# YAML Script Manager

## Verwendung

Die App zeigt alle `.yaml`- und `.yml`-Dateien unter `/config/packages` rekursiv
an. Wähle links eine Datei aus, bearbeite sie und speichere mit der Schaltfläche
**Speichern** oder mit `Strg+S` beziehungsweise `Cmd+S`.

Oberhalb der Kategorien zeigt die App, ob der Paketordner in
`configuration.yaml` eingebunden ist. Bei einer fehlenden Einbindung wird dieser
Eintrag erwartet:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Die Prüfung unterstützt außerdem `!include_dir_merge_named` und eine über
`homeassistant: !include ...` ausgelagerte Konfiguration. Sie ist rein lesend;
die App verändert `configuration.yaml` nicht.

Die YAML-Prüfung läuft während der Eingabe. Ein Klick auf eine Fehlermeldung in
der Statusleiste springt zur betroffenen Zeile. Die Prüfung kontrolliert die
YAML-Syntax und doppelte Schlüssel, jedoch nicht die vollständige semantische
Home-Assistant-Konfiguration.

Nach dem Speichern können die Skripte über **Skripte neu laden** in Home Assistant
aktiviert werden. Diese Aktion ruft den Dienst `script.reload` auf.

## Kategorien

Die Kategorie einer geöffneten Datei wird oberhalb des Editors ausgewählt. Über
**+ Neue Kategorie** kann ein neuer Name angelegt werden. Kategorien sind reine
Metadaten der App und werden nicht in die YAML-Dateien geschrieben.

## Tags

Tags werden oberhalb des Editors als kommagetrennte Liste gepflegt. In der linken
Spalte können Dateien anschließend nach einem Tag gefiltert werden. Die Suche
berücksichtigt Dateipfad, Kategorie und Tags. Pro Datei werden bis zu zwölf Tags
gespeichert.

## Script-Prüfung

Der Tab **Prüfung** wird während der Eingabe aktualisiert und zeigt einen
Qualitätswert sowie priorisierte Hinweise. Geprüft werden unter anderem:

- doppelte YAML-Schlüssel wie zwei `template:`-Blöcke im selben Bereich,
- gleiche Script-IDs in anderen Package-Dateien,
- mehrfach verwendete `entity_id`-Werte,
- unausgeglichene Jinja-Klammern,
- fehlende oder leere `sequence:`-Blöcke,
- fehlende Aliase und Script-Modi,
- Script-IDs mit ungeeigneten Zeichen.

Mehrfach verwendete Entitäten können beabsichtigt sein und werden deshalb als
Warnung statt als Fehler angezeigt. Hinweise mit einer Zeilennummer springen
beim Anklicken direkt an die betroffene Stelle.

## Dateien organisieren

Über das Stiftsymbol kann die geöffnete Datei umbenannt oder in einen Unterordner
von `packages` verschoben werden. Ungespeicherte Änderungen müssen vorher
gespeichert werden. Versionsprüfung, Pfadschutz und Sicherungskopie gelten auch
für diese Aktion.

## Hilfsfunktionen

- **Bausteine** fügt häufige Script-Strukturen an der Cursorposition ein.
- **Entitäten** durchsucht die aktuellen Home-Assistant-Zustände und fügt eine
  `entity_id` ein.
- **Dienste** durchsucht verfügbare Aktionen und fügt einen Aktionsblock ein.

## Datensicherheit

- Vor jedem Speichern wird eine Sicherung unter `/data/backups` erzeugt. Die App
  behält die letzten 30 Sicherungsstände.
- Gelöschte Dateien werden unter `/data/trash` abgelegt und nicht endgültig
  entfernt.
- Erkennt die App eine externe Änderung nach dem Öffnen, wird das Speichern mit
  einem Konflikthinweis abgebrochen.
- Es werden nur UTF-8-Dateien bis 2 MiB akzeptiert.
- Pfade außerhalb von `/config/packages` und versteckte Pfadbestandteile sind
  gesperrt.

Die Verzeichnisse `/data/backups` und `/data/trash` liegen im persistenten
Datenspeicher der App und sind Bestandteil eines Home-Assistant-Backups.

## Technischer Aufbau

Der Container stellt auf Port `8099` einen `ThreadingHTTPServer` bereit. Ingress
übernimmt Authentifizierung und Weiterleitung. Der Zugriff auf Entitäten, Dienste
und `script.reload` erfolgt über `http://supervisor/core/api` mit dem von Home
Assistant bereitgestellten `SUPERVISOR_TOKEN`.

Die Home-Assistant-Konfiguration wird als `homeassistant_config` mit Schreibzugriff
nach `/homeassistant` gemountet. Die App selbst verwendet ausschließlich
`/homeassistant/packages`.
