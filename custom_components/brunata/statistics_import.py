"""Recorder/Statistics import helpers for Brunata.

We use Home Assistant's statistics import API to backfill historical values into the
recorder database. This is the supported way to write "past" data.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from homeassistant.components.recorder.models.statistics import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _as_utc_hour(dt: datetime) -> datetime:
    """Ensure timestamp is UTC and aligned to top-of-hour."""
    dt_utc = dt_util.as_utc(dt)
    return dt_utc.replace(minute=0, second=0, microsecond=0)


def _unit_class_for_unit(unit: str | None) -> str | None:
    """Best-effort mapping to HA unit converters."""
    if unit is None:
        return None
    if unit in EnergyConverter.VALID_UNITS:
        return EnergyConverter.UNIT_CLASS
    if unit in VolumeConverter.VALID_UNITS:
        return VolumeConverter.UNIT_CLASS
    return None


def import_series_as_state(
    hass: HomeAssistant,
    *,
    statistic_id: str,
    name: str,
    unit: str | None,
    points: Iterable[tuple[datetime, float]],
) -> None:
    """Import a series as state-only statistics (no cumulative sum)."""
    stats: list[StatisticData] = [
        StatisticData(start=_as_utc_hour(ts), state=float(val)) for ts, val in points
    ]
    if not stats:
        return

    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=False,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=_unit_class_for_unit(unit),
        unit_of_measurement=unit,
    )

    try:
        _LOGGER.info(
            "Importing %d external statistics points for %s (%s)",
            len(stats),
            statistic_id,
            unit or "no-unit",
        )
        async_add_external_statistics(hass=hass, metadata=metadata, statistics=stats)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed importing external statistics %s: %s", statistic_id, err, exc_info=True)


def import_series_as_sum(
    hass: HomeAssistant,
    *,
    statistic_id: str,
    name: str,
    unit: str | None,
    points: Iterable[tuple[datetime, float]],
) -> None:
    """Import a series as cumulative (sum) statistics."""
    stats: list[StatisticData] = [
        StatisticData(start=_as_utc_hour(ts), state=float(val), sum=float(val))
        for ts, val in points
    ]
    if not stats:
        return

    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=_unit_class_for_unit(unit),
        unit_of_measurement=unit,
    )

    try:
        _LOGGER.info(
            "Importing %d external statistics points for %s (%s)",
            len(stats),
            statistic_id,
            unit or "no-unit",
        )
        async_add_external_statistics(hass=hass, metadata=metadata, statistics=stats)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed importing external statistics %s: %s", statistic_id, err, exc_info=True)


def safe_float(v: Any) -> float | None:
    """Convert to float if possible."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

