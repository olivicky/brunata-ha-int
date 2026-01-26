"""DataUpdateCoordinator for Brunata."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from datetime import timedelta
import logging
from typing import Any

from brunata_api import BrunataClient, ReadingKind
from brunata_api.errors import LoginError
from brunata_api.models import CurrentConsumption, MeterReading, Reading
import httpx
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components.recorder.statistics import async_list_statistic_ids
from homeassistant.components.recorder.util import get_instance as get_recorder_instance
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_BASE_URL, CONF_SAP_CLIENT, CONF_SAP_LANGUAGE, DOMAIN
from .statistics_import import import_series_as_sum

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class _KwhHistory:
    current: MeterReading
    history: list[MeterReading]
    monthly_kwh: list[Reading]


def _is_kwh_unit(unit: str | None) -> bool:
    if not unit:
        return False
    return "kwh" in unit.lower()


def _backcalculate_kwh_history(
    *,
    current: MeterReading,  # unit must be kWh
    monthly: list[Reading],
) -> list[MeterReading]:
    """Back-calculate cumulative kWh readings from monthly kWh consumption."""
    if not monthly:
        return [current]

    monthly_sorted = sorted(monthly, key=lambda r: r.timestamp)
    current_value = float(current.value)

    out_rev: list[MeterReading] = []
    # Only use monthly points up to the current timestamp (active period).
    monthly_upto = [m for m in monthly_sorted if m.timestamp <= current.timestamp]
    for m in reversed(monthly_upto):
        before = current_value
        out_rev.append(
            MeterReading(
                timestamp=m.timestamp,
                value=round(current_value, 6),
                unit=current.unit,
                cost_type=current.cost_type,
                kind=current.kind,
            )
        )

        current_value -= float(m.value)
        if current_value < -1e-6:
            _LOGGER.warning(
                "Back-calculated kWh reading went negative for cost_type=%s at %s "
                "(unit=%s). Stopping backfill. before=%s, subtract=%s, after=%s, api_current=%s",
                current.cost_type,
                m.timestamp.isoformat(),
                current.unit,
                round(before, 6),
                m.value,
                round(current_value, 6),
                current.value,
            )
            break

    out_rev.append(current)
    uniq: dict[datetime, MeterReading] = {}
    for r in out_rev:
        ts = r.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        uniq[ts] = r
    return sorted(uniq.values(), key=lambda r: r.timestamp)


class BrunataDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch Brunata data and store it for entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.entry = entry
        self._client: BrunataClient | None = None
        self._client_lock = asyncio.Lock()
        self._cleared_obsolete_statistics = False

    async def async_shutdown(self) -> None:
        """Close resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _async_get_client(self) -> BrunataClient:
        """Create the API client off the event loop (SSL setup can block)."""
        if self._client is not None:
            return self._client

        async with self._client_lock:
            if self._client is not None:
                return self._client

            def _create() -> BrunataClient:
                return BrunataClient(
                    base_url=self.entry.data[CONF_BASE_URL],
                    username=self.entry.data[CONF_USERNAME],
                    password=self.entry.data[CONF_PASSWORD],
                    sap_client=self.entry.data.get(CONF_SAP_CLIENT, "201"),
                    sap_language=self.entry.data.get(CONF_SAP_LANGUAGE, "DE"),
                )

            self._client = await self.hass.async_add_executor_job(_create)
            return self._client

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Brunata."""
        client = await self._async_get_client()

        try:
            # Ensure we only log in once.
            # The API client doesn't guard login() with a lock, so running several
            # requests concurrently can trigger multiple simultaneous logins and fail.
            account = await client.get_account()

            dashboard_dates_task = client.get_dashboard_dates()
            meter_readings_task = client.get_meter_readings()
            current_heating_task = client.get_current_consumption(ReadingKind.heating)
            current_hot_water_task = client.get_current_consumption(ReadingKind.hot_water)

            (
                dashboard_dates,
                meter_readings,
                current_heating,
                current_hot_water,
            ) = await asyncio.gather(
                dashboard_dates_task,
                meter_readings_task,
                current_heating_task,
                current_hot_water_task,
            )

            # Monthly consumption series depends on the discovered cost types.
            monthly_heating = await client.get_monthly_consumption(
                cost_type=current_heating.cost_type, in_kwh=True
            )
            monthly_hot_water = await client.get_monthly_consumption(
                cost_type=current_hot_water.cost_type, in_kwh=True
            )

            data: dict[str, Any] = {
                "account": account,
                # Keep the existing keys for backwards-compatibility with entity ids.
                "monthly_hz01": monthly_heating,
                "monthly_ww01": monthly_hot_water,
                "dashboard_dates": dashboard_dates,
                "meter_readings": meter_readings,
                "current_heating": current_heating,
                "current_hot_water": current_hot_water,
            }

            # Build a synthetic "kWh meter" (total_increasing) from brunata current (kWh)
            # and back-calculate earlier cumulative points from monthly kWh.
            kwh_meter_readings: list[MeterReading] = [
                MeterReading(
                    timestamp=current_heating.as_of,
                    value=float(current_heating.value),
                    unit=current_heating.unit,
                    cost_type=current_heating.cost_type,
                    kind=current_heating.kind,
                ),
                MeterReading(
                    timestamp=current_hot_water.as_of,
                    value=float(current_hot_water.value),
                    unit=current_hot_water.unit,
                    cost_type=current_hot_water.cost_type,
                    kind=current_hot_water.kind,
                ),
            ]
            data["kwh_meter_readings"] = kwh_meter_readings

            kwh_histories: dict[str, _KwhHistory] = {}
            for km in kwh_meter_readings:
                if not _is_kwh_unit(km.unit):
                    continue
                monthly_for_kwh = (
                    monthly_heating if km.kind == ReadingKind.heating else monthly_hot_water
                )
                history = _backcalculate_kwh_history(current=km, monthly=monthly_for_kwh)
                kwh_histories[km.cost_type] = _KwhHistory(
                    current=km, history=history, monthly_kwh=monthly_for_kwh
                )
            data["kwh_histories"] = kwh_histories

            uid = self.entry.unique_id or self.entry.entry_id

            # One-time cleanup: remove obsolete statistic_ids from earlier iterations
            # so they don't show up in Energy dashboard selection.
            if not self._cleared_obsolete_statistics:
                self._cleared_obsolete_statistics = True
                try:
                    ids = await async_list_statistic_ids(self.hass)
                    obsolete = [
                        i["statistic_id"]
                        for i in ids
                        if i.get("statistic_id", "").startswith(f"{DOMAIN}:{uid}_")
                        and (
                            "_meter_" in i.get("statistic_id", "")
                            or "_monthly_" in i.get("statistic_id", "")
                        )
                    ]
                    if obsolete:
                        get_recorder_instance(self.hass).async_clear_statistics(obsolete)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Failed to clear obsolete statistics: %s", err)

            # Backfill ONLY the synthetic cumulative kWh series (not the physical meters).
            for cost_type, kh in kwh_histories.items():
                label = "Heizung" if kh.current.kind == ReadingKind.heating else "Warmwasser"
                import_series_as_sum(
                    self.hass,
                    statistic_id=f"{DOMAIN}:{uid}_kwh_total_{cost_type.lower()}",
                    name=f"Brunata {uid} – {label} – Verbrauch (kumulativ, kWh)",
                    unit=kh.current.unit,
                    points=((r.timestamp, float(r.value)) for r in kh.history),
                )

            return data
        except LoginError as err:
            raise ConfigEntryAuthFailed("Brunata authentication failed") from err
        except (httpx.HTTPError, TimeoutError) as err:
            raise UpdateFailed(f"Brunata communication error: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Unexpected Brunata error: {err}") from err

