# Release Notes 1.7.0

Veröffentlicht am 27. Juni 2026.

## Streamlined UI

Die Oberfläche wurde auf eine zentrale, logisch gruppierte Sidebar-Navigation
umgestellt. Werkzeuge sind jetzt in die Bereiche **Übersicht**,
**Dateien bearbeiten**, **Prüfen und Debuggen**, **Struktur und Daten** sowie
**Verwaltung** einsortiert. Die bisherige Werkzeugauswahl in der Topbar wurde
entfernt, damit die Kopfzeile nur noch die wichtigsten Dateiaktionen enthält.

## Package-Dateien

Package-Dateien werden nicht mehr dauerhaft als lange Liste in der Sidebar
angezeigt. Stattdessen gibt es den neuen Navigationseintrag
**Package-Dateien**, der eine eigene Dateiansicht öffnet. Diese Seite bündelt:

- Suche nach Dateinamen,
- Kategorie-Filter,
- Tag-Filter,
- kompakte Kennzahlen,
- scrollbare Dateiliste,
- direkten Wechsel in den Editor.

Damit bleiben auch viele Package-Dateien auffindbar, ohne die Hauptnavigation zu
überladen.

## Seiten statt Dialoge

Die Package-Dateiansicht ist als reguläre Inhaltsseite umgesetzt und verhält
sich damit wie Dashboard, Review, Git, Backups und die übrigen Werkzeugseiten.
Beim Öffnen oder Erstellen einer Package-Datei wechselt die App direkt zurück in
den Editor.

## Technische Änderungen

- Sidebar-Navigation in `index.html` neu gruppiert
- Topbar-Werkzeugmenü entfernt und Dateiaktionen konsolidiert
- Package-Dateibrowser von einem Dialog in eine echte Seite umgebaut
- Seitenzustände, aktive Navigation und Sidebar-Zusammenfassung in `app.js`
  erweitert
- Responsive Darstellung und Dateibrowser-Layout in `app.css` angepasst
- Projekt- und Add-on-Version auf `1.7.0` angehoben
