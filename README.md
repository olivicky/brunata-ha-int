## Brunata Home Assistant Integration (Custom Component)

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

### Anmeldung / Konfiguration

Du brauchst Zugangsdaten, die im Brunata-Portal funktionieren.
Im Config-Flow kannst du u. a. **Base URL**, **SAP Client** und **Sprache** setzen (standardmäßig passend für das Münchner Portal).

### Sensoren (Entities)

- **Heizung – Monatsverbrauch (kWh)** (`sensor.*monthly_hz01`)
- **Warmwasser – Monatsverbrauch (kWh)** (`sensor.*monthly_ww01`)
- **Heizung – Zählerstand (Meter)** (aus `brunata meter`, Einheit z. B. *Einh.*)
- **Warmwasser – Zählerstand (Meter)** (aus `brunata meter`, Einheit z. B. *m³*)
- **Heizung – Verbrauch (kumulativ, kWh)** (aus `brunata current`, als `total_increasing`)
- **Warmwasser – Verbrauch (kumulativ, kWh)** (aus `brunata current`, als `total_increasing`)
- **Dashboard-Perioden** (Diagnose)

### Historie / Recorder (wichtig)

- Die **kWh kumulativ** Sensoren werden zusätzlich als **Long-term statistics** in den Recorder geschrieben.
- Beim ersten Lauf wird die kWh-Historie aus den Monatswerten rückwärts rekonstruiert (Backtracking).

### Sicherheit & Datenschutz

- Diese Integration nutzt deine Portal-Zugangsdaten, um Daten aus dem Brunata-Portal abzurufen.
- Teile Logs/Dumps nur anonymisiert, da sie personenbezogene Daten enthalten können.

