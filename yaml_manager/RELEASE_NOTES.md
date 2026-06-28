# Release Notes 1.9.0

Veröffentlicht am 28. Juni 2026.

## Datenbankanalyse

Die Datenbankseite ist jetzt in klare Arbeitsbereiche aufgeteilt:

- **Analyse** mit schnellem DB Check
- **Tabellen** mit Suche, Sortierung und Tabellenaktionen
- **Problemstellen** für Entities, YAML-/DB-Abgleich und Statistiken
- **Empfehlungen** aus den Analyseergebnissen
- **SQL** für bestehende read-only Abfragen

Der neue DB Check nutzt den vorhandenen Health-Endpunkt separat und zeigt
`quick_check`, Dateipfad, Recorder-Zeitraum, WAL-Größe und größte Tabellen als
kompakte Checkliste.

## Cache und Aktualisieren

Dashboard, Graph und Entity-Health werden im Browser gecacht. Beim Wechseln
zwischen Seiten werden frische Ergebnisse wiederverwendet, statt jedes Mal neu
geladen zu werden.

Wenn sich Package-Dateien oder die Package-Einbindung ändern, markiert die App
diese Bereiche als veraltet. Die Status-Badges neben **Aktualisieren** zeigen,
ob die Ansicht frisch, veraltet oder noch nicht geladen ist.

## Sidebar

Der Navigationsbereich in der linken Sidebar scrollt wieder intern. Der
Systemstatus bleibt dabei unten angedockt und kann im geöffneten Zustand selbst
scrollen.

## Technische Änderungen

- Datenbankseite in View-Panels mit `data-database-view` und Tab-State umgebaut
- Tabellenliste um Client-Filter, Sortierung und SELECT-/COUNT-Aktionsbuttons
  erweitert
- JSON-Export für die aktuelle Datenbankanalyse ergänzt
- Cache-State mit `loadedAt`, `stale` und Stale-Grund für Dashboard, Graph und
  Entity-Health eingeführt
- Dateisignatur aus Package-Pfad, Größe, Änderungszeit, Kategorie, Tags und
  Package-Konfigurationsstatus ergänzt
- Sidebar-Layout auf Flex-Column mit scrollendem Mittelbereich umgestellt
- Projekt- und Add-on-Version auf `1.9.0` angehoben
