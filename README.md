## Brunata Home Assistant Integration

This repository contains a **Home Assistant custom integration** for the Brunata user portal.

### Installation

#### Home Assistant OS / Supervised

- Copy the folder `custom_components/brunata/` to:
  - `/config/custom_components/brunata/`
- Restart Home Assistant.
- Open **Settings → Devices & Services → Add Integration → Brunata**.

#### Home Assistant Core (venv)

- Copy the folder `custom_components/brunata/` into your HA config directory:
  - `<config>/custom_components/brunata/`
- Restart Home Assistant.

### Installation via HACS (Custom Repository)

- Add the repository as a **Custom repository** in HACS (type: **Integration**):
  - `https://github.com/fjfricke/brunata`
- Then install **Brunata** and restart Home Assistant.

### Login / Configuration

You need portal credentials that work with the Brunata portal.
In the config flow you can set **Base URL**, **SAP client**, and **language** (defaults fit the Munich portal).

You can change the update interval via the options flow.

### Sensoren (Entities)

- For each `CostType` (e.g. `HZ01`, `HZ02`, `WW01` …) separate sensors are created:
  - **Monthly consumption (kWh)** (`sensor.*monthly_<cost_type>`)
  - **Meter reading** (`sensor.*meter_<cost_type>`, unit e.g. *Einh.* or *m³*)
  - **Cumulative consumption (kWh)** (`sensor.*kwh_total_<cost_type>`, `total_increasing`)
- **Dashboard periods** (diagnostic)

### History / Recorder (important)

- The **cumulative kWh** sensors are also written as **long-term statistics** into the recorder.
- The cumulative kWh history is built as a cumulative sum from the monthly values and imported.

### Security & Privacy

- This integration uses your portal credentials to fetch data from the Brunata portal.
- Only share logs/dumps in anonymized form, as they may contain personal data.

