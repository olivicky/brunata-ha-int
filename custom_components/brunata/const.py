"""Constants for the Brunata integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "brunata"

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONF_BASE_URL = "base_url"
CONF_SAP_CLIENT = "sap_client"
CONF_SAP_LANGUAGE = "sap_language"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_BASE_URL = "https://nutzerportal.brunata-muenchen.de"
DEFAULT_SAP_CLIENT = "201"
DEFAULT_SAP_LANGUAGE = "DE"
DEFAULT_SCAN_INTERVAL = timedelta(days=1)
DEFAULT_SCAN_INTERVAL_SECONDS = int(DEFAULT_SCAN_INTERVAL.total_seconds())

ATTR_PERIODS = "periods"
ATTR_LAST_UPDATE_SUCCESS = "last_update_success"

