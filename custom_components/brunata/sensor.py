"""Sensors for the Brunata integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from brunata_api import ReadingKind
from brunata_api.models import MeterReading, Reading
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import BrunataDataCoordinator


ReadingLike = Reading | MeterReading


def _latest(readings: list[ReadingLike]) -> ReadingLike | None:
    return readings[-1] if readings else None


def _reading_attrs(readings: list[ReadingLike], *, limit: int = 24) -> dict[str, Any]:
    tail = readings[-limit:] if len(readings) > limit else readings
    return {
        "history": [
            {
                "timestamp": r.timestamp.isoformat(),
                "value": r.value,
                "unit": r.unit,
                "kind": r.kind.value,
                **({"cost_type": r.cost_type} if isinstance(r, MeterReading) else {}),
            }
            for r in tail
        ]
    }


@dataclass(frozen=True)
class _SensorDef:
    key: str
    name: str
    kind: str
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    entity_category: EntityCategory | None = None


SENSORS: tuple[_SensorDef, ...] = (
    _SensorDef(
        key="monthly_hz01",
        name="Heizung – Monatsverbrauch (kWh)",
        kind="monthly_hz01",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    _SensorDef(
        key="monthly_ww01",
        name="Warmwasser – Monatsverbrauch (kWh)",
        kind="monthly_ww01",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    _SensorDef(
        key="meter_hz",
        name="Heizung – Zählerstand (Meter)",
        kind="meter_hz",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _SensorDef(
        key="meter_ww",
        name="Warmwasser – Zählerstand (Meter)",
        kind="meter_ww",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _SensorDef(
        key="kwh_total_hz",
        name="Heizung – Verbrauch (kumulativ, kWh)",
        kind="kwh_total_hz",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _SensorDef(
        key="kwh_total_ww",
        name="Warmwasser – Verbrauch (kumulativ, kWh)",
        kind="kwh_total_ww",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _SensorDef(
        key="dashboard_dates",
        name="Dashboard-Perioden",
        kind="dashboard_dates",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BrunataDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BrunataSensor(coordinator, entry, d) for d in SENSORS)


class BrunataSensor(CoordinatorEntity[BrunataDataCoordinator], SensorEntity):
    """A sensor backed by the Brunata coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BrunataDataCoordinator, entry: ConfigEntry, definition: _SensorDef) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._def = definition

        uid = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{uid}_{definition.key}"

        self._attr_name = definition.name
        self._attr_device_class = definition.device_class
        self._attr_state_class = definition.state_class
        self._attr_entity_category = definition.entity_category

    @property
    def device_info(self) -> DeviceInfo:
        uid = self._entry.unique_id or self._entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, uid)},
            name=f"Brunata ({uid})",
            manufacturer="Brunata",
        )

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self._def.kind == "dashboard_dates":
            return None

        readings = self._get_readings()
        r = _latest(readings)
        return r.unit if r else None

    @property
    def native_value(self) -> float | int | str | None:
        if self._def.kind == "dashboard_dates":
            periods = _extract_periods(self.coordinator.data.get("dashboard_dates"))
            return len(periods)

        r = _latest(self._get_readings())
        return r.value if r else None

    @property
    def last_reset(self) -> datetime | None:
        """Return last_reset for period totals (monthly consumption).

        For monthly consumption we expose the month-total as a 'total' sensor which resets
        at the beginning of each month.
        """
        if self._def.kind not in ("monthly_hz01", "monthly_ww01"):
            return None
        latest = _latest(self._get_readings())
        if not isinstance(latest, Reading):
            return None
        ts = dt_util.as_utc(latest.timestamp)
        return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._def.kind == "dashboard_dates":
            return {"periods": _extract_periods(self.coordinator.data.get("dashboard_dates"))}

        readings = self._get_readings()
        attrs: dict[str, Any] = _reading_attrs(readings)
        latest = _latest(readings)
        if latest is not None:
            attrs["timestamp"] = latest.timestamp.isoformat()
            if isinstance(latest, MeterReading):
                attrs["cost_type"] = latest.cost_type
        return attrs

    def _get_readings(self) -> list[ReadingLike]:
        data = self.coordinator.data or {}

        if self._def.kind == "monthly_hz01":
            return list(data.get("monthly_hz01") or [])
        if self._def.kind == "monthly_ww01":
            return list(data.get("monthly_ww01") or [])
        if self._def.kind == "meter_hz":
            readings: list[MeterReading] = list(data.get("meter_readings") or [])
            return [r for r in readings if r.kind == ReadingKind.heating]
        if self._def.kind == "meter_ww":
            readings = list(data.get("meter_readings") or [])
            return [r for r in readings if r.kind == ReadingKind.hot_water]
        if self._def.kind == "kwh_total_hz":
            readings: list[MeterReading] = list(data.get("kwh_meter_readings") or [])
            return [r for r in readings if r.kind == ReadingKind.heating]
        if self._def.kind == "kwh_total_ww":
            readings = list(data.get("kwh_meter_readings") or [])
            return [r for r in readings if r.kind == ReadingKind.hot_water]
        return []


def _extract_periods(dashboard_dates: Any) -> list[dict[str, Any]]:
    """Extract a compact list of periods from Brunata dashboard date payload."""
    if not isinstance(dashboard_dates, dict):
        return []

    results = (dashboard_dates.get("d") or {}).get("results") or []
    if not isinstance(results, list):
        return []

    out: list[dict[str, Any]] = []
    for period in results:
        if not isinstance(period, dict):
            continue
        units = ((period.get("Units") or {}).get("results") or []) if isinstance(period.get("Units"), dict) else []
        cost_types = sorted(
            {
                r.get("CostType")
                for r in units
                if isinstance(r, dict) and isinstance(r.get("CostType"), str) and r.get("CostType")
            }
        )
        out.append(
            {
                "from": period.get("Abdatum"),
                "to": period.get("Bisdatum"),
                "cost_types": cost_types,
            }
        )
    return out

