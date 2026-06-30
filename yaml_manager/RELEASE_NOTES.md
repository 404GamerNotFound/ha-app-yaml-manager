# Release Notes 1.10.0

Veröffentlicht am 30. Juni 2026.

## Grundkonfiguration

Die App prüft jetzt, ob zentrale Home-Assistant-Grundlagen bereits in
`configuration.yaml` oder in geladenen Packages definiert sind.

Geprüft werden unter anderem:

- `homeassistant.packages`
- `default_config`
- `recorder`
- `logger`
- `automation`
- `script`
- `scene`
- `history`
- `logbook`
- `system_health`

Fehlende Einträge werden nicht automatisch geschrieben. Stattdessen zeigt die
App eine technische Begründung und eine Empfehlung an. Bei `recorder:` wird
beispielsweise erklärt, dass der Recorder Zustandsverlauf, Logbook- und
Statistikdaten speichert und eine explizite Konfiguration Aufbewahrung,
Excludes und Datenbankpflege nachvollziehbar macht.

## Dashboard und Preflight

Das Qualitätsdashboard enthält eine neue Kennzahl **Grundlagen**. Fehlende
Grundlagen erscheinen als normale Dashboard-Hinweise und öffnen bei Bedarf
direkt `configuration.yaml`.

Preflight enthält zusätzlich den Check **Grundkonfiguration**. Damit sind
fehlende Basisdefinitionen schon vor Push oder Wartungslauf sichtbar.

## Technische Änderungen

- Neue read-only Analyse `fundamental_configuration_status()` in
  `configuration.py` ergänzt
- Neuer API-Endpunkt `/api/configuration/fundamentals`
- Erkennung von Fundorten in `configuration.yaml`, Root-`!include`,
  ausgelagerten `homeassistant: !include`-Dateien und Packages ergänzt
- Package-Modi `!include_dir_named` und `!include_dir_merge_named`
  berücksichtigt
- Dashboard-Findings und Preflight-Details aus derselben Analyse abgeleitet
- Tests für `recorder:` in `configuration.yaml`, Packages,
  `merge_named`-Packages, Dashboard und Preflight ergänzt
- Projekt- und Add-on-Version auf `1.10.0` angehoben
