"""Config flow for Brunata."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from brunata_api import BrunataClient
from brunata_api.errors import LoginError
import httpx
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.selector import DurationSelector, DurationSelectorConfig
import voluptuous as vol

from .const import (
    CONF_BASE_URL,
    CONF_SAP_CLIENT,
    CONF_SAP_LANGUAGE,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SAP_CLIENT,
    DEFAULT_SAP_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

def _seconds_to_duration_dict(total_seconds: int) -> dict[str, int]:
    """Convert seconds into a duration dict for DurationSelector defaults."""
    total_seconds = max(0, int(total_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return {
        "days": days,
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
    }


@dataclass(frozen=True)
class _ValidatedAccount:
    user_unit_id: str


async def _async_validate_input(hass: HomeAssistant, data: dict[str, Any]) -> _ValidatedAccount:
    """Validate the user input allows us to connect."""
    # Construct client off the event loop (SSL setup can block).
    def _create() -> BrunataClient:
        return BrunataClient(
            base_url=data[CONF_BASE_URL],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            sap_client=data[CONF_SAP_CLIENT],
            sap_language=data[CONF_SAP_LANGUAGE],
        )

    client = await hass.async_add_executor_job(_create)
    try:
        account = await client.get_account()
        user_unit_id = str(account.get("UserUnitID") or "").strip()
        if not user_unit_id:
            raise LoginError("Missing UserUnitID")
        return _ValidatedAccount(user_unit_id=user_unit_id)
    finally:
        await client.aclose()


class BrunataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Brunata."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                validated = await _async_validate_input(self.hass, user_input)
            except LoginError:
                errors["base"] = "invalid_auth"
            except (httpx.HTTPError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error while validating Brunata credentials")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(validated.user_unit_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Brunata ({validated.user_unit_id})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_SAP_CLIENT, default=DEFAULT_SAP_CLIENT): cv.string,
                vol.Optional(CONF_SAP_LANGUAGE, default=DEFAULT_SAP_LANGUAGE): cv.string,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return BrunataOptionsFlow(config_entry)


class BrunataOptionsFlow(config_entries.OptionsFlow):
    """Handle Brunata options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            # DurationSelector yields a dict; convert to seconds (json-serializable).
            duration = cv.time_period(user_input[CONF_SCAN_INTERVAL])
            seconds = int(duration.total_seconds())
            seconds = max(60, seconds)  # clamp to at least 1 minute
            return self.async_create_entry(title="", data={CONF_SCAN_INTERVAL: seconds})

        current_seconds = self._entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS)
        if not isinstance(current_seconds, (int, float)):
            current_seconds = int(DEFAULT_SCAN_INTERVAL.total_seconds())

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=_seconds_to_duration_dict(int(current_seconds)),
                ): DurationSelector(DurationSelectorConfig(enable_day=True))
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

