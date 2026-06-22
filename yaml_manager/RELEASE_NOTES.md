# Release Notes 0.8.0

Veröffentlicht am 22. Juni 2026.

## Dashboard als Startseite

Die App startet nun im Qualitätsdashboard. Von dort führt **Scripts öffnen** in
den vollständigen Script-Manager. Über **Dashboard** kann jederzeit zur Übersicht
zurückgekehrt werden, ohne den aktuellen Editorstand zu verlieren.

## Divergierte Git-Historien auflösen

Der häufige Fall eines neuen GitHub-/GitLab-Repositories mit eigenem README-
Commit führt nicht mehr in eine Sackgasse. Das Dashboard bietet zwei Optionen:

- **Historien verbinden** übernimmt README-/Lizenzdateien, erzeugt einen sicheren
  Merge und pusht den gemeinsamen Stand. Dies ist die empfohlene Lösung.
- **Remote durch lokalen Stand ersetzen** verwirft die bisherige Remote-Historie
  mit einem gegen parallele Änderungen geschützten `force-with-lease`.

Vor einem Merge werden Remote-Pfade, Dateitypen, Größen und YAML geprüft sowie
lokale Dateien gesichert. Bei einem Merge-Konflikt wird der Vorgang automatisch
abgebrochen und der Ausgangsstand wiederhergestellt.

## Bestehende Funktionen

Qualitätsprüfung, Git-Remote-Verwaltung, Git-Historie sowie ZIP-Import und -Export
bleiben vollständig im Dashboard beziehungsweise in den Editoren verfügbar.

## Technische API-Erweiterungen

- `POST /api/git/remote/sync` akzeptiert zusätzlich `merge` und `force-push`.
- Konfliktantworten enthalten `ahead`, `behind` und verfügbare Auflösungsoptionen.

## Nach dem Update

1. Die App öffnet automatisch das Dashboard.
2. Wähle bei einem neuen Remote mit README **Historien verbinden**.
3. Verwende **Remote durch lokalen Stand ersetzen** nur, wenn die Remote-Historie sicher verworfen werden darf.
