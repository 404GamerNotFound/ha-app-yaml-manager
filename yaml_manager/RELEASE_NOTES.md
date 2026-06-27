# Release Notes 1.6.0

Veröffentlicht am 27. Juni 2026.

## Backup-Center

Die neue Seite **Backups** bündelt lokale Datei-Backups, vollständige
Konfigurations-Snapshots, Recorder-Datenbank-Backups und die
Integritätsprüfung. Backups können gepinnt werden, damit sie von automatischer
Bereinigung ausgenommen bleiben.

## Manifeste und Integrität

Neue Datei-Backups erhalten ein `manifest.json` mit Quelle, Erstellzeitpunkt,
Größe, SHA-256, Git-Commit, letztem Home-Assistant-Check und Restore-Status.
Ältere Backups ohne Manifest bleiben lesbar und werden in der Integritätsprüfung
als Hinweis markiert.

Die Integritätsprüfung erkennt:

- fehlende Manifeste oder Dateien,
- Hash- und Größenabweichungen,
- ungültige YAML-Sicherungen,
- defekte Snapshot-ZIP-Archive,
- überschrittene Backup-Größenlimits,
- Backups außerhalb der Aufbewahrung.

## Konfigurations-Snapshots

Snapshots werden als ZIP in `/data/backups/<id>/snapshot.zip` abgelegt und
enthalten `configuration.yaml`, verwaltete Packages und Blueprints. `secrets.yaml`
wird optional nur maskiert als `secrets.masked.yaml` aufgenommen und nicht
zurückgeschrieben.

Ein Snapshot-Restore ist nur nach einer Vorschau möglich. Die Vorschau prüft
YAML, Package-Konflikte und bindet den Zielzustand über einen Hash. Beim
Wiederherstellen werden bestehende Ziel-Dateien zuerst gesichert, dann atomar
geschrieben, per Git versioniert und anschließend durch den Home-Assistant-Check
geführt.

## Recorder-Datenbank-Backups

Die Recorder-Datenbank `home-assistant_v2.db` wird nicht roh kopiert. Stattdessen
erstellt HA Maintenance Hub über `sqlite3.Connection.backup()` einen konsistenten
SQLite-Snapshot unter `/data/db-backups`.

## Aufbewahrung

Die Einstellungen wurden erweitert:

- Anzahl der Backup-Stände,
- Backup-Aufbewahrung nach Tagen,
- maximales Backup-Volumen in MiB,
- Pinning einzelner Backups.

## Technische Änderungen

- Neue API-Endpunkte:
  - `GET /api/backups/overview`
  - `GET /api/backups/integrity`
  - `POST /api/backups/pin`
  - `POST /api/backups/snapshot`
  - `POST /api/backups/snapshot/restore-preview`
  - `POST /api/backups/snapshot/restore`
  - `POST /api/backups/database`
- Backup-Integrität ist Teil von Preflight
- Systemstatus berücksichtigt `/data/db-backups`
- Projekt- und Add-on-Version auf `1.6.0` angehoben
- Tests für Manifeste, Pinning, Retention, Snapshots, Restore-Preview und SQLite-Backup ergänzt
