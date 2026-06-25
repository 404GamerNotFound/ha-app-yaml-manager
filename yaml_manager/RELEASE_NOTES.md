# Release Notes 1.2.0

Veröffentlicht am 25. Juni 2026.

## Interaktive Dokumentation

Die Seite **Doku** zeigt die generierte Dokumentation jetzt zusätzlich als
interne HTML-Ansicht. Tabs trennen Übersicht, Objektgraph, Entitäten,
Änderungen und Markdown. Der Filter durchsucht die strukturierten Daten direkt
im Browser.

Der Backend-Generator liefert dafür neben der Markdown-Datei ein `data`-Objekt
mit Package-Dateien, HA-Objekten, Referenzen, Graph-Kanten, Entity-Nutzung,
Konflikten und letzten Git-Commits.

## Sicherheit und Git-Push-Warnung

Die neue Seite **Sicherheit** scannt alle verwalteten YAML-Dateien auf
`!secret`-Referenzen, fehlende Einträge in `secrets.yaml`, mögliche Klartext-
Tokens in URL-Parametern oder typischen Secret-Feldern und wahrscheinlich
ungenutzte Secrets.

Vor Git-Push, sicherer Synchronisation, Merge-Push und Force-Push ruft das
Frontend dieselbe Prüfung über `/api/security/push-warning` auf. Kritische
Hinweise müssen bewusst bestätigt werden, bevor die Remote-Aktion startet.
Automatische Pushes nach Speichervorgängen werden bei riskanten Funden
serverseitig blockiert und als `gitSync`-Status gemeldet.

## Jinja-Template-Tester

Der rechte Hilfebereich enthält den neuen Tab **Templates**. Dort kann ein
Jinja-Template gegen Home Assistants `/api/template` gerendert werden. Die App
zeigt das Ergebnis oder die Fehlermeldung und extrahiert verwendete Entitäten
aus `states(...)`, `is_state(...)`, `state_attr(...)` und `states.domain.name`.

Ohne Supervisor-Token bleibt der Tester sichtbar, meldet aber die nicht
verfügbare Home-Assistant-API.

## Trace-/Debug-Ansicht

Die neue Seite **Traces** sammelt die letzten Ausführungen erkannter Automationen
und Scripts über Home Assistants Trace-API. Die Liste zeigt Objekt, Entity-ID,
Zeitpunkt, Status, letzten Schritt und Fehler. Ein Klick lädt die Detaildaten
einer Ausführung als JSON, damit Variablen, Trigger und Schritte gezielt
untersucht werden können.

## Dashboard-Aktionen

Dashboard-Hinweise enthalten nun direkte Aktionen. Je nach Hinweis öffnet die App
die Konfliktübersicht, die Blueprint-Seite, die Sicherheitsprüfung, die
Trace-Ansicht oder springt in die betroffene YAML-Datei und Zeile. Dadurch wird
das Dashboard stärker zu einem Arbeitsbereich statt nur zu einer Übersicht.

## Technische Änderungen

- Neue Backend-Module `security.py` und `traces.py`
- `documentation.py` liefert strukturierte Daten für HTML-Doku, Objektgraph,
  Entity-Liste und Änderungsverlauf
- Neue API-Endpunkte für Security, Push-Warnung, Trace-Index, Trace-Detail und
  Template-Rendering
- Dashboard-Antworten enthalten Security- und Trace-Summaries sowie optionale
  Aktions-Metadaten pro Finding
- Frontend-Seiten für Sicherheit und Traces sowie Doku-Tabs, Template-Tester und
  Dashboard-Aktionsbuttons ergänzt
- Unit-Tests für Security-Scan, Template-Rendering, Trace-API und strukturierte
  Dokumentationsdaten ergänzt

## Neue API-Endpunkte

- `GET /api/security`
- `GET /api/security/push-warning`
- `GET /api/traces`
- `GET /api/trace`
- `POST /api/template/render`
