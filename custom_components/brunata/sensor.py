"""Sensors for the Brunata integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from brunata_api.models import (
    ConsumptionComparison,
    ConsumptionForecast,
    MeterReading,
    Reading,
    RoomConsumption,
)
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


def _label_for_cost_type(cost_type: str) -> str:
    if cost_type.startswith("HZ"):
        return "Heizung"
    if cost_type.startswith("WW"):
        return "Warmwasser"
    return cost_type


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BrunataDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data or {}

    meter_by_cost_type: dict[str, MeterReading] = dict(data.get("meter_readings_by_cost_type") or {})
    monthly_by_cost_type: dict[str, list[Reading]] = dict(data.get("monthly_by_cost_type") or {})
    kwh_histories_by_cost_type: dict[str, list[MeterReading]] = dict(
        data.get("kwh_histories_by_cost_type") or {}
    )
    comparison_by_cost_type: dict[str, ConsumptionComparison] = dict(
        data.get("comparison_by_cost_type") or {}
    )
    forecast_by_cost_type: dict[str, ConsumptionForecast] = dict(
        data.get("forecast_by_cost_type") or {}
    )
    room_by_cost_type: dict[str, list[RoomConsumption]] = dict(
        data.get("room_by_cost_type") or {}
    )

    cost_types = sorted({
        *meter_by_cost_type.keys(),
        *monthly_by_cost_type.keys(),
        *comparison_by_cost_type.keys(),
        *forecast_by_cost_type.keys(),
        *room_by_cost_type.keys(),
    })

    entities: list[BrunataSensor] = []

    # Always keep a diagnostics entity for dashboard periods.
    entities.append(
        BrunataSensor(
            coordinator,
            entry,
            _SensorDef(
                key="dashboard_dates",
                name="Dashboard-Perioden",
                kind="dashboard_dates",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
        )
    )

    for cost_type in cost_types:
        label = _label_for_cost_type(cost_type)

        if monthly_by_cost_type.get(cost_type):
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"monthly_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Monatsverbrauch (kWh)",
                        kind=f"monthly:{cost_type}",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.TOTAL,
                    ),
                )
            )

        if meter_by_cost_type.get(cost_type):
            device_class = SensorDeviceClass.WATER if cost_type.startswith("WW") else None
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"meter_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Zählerstand (Meter)",
                        kind=f"meter:{cost_type}",
                        device_class=device_class,
                        state_class=SensorStateClass.TOTAL_INCREASING,
                    ),
                )
            )

        if kwh_histories_by_cost_type.get(cost_type) or monthly_by_cost_type.get(cost_type):
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"kwh_total_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Verbrauch (kumulativ, kWh)",
                        kind=f"kwh_total:{cost_type}",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.TOTAL_INCREASING,
                    ),
                )
            )

        if comparison_by_cost_type.get(cost_type):
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"comparison_your_value_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Verbrauch (kWh/m²)",
                        kind=f"comparison_your:{cost_type}",
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"comparison_building_avg_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Gebäudedurchschnitt",
                        kind=f"comparison_building:{cost_type}",
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"comparison_national_avg_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Bundesdurchschnitt",
                        kind=f"comparison_national:{cost_type}",
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )

        if forecast_by_cost_type.get(cost_type):
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"forecast_current_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Aktuell (YTD)",
                        kind=f"forecast_current:{cost_type}",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.TOTAL,
                    ),
                )
            )
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"forecast_previous_year_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Vorjahr",
                        kind=f"forecast_previous:{cost_type}",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"forecast_forecast_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Prognose",
                        kind=f"forecast_forecast:{cost_type}",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"forecast_difference_{cost_type.lower()}",
                        name=f"{label} – {cost_type} – Mehrverbrauch",
                        kind=f"forecast_difference:{cost_type}",
                        device_class=SensorDeviceClass.ENERGY,
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )

        for room in room_by_cost_type.get(cost_type) or []:
            room_id = (room.room_id or "").strip() or "unknown"
            room_name = (room.room_name or "").strip() or room_id
            safe_key = room_id.replace(" ", "_").lower()
            entities.append(
                BrunataSensor(
                    coordinator,
                    entry,
                    _SensorDef(
                        key=f"room_{safe_key}_{cost_type.lower()}",
                        name=f"Raum: {room_name} – {cost_type}",
                        kind=f"room:{cost_type}:{room_id}",
                        state_class=SensorStateClass.MEASUREMENT,
                    ),
                )
            )

    async_add_entities(entities)


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

        unit = self._unit_for_extra_kinds()
        if unit is not None:
            return unit

        readings = self._get_readings()
        r = _latest(readings)
        return r.unit if r else None

    @property
    def native_value(self) -> float | int | str | None:
        if self._def.kind == "dashboard_dates":
            periods = _extract_periods(self.coordinator.data.get("dashboard_dates"))
            return len(periods)

        val = self._value_for_extra_kinds()
        if val is not None:
            return val

        r = _latest(self._get_readings())
        return r.value if r else None

    @property
    def last_reset(self) -> datetime | None:
        """Return last_reset for period totals (monthly consumption, forecast current YTD)."""
        if self._def.kind.startswith("monthly:"):
            latest = _latest(self._get_readings())
            if not isinstance(latest, Reading):
                return None
            ts = dt_util.as_utc(latest.timestamp)
            return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if self._def.kind.startswith("forecast_current:"):
            now = dt_util.now()
            return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._def.kind == "dashboard_dates":
            return {"periods": _extract_periods(self.coordinator.data.get("dashboard_dates"))}

        attrs_extra = self._attrs_for_extra_kinds()
        if attrs_extra is not None:
            return attrs_extra

        readings = self._get_readings()
        attrs: dict[str, Any] = _reading_attrs(readings)
        latest = _latest(readings)
        if latest is not None:
            attrs["timestamp"] = latest.timestamp.isoformat()
            if isinstance(latest, MeterReading):
                attrs["cost_type"] = latest.cost_type
        return attrs

    def _value_for_extra_kinds(self) -> float | None:
        """Return native_value for comparison/forecast/room kinds, or None."""
        data = self.coordinator.data or {}
        if self._def.kind.startswith("comparison_"):
            sub, cost_type = self._def.kind.split(":", 1)
            comp: ConsumptionComparison | None = (data.get("comparison_by_cost_type") or {}).get(cost_type)
            if not comp:
                return None
            if "your" in sub:
                return comp.your_value
            if "building" in sub:
                return comp.building_average
            if "national" in sub:
                return comp.national_average
            return None
        if self._def.kind.startswith("forecast_"):
            sub, cost_type = self._def.kind.split(":", 1)
            fc: ConsumptionForecast | None = (data.get("forecast_by_cost_type") or {}).get(cost_type)
            if not fc:
                return None
            if sub == "forecast_current":
                return fc.current
            if sub == "forecast_previous":
                return fc.previous_year
            if sub == "forecast_forecast":
                return fc.forecast
            if sub == "forecast_difference":
                return fc.difference
            return None
        if self._def.kind.startswith("room:"):
            _, cost_type, room_id = self._def.kind.split(":", 2)
            rooms: list[RoomConsumption] = (data.get("room_by_cost_type") or {}).get(cost_type) or []
            for r in rooms:
                if (r.room_id or "").strip() == room_id:
                    return r.value
            return None
        return None

    def _unit_for_extra_kinds(self) -> str | None:
        """Return native_unit for comparison/forecast/room kinds, or None."""
        data = self.coordinator.data or {}
        if self._def.kind.startswith("comparison_"):
            _, cost_type = self._def.kind.split(":", 1)
            comp: ConsumptionComparison | None = (data.get("comparison_by_cost_type") or {}).get(cost_type)
            return (comp.unit if comp else None) or "kWh/m²"
        if self._def.kind.startswith("forecast_"):
            _, cost_type = self._def.kind.split(":", 1)
            fc: ConsumptionForecast | None = (data.get("forecast_by_cost_type") or {}).get(cost_type)
            return (fc.unit if fc else None) or "kWh"
        if self._def.kind.startswith("room:"):
            _, cost_type, room_id = self._def.kind.split(":", 2)
            rooms: list[RoomConsumption] = (data.get("room_by_cost_type") or {}).get(cost_type) or []
            for r in rooms:
                if (r.room_id or "").strip() == room_id:
                    return r.unit
            return None
        return None

    def _attrs_for_extra_kinds(self) -> dict[str, Any] | None:
        """Return extra_state_attributes for comparison/forecast/room kinds, or None."""
        if self._def.kind.startswith("room:"):
            data = self.coordinator.data or {}
            _, cost_type, room_id = self._def.kind.split(":", 2)
            rooms: list[RoomConsumption] = (data.get("room_by_cost_type") or {}).get(cost_type) or []
            for r in rooms:
                if (r.room_id or "").strip() == room_id:
                    return {
                        "room_id": r.room_id,
                        "room_name": r.room_name,
                        "share_percent": r.share_percent,
                        "cost_type": r.cost_type,
                    }
            return {}
        return None

    def _get_readings(self) -> list[ReadingLike]:
        data = self.coordinator.data or {}

        if self._def.kind.startswith("monthly:"):
            _, cost_type = self._def.kind.split(":", 1)
            monthly_by_cost_type: dict[str, list[Reading]] = dict(data.get("monthly_by_cost_type") or {})
            return list(monthly_by_cost_type.get(cost_type) or [])

        if self._def.kind.startswith("meter:"):
            _, cost_type = self._def.kind.split(":", 1)
            meter_by_cost_type: dict[str, MeterReading] = dict(data.get("meter_readings_by_cost_type") or {})
            r = meter_by_cost_type.get(cost_type)
            return [r] if r else []

        if self._def.kind.startswith("kwh_total:"):
            _, cost_type = self._def.kind.split(":", 1)
            histories_by_cost_type: dict[str, list[MeterReading]] = dict(
                data.get("kwh_histories_by_cost_type") or {}
            )
            return list(histories_by_cost_type.get(cost_type) or [])

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

