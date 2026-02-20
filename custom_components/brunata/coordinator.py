"""DataUpdateCoordinator for Brunata."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from brunata_api import BrunataClient, ReadingKind
from brunata_api.errors import LoginError
from brunata_api.models import MeterReading, Reading
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


def _kind_from_cost_type(cost_type: str) -> ReadingKind:
    if cost_type.startswith("HZ"):
        return ReadingKind.heating
    if cost_type.startswith("WW"):
        return ReadingKind.hot_water
    # Fallback: heating
    return ReadingKind.heating


def _cumulative_kwh_history(
    *, cost_type: str, monthly: list[Reading]
) -> tuple[ReadingKind, str | None, list[MeterReading]]:
    """Build a cumulative (sum) kWh series from monthly kWh readings."""
    kind = _kind_from_cost_type(cost_type)
    monthly_sorted = sorted(monthly, key=lambda r: r.timestamp)
    unit = monthly_sorted[-1].unit if monthly_sorted else "kWh"
    unit = unit or "kWh"

    total = 0.0
    history: list[MeterReading] = []
    for r in monthly_sorted:
        total += float(r.value)
        history.append(
            MeterReading(
                timestamp=r.timestamp,
                value=round(total, 6),
                unit=unit,
                cost_type=cost_type,
                kind=kind,
            )
        )

    return kind, unit, history


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
            periods_task = client.get_periods()

            (
                dashboard_dates,
                meter_readings_by_cost_type,
                periods,
            ) = await asyncio.gather(
                dashboard_dates_task,
                meter_readings_task,
                periods_task,
            )

            # Fetch monthly consumption for all periods and merge per cost_type so the
            # cumulative series spans all years (avoids Energy dashboard "reset" at new year).
            monthly_by_cost_type: dict[str, list[Reading]] = {}
            for i in range(len(periods)):
                heating_i, hot_water_i = await asyncio.gather(
                    client.get_monthly_consumptions(
                        ReadingKind.heating, in_kwh=True, period_index=i
                    ),
                    client.get_monthly_consumptions(
                        ReadingKind.hot_water, in_kwh=True, period_index=i
                    ),
                )
                for ct, readings in (heating_i or {}).items():
                    monthly_by_cost_type.setdefault(ct, []).extend(readings)
                for ct, readings in (hot_water_i or {}).items():
                    monthly_by_cost_type.setdefault(ct, []).extend(readings)
            for ct in monthly_by_cost_type:
                monthly_by_cost_type[ct] = sorted(
                    monthly_by_cost_type[ct], key=lambda r: r.timestamp
                )

            comparison_task = client.get_consumption_comparison()
            forecast_task = client.get_consumption_forecast()
            room_task = client.get_room_consumption()

            comparison_by_cost_type, forecast_by_cost_type, room_by_cost_type = await asyncio.gather(
                comparison_task, forecast_task, room_task
            )

            data: dict[str, Any] = {
                "account": account,
                "dashboard_dates": dashboard_dates,
                # New multi-cost-type model
                "meter_readings_by_cost_type": meter_readings_by_cost_type or {},
                "monthly_by_cost_type": monthly_by_cost_type,
                "comparison_by_cost_type": comparison_by_cost_type or {},
                "forecast_by_cost_type": forecast_by_cost_type or {},
                "room_by_cost_type": room_by_cost_type or {},
            }

            kwh_histories_by_cost_type: dict[str, list[MeterReading]] = {}
            kwh_totals_by_cost_type: dict[str, MeterReading] = {}
            for cost_type, monthly in monthly_by_cost_type.items():
                if not monthly:
                    continue
                _kind, _unit, history = _cumulative_kwh_history(cost_type=cost_type, monthly=monthly)
                if not history:
                    continue
                kwh_histories_by_cost_type[cost_type] = history
                kwh_totals_by_cost_type[cost_type] = history[-1]
            data["kwh_histories_by_cost_type"] = kwh_histories_by_cost_type
            data["kwh_totals_by_cost_type"] = kwh_totals_by_cost_type

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
            for cost_type, history in kwh_histories_by_cost_type.items():
                kind = _kind_from_cost_type(cost_type)
                label = "Heizung" if kind == ReadingKind.heating else "Warmwasser"
                unit = history[-1].unit if history else None
                import_series_as_sum(
                    self.hass,
                    statistic_id=f"{DOMAIN}:{uid}_kwh_total_{cost_type.lower()}",
                    name=f"Brunata {uid} – {label} – {cost_type} – Verbrauch (kumulativ, kWh)",
                    unit=unit,
                    points=((r.timestamp, float(r.value)) for r in history),
                )

            return data
        except LoginError as err:
            raise ConfigEntryAuthFailed("Brunata authentication failed") from err
        except (httpx.HTTPError, TimeoutError) as err:
            raise UpdateFailed(f"Brunata communication error: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Unexpected Brunata error: {err}") from err

