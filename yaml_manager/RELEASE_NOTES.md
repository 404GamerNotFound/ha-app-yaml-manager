# Release Notes 1.4.0

Veröffentlicht am 26. Juni 2026.

## Entity-Refactoring

Die neue Seite **Refactor** ändert Entity-IDs über alle verwalteten YAML-Dateien
hinweg. Die Vorschau zeigt Treffer, Dateien und Zeilen. Die Anwendung ist
entity-exakt, damit `light.alt` nicht versehentlich `light.alt_extra` verändert.

Beim Anwenden laufen die bestehenden Schutzmechanismen: Zustandshash,
YAML-Prüfung, Package-Konfliktprüfung, Backups, atomarer Austausch, Git-Commit,
Auto-Push-Schutz und Home-Assistant-Konfigurationsprüfung.

## Secrets-Manager

Die neue Seite **Secrets** verwaltet `/config/secrets.yaml` maskiert. Secret-
Werte werden nie in API-Antworten zurückgegeben. Unterstützt werden:

- Secret anlegen oder aktualisieren,
- Secret löschen,
- Referenzanzahl anzeigen,
- Klartext-Zeile in `!secret <name>` umwandeln und den Wert gleichzeitig in
  `secrets.yaml` schreiben.

Auch diese Änderungen erzeugen Backups und Git-Commits. Die bestehende
Security-Prüfung bleibt die Quelle für fehlende und ungenutzte Secret-Hinweise.

## Preflight

Die neue Seite **Preflight** bündelt alle Prüfungen vor dem Push:

- YAML-Syntax,
- Package-Konflikte,
- Security und Secrets,
- Entity-Health,
- Home-Assistant-Konfigurationscheck,
- Dokumentationsstatus,
- Git-Remote-Status.

Die Antwort unterscheidet Blocker und Warnungen. Damit gibt es einen klaren
„bereit zum Push“-Status, ohne die einzelnen Detailseiten öffnen zu müssen.

## Technische Änderungen

- Neue Backend-Module `entity_refactor.py`, `secrets_manager.py` und `preflight.py`
- Neue API-Endpunkte für Entity-Refactor, Secrets und Preflight
- Neue Sidebar-Seiten **Refactor**, **Secrets** und **Preflight**
- Secret-Werte werden serverseitig maskiert und nicht serialisiert
- Tests für Entity-Refactor, Secrets-Umwandlung und Preflight ergänzt

## Neue API-Endpunkte

- `POST /api/entity-refactor/preview`
- `POST /api/entity-refactor/apply`
- `GET /api/secrets`
- `POST /api/secrets`
- `DELETE /api/secrets`
- `POST /api/secrets/convert`
- `GET /api/preflight`
