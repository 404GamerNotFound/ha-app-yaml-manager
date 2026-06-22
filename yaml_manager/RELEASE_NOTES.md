# Release Notes 0.12.0

Veröffentlicht am 22. Juni 2026.

## Integrierte HA-Objektansicht

Automationen, Scripts und Szenen öffnen jetzt als reguläre App-Seite neben der
sichtbaren Sidebar. Die bisherige große Modalansicht wurde durch kompakte Zeilen
mit Objekt, Quelldatei, Referenzen und Beziehungszählern ersetzt. HA-Objekte und
Suchen/Ersetzen liegen als logische Werkzeuge in der Sidebar statt in der
Topbar.

## Automatischer Git-Push

Unter **Git Remote** kann Auto-Push pro Remote aktiviert werden. Nach jedem
erfolgreichen lokalen App-Commit wird der konfigurierte Remote-Branch sicher
aktualisiert. Ein neuerer oder divergierter Remote wird nicht überschrieben;
der lokale Save bleibt erfolgreich und der Sync-Fehler wird separat angezeigt.

## Git-Branch-Verwaltung

Lokale Branches können im Dashboard angezeigt, erstellt und gewechselt werden.
Vor einem Merge zeigt die App Ahead/Behind, betroffene Dateien und einen Unified
Diff. Konflikte und ungültiges YAML brechen den noch nicht eingecheckten Merge
automatisch ab.

## Multi-Datei-Suche und Ersetzen

`configuration.yaml`, Packages und erkannte HA-Includes können gemeinsam
durchsucht und nach einer Vorschau geändert werden. Zustandshash, YAML- und
Konfliktprüfung, Backups, Rollback und ein gemeinsamer Git-Commit schützen den
Vorgang.

## Automationen, Scripts und Szenen

Der neue HA-Objektbrowser folgt den entsprechenden Bereichen aus
`configuration.yaml`, `!include`, Include-Verzeichnissen und Packages. Objekte
und Referenzen sind durchsuchbar und öffnen direkt den passenden Editor. Für
`automations.yaml`, `scripts.yaml`, `scenes.yaml` und weitere eingebundene
Dateien steht ein geschützter YAML-Ressourceneditor bereit.

## Script-Abhängigkeiten

Der neue Tab **Bezüge** zeigt Definitionen, verwendete Scripts, Szenen und
Entitäten sowie eingehende Verweise aus anderen Package-Dateien. Fundstellen und
bekannte Definitionen lassen sich direkt im Editor öffnen.

## Referenzsichere Script-ID-Umbenennung

Script-IDs können nach einer Vorschau zusammen mit allen erkannten Referenzen
umbenannt werden. Die Anwendung ist durch einen globalen Package-Zustandshash,
YAML- und Konfliktprüfung, Backups, Rollback und einen gemeinsamen Git-Commit
geschützt.

## Modularisiertes Backend

HTTP, `configuration.yaml`, Git, Backups, YAML-Validierung und
Abhängigkeitsanalyse liegen jetzt in eigenen Python-Modulen. `app.py` bleibt als
kompatible Service-Fassade bestehen; bestehende API-Verträge bleiben erhalten.

## Dashboard in der linken Navigation

Das Dashboard ist jetzt der erste Eintrag links oben. Es belegt ausschließlich
den Inhaltsbereich rechts neben der Sidebar. Kategorien, Tags und sämtliche
Script-Dateien bleiben dadurch auch auf der Qualitätsübersicht sichtbar.

## Direkter Zugriff auf Scripts

Ein Klick auf eine Datei in der linken Spalte öffnet unmittelbar den YAML-Editor.
Der Dashboard-Eintrag führt zurück zur Übersicht, ohne einen geöffneten
Editorstand zu verwerfen. Auf mobilen Geräten bleibt die Scriptliste über die
vorhandene Seitenleisten-Schaltfläche erreichbar.

## Bestehende Funktionen

Qualitätsprüfung, Git-Divergenzauflösung, Git-Historie sowie ZIP-Import und
-Export bleiben vollständig verfügbar.

## Technische API-Erweiterungen

- `GET /api/git/branches`
- `POST /api/git/branches/create|switch|compare|merge`
- `POST /api/search-replace/preview|apply`
- `GET /api/ha-objects`
- `GET|PUT /api/resource`
- `GET /api/dependencies`
- `POST /api/script/rename-preview`
- `POST /api/script/rename`

## Nach dem Update

1. Öffne eine Package-Datei und wähle rechts **Bezüge**.
2. Nutze **Öffnen** oder **Definition**, um zwischen Fundstellen zu wechseln.
3. Nutze **Umbenennen**, prüfe die Vorschau und bestätige die Änderungen.
