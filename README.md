## Brunata Home Assistant Integration

Diese Repository enthält eine **Home Assistant Custom Integration** für das Brunata Nutzerportal.

### Installation

#### Home Assistant OS / Supervised

- Kopiere den Ordner `custom_components/brunata/` nach:
  - `/config/custom_components/brunata/`
- Starte Home Assistant neu.
- Öffne **Einstellungen → Geräte & Dienste → Integration hinzufügen → Brunata**.

#### Home Assistant Core (venv)

- Kopiere den Ordner `custom_components/brunata/` in dein HA-Konfigurationsverzeichnis:
  - `<config>/custom_components/brunata/`
- Starte Home Assistant neu.

### Installation via HACS (Custom Repository)

- Füge das Repository als **Custom repository** in HACS hinzu (Typ: **Integration**):
  - `https://github.com/fjfricke/brunata`
- Installiere anschließend **Brunata** und starte Home Assistant neu.

### Anmeldung / Konfiguration

Du brauchst Zugangsdaten, die im Brunata-Portal funktionieren.
Im Config-Flow kannst du u. a. **Base URL**, **SAP Client** und **Sprache** setzen (standardmäßig passend für das Münchner Portal).

Über die Optionen kannst du das Aktualisierungsintervall ändern.

### Sensoren (Entities)

- Pro `CostType` (z. B. `HZ01`, `HZ02`, `WW01` …) werden eigene Sensoren erzeugt:
  - **Monatsverbrauch (kWh)** (`sensor.*monthly_<cost_type>`)
  - **Zählerstand (Meter)** (`sensor.*meter_<cost_type>`, Einheit z. B. *Einh.* oder *m³*)
  - **Verbrauch (kumulativ, kWh)** (`sensor.*kwh_total_<cost_type>`, `total_increasing`)
- **Dashboard-Perioden** (Diagnose)

### Historie / Recorder (wichtig)

- Die **kWh kumulativ** Sensoren werden zusätzlich als **Long-term statistics** in den Recorder geschrieben.
- Die kumulative kWh-Historie wird aus den Monatswerten als kumulative Summe aufgebaut und importiert.

### Sicherheit & Datenschutz

- Diese Integration nutzt deine Portal-Zugangsdaten, um Daten aus dem Brunata-Portal abzurufen.
- Teile Logs/Dumps nur anonymisiert, da sie personenbezogene Daten enthalten können.

