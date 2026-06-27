# Release Notes 1.8.0

Veröffentlicht am 27. Juni 2026.

## Navigation und Verlauf

Der Editor ist jetzt ein eigener Navigationseintrag in der linken Sidebar. Damit
ist der Rückweg aus Werkzeugseiten eindeutig: Seitenaktionen führen zurück zum
Editor, während **Package-Dateien** gezielt die Dateiansicht öffnet.

Die App unterstützt außerdem URL-Hashes für Hauptseiten. Beispiele:

- `#dashboard`
- `#editor`
- `#files`
- `#backups`
- `#search-replace`
- `#configuration`

Browser-Zurück und Browser-Vorwärts wechseln damit zwischen App-Seiten, ohne
Funktionen oder Daten zu verlieren.

## Package-Dateien

Die Package-Dateiansicht wurde für größere Dateibestände erweitert:

- Favoriten lokal im Browser markieren,
- zuletzt geöffnete Dateien anzeigen,
- nach Name, Pfad, Änderung oder Kategorie sortieren,
- nach Ordnern gruppieren,
- aktuelle Filter speichern und wieder anwenden,
- große Trefferlisten gestaffelt rendern.

Die Datei-Metadaten bleiben unverändert; Favoriten, zuletzt geöffnete Dateien
und gespeicherte Filter werden nur lokal im Browser gespeichert.

## Seiten statt Dialoge

Weitere größere Arbeitsbereiche sind jetzt echte Inhaltsseiten:

- Versionsverlauf
- Git-Historie
- Ressourcen-Editor
- Package-Konfliktübersicht

Kurze Aktionen wie **Neue Datei** und die Impact-Bestätigung bleiben bewusst als
Dialoge bestehen.

## Responsive Feinschliff

Für kleinere Displays wurden Page-Header, Navigationszeilen, Seitenabstände und
Diff-Ansichten verdichtet. Tabellen, Karten und Werkzeugbereiche stapeln sich
stabiler und lassen mehr Platz für den eigentlichen Inhalt.

## Technische Änderungen

- `Editor` als eigener Sidebar-Navigationszustand ergänzt
- Hash-Router in `app.js` eingeführt
- Package-Dateiliste um lokale Favoriten, Recents, gespeicherte Filter,
  Sortierung, Ordnergruppen und gestaffeltes Rendering erweitert
- History-, Git-History-, Resource- und Conflict-Flächen in den gemeinsamen
  Page-Stack aufgenommen
- Responsive CSS-Regeln für Page-Header, Dateiliste, Diffs und Sidebar
  nachgezogen
- Projekt- und Add-on-Version auf `1.8.0` angehoben
