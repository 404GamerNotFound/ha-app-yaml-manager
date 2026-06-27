# Release Notes 1.5.0

Veröffentlicht am 27. Juni 2026.

## Datenbankanalyse

Die neue Seite **Datenbank** analysiert die Home-Assistant-Recorder-Datenbank
`home-assistant_v2.db` direkt aus dem Konfigurationsverzeichnis. Die Analyse ist
rein lesend und funktioniert auch dann sauber, wenn lokal keine Recorder-
Datenbank vorhanden ist.

Die Recorder-Übersicht zeigt:

- Datenbank- und WAL-Größe,
- Tabellen und Zeilenanzahlen,
- größte Tabellen, sofern `dbstat` verfügbar ist,
- ältesten und neuesten State-Zeitpunkt,
- Ergebnis von `PRAGMA quick_check`.

## Entity- und YAML-Abgleich

Die Entity-Analyse findet laute Entities nach State-Änderungen, Entities mit
großem Attributvolumen sowie Entities, deren letzter oder kompletter Verlauf auf
`unknown` beziehungsweise `unavailable` hindeutet.

Zusätzlich gleicht die App verwaltete YAML-Entity-Referenzen mit der
Recorder-Historie ab. Dadurch werden Entities sichtbar, die zwar in YAML
referenziert werden, aber nie in der Datenbank auftauchen, sowie Datenbank-
Entities ohne verwaltete YAML-Referenz.

## Statistikprüfung

Langzeit- und Kurzzeitstatistiken werden auf typische Auffälligkeiten geprüft:

- Lücken in `statistics` und `statistics_short_term`,
- große Sprung-Kandidaten,
- geänderte Einheiten in `statistics_meta`,
- Statistik-Metadaten ohne `has_mean` und ohne `has_sum`.

## Sicherer SQL-Explorer

Der SQL-Explorer erlaubt nur einzelne `SELECT`- oder `WITH`-Abfragen. Serverseitig
werden `PRAGMA query_only=ON`, ein SQLite-Authorizer, ein kurzer Timeout sowie
Limits für Zeilen und Spalten verwendet. Schreibende Statements und mehrere
Statements werden abgelehnt.

## Technische Änderungen

- Neues Backend-Modul `database.py`
- Neue API-Endpunkte:
  - `GET /api/database`
  - `GET /api/database/health`
  - `GET /api/database/entities`
  - `GET /api/database/statistics`
  - `GET /api/database/yaml-compare`
  - `POST /api/database/query`
- Neue Sidebar-Seite **Datenbank**
- Projekt- und Add-on-Version auf `1.5.0` angehoben
- Tests für Recorder-Health, Entity-Analyse, Statistikhinweise, YAML-Abgleich und SQL-Schutz ergänzt
