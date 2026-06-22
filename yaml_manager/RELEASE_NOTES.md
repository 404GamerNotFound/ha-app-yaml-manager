# Release Notes 0.10.0

Veröffentlicht am 22. Juni 2026.

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

- `GET /api/dependencies`
- `POST /api/script/rename-preview`
- `POST /api/script/rename`

## Nach dem Update

1. Öffne eine Package-Datei und wähle rechts **Bezüge**.
2. Nutze **Öffnen** oder **Definition**, um zwischen Fundstellen zu wechseln.
3. Nutze **Umbenennen**, prüfe die Vorschau und bestätige die Änderungen.
