# Release Notes 0.7.0

Veröffentlicht am 22. Juni 2026.

## GitHub- und GitLab-Synchronisation

Im neuen Qualitätsdashboard kann ein HTTPS-Remote auf GitHub.com oder GitLab.com
hinterlegt werden. Fetch, Fast-forward-Pull, Push und sichere Synchronisation
werden ausschließlich manuell gestartet. Divergierte Historien, Force-Pushes und
Remote-Änderungen außerhalb von `configuration.yaml` und `packages/` werden
nicht automatisch übernommen.

Personal Access Tokens werden mit Dateimodus `0600` im persistenten App-Datenordner
gespeichert. Sie erscheinen weder in der Git-Remote-URL noch in API-Antworten oder
Prozessargumenten.

## Qualitätsdashboard

Das Dashboard bündelt Package-Konflikte, Warnungen, Script-Anzahl, mögliche
ungenutzte Scripts, Backups und Git-Status in einer Übersicht. Der Qualitätswert
macht sichtbar, wo zuerst nachgebessert werden sollte. Die Script-Nutzungsanalyse
bleibt bewusst eine Warnung, da externe Aufrufe nicht vollständig erkennbar sind.

## ZIP-Import und -Export

Einzelne Package-Dateien, Kategorien oder alle Packages lassen sich samt Tags und
Kategorien exportieren. Vor einem Import prüft die App ZIP-Pfade, Größenlimits,
UTF-8, YAML, vorhandene Dateien und globale Package-Konflikte.

Der bestätigte Import läuft transaktional und unterstützt Überspringen oder
Überschreiben. Backups, Git-Commit, Rollback bei Schreibfehlern und die
Home-Assistant-Prüfung bleiben Bestandteil des Ablaufs.

## Technische API-Erweiterungen

- `GET /api/dashboard` liefert Qualitäts- und Git-Status.
- `GET|PUT|DELETE /api/git/remote` verwaltet den geschützten Remote.
- `POST /api/git/remote/sync` führt die gewählte Synchronisationsaktion aus.
- `GET /api/export` erzeugt Package-ZIP-Archive.
- `POST /api/import/preview` und `/api/import/apply` prüfen und importieren Archive.

## Nach dem Update

1. Öffne **Dashboard** und prüfe Qualitätswert und Hinweise.
2. Hinterlege bei Bedarf einen privaten GitHub-/GitLab-Remote mit minimal berechtigtem Token.
3. Teste unter **Import/Export** zunächst einen ZIP-Export und anschließend die Importvorschau.
