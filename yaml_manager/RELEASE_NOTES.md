# Release Notes 0.6.0

Veröffentlicht am 22. Juni 2026.

## Automatische Git-Commits

Die App initialisiert bei Bedarf ein lokales Git-Repository im Home-Assistant-
Konfigurationsverzeichnis. Erstellen, Speichern, Umbenennen, Löschen, Migrationen
und Wiederherstellungen erzeugen automatisch beschriftete Commits. Vorhandene,
noch nicht eingecheckte Stände einer betroffenen Datei werden zuvor als eigener
Zwischenstand bewahrt.

App-Commits enthalten ausschließlich die tatsächlich bearbeiteten Pfade. Bereits
vom Nutzer vorgemerkte Änderungen an anderen Dateien bleiben unangetastet.

## Git-Historie und Diff

Im `configuration.yaml`-Editor steht die neue Aktion **Git-Historie** bereit.
Package-Dateien erhalten dafür eine **G**-Schaltfläche. Die Ansicht zeigt bis zu
100 Commits mit Zeitpunkt, Kurz-ID, Autor und Commit-Nachricht. Nach Auswahl eines
Commits erscheint ein Unified Diff zur aktuellen Fassung.

## Frühere Stände wiederherstellen

Ein ausgewählter Commit kann direkt wiederhergestellt werden. Die App prüft
vorher den aktuellen SHA-256-Dateistand und die YAML-Gültigkeit der Git-Version.
Zusätzlich wird die aktuelle Datei im bisherigen Backup-System gesichert. Der
wiederhergestellte Stand wird als neuer Commit angelegt; bestehende Git-Historie
wird nicht verändert. Danach läuft weiterhin die Home-Assistant-
Konfigurationsprüfung.

## Technische API-Erweiterungen

- `GET /api/git/history` liefert die dateibezogenen Commits.
- `GET /api/git/diff` vergleicht einen Commit mit der aktuellen Fassung.
- `POST /api/git/restore` stellt einen Stand konfliktgeschützt wieder her.

## Nach dem Update

1. Öffne eine Package-Datei und speichere eine kleine Änderung.
2. Öffne über **G** die neue Git-Historie und prüfe den Commit-Diff.
3. Die bisherige Backup-Historie bleibt parallel über **Versionen** verfügbar.
