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
Änderungen erfolgen ausschließlich über den separaten Konfigurationseditor.

## configuration.yaml-Editor

Die Schaltfläche **configuration.yaml** öffnet einen eigenen Editor mit
Syntaxhervorhebung, Zeilennummern, Live-YAML-Prüfung und Konfliktschutz.
`Strg+S` beziehungsweise `Cmd+S` speichert die Datei. Vor dem Schreiben wird die
vorherige Fassung im persistenten Backup-Verzeichnis der App gesichert.

### Packages einbinden

**Packages einbinden** ergänzt bei einer normalen Konfiguration diesen Block:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Existiert `homeassistant:` bereits, bleiben seine Optionen erhalten. Verweist
`homeassistant: !include homeassistant.yaml` auf eine separate Datei, wird die
`packages:`-Zeile dort ergänzt. Eine vorhandene abweichende `packages:`-
Definition wird niemals automatisch überschrieben.

### Konfiguration in ein Package auslagern

**Alles in Package auslagern** analysiert zunächst die aktuelle Editorfassung
und zeigt die betroffenen Top-Level-Bereiche. Nach Bestätigung werden diese
standardmäßig nach `/config/packages/configuration_import.yaml` verschoben.

Dabei gelten folgende Schutzregeln:

- `homeassistant:` bleibt vollständig in `configuration.yaml`.
- Damit bleiben insbesondere `auth_providers` und andere früh verarbeitete
  Core-Optionen an ihrem erforderlichen Ort.
- Relative `!include`-Pfade erhalten für den neuen Package-Standort automatisch
  ein passendes `../`-Präfix.
- Eine vorhandene gleichnamige Package-Datei wird nicht überschrieben.
- Hauptdatei und Package werden vorbereitet, validiert, gesichert und atomar
  ausgetauscht; bei einem Schreibfehler wird zurückgerollt.
- `!include_dir_named` und `!include_dir_merge_named` werden mit ihrer jeweils
  erforderlichen Package-Struktur unterstützt.

Die Prüfung der App kontrolliert YAML-Syntax und Dateikonsistenz. Nach Speichern,
Package-Einbindung und Migration startet sie automatisch zusätzlich Home
Assistants semantische Konfigurationsprüfung.

## Home-Assistant-Konfigurationsprüfung

Auch das Erstellen, Speichern und Wiederherstellen einer Package-Datei löst die
Prüfung aus; das Ergebnis erscheint in der Statusleiste des Script-Editors. Die
Schaltfläche **Home Assistant prüfen** ruft die Prüfung außerdem ohne vorherige
Änderung manuell auf. Serverseitig wird dafür über den Supervisor-Token ein
`POST` an `/api/config/core/check_config` gesendet. Das Ergebnis steht direkt
oberhalb des Editors. Bei einer ungültigen Konfiguration bleibt die Datei zwar
gespeichert, die Meldung wird aber deutlich als Fehler dargestellt. Soweit Home
Assistant eine Zeile nennt, springt ein Klick auf die Meldung dorthin.

Ist die Supervisor-API in der lokalen Entwicklung nicht verfügbar, kennzeichnet
die App die Prüfung als nicht verfügbar, ohne den erfolgreichen Dateivorgang
rückgängig zu machen.

## Versionsverlauf und Wiederherstellung

**Versionen** im Konfigurationseditor beziehungsweise das Verlaufssymbol im
Package-Editor öffnen alle für die aktuelle Datei vorhandenen Sicherungen. Die
Ansicht enthält Zeitpunkt, Dateigröße, Additionen, Löschungen und einen Unified
Diff zur aktuellen Fassung.

Beim Wiederherstellen gelten dieselben Schutzregeln wie beim Speichern:

- Die aktuelle Datei muss noch dem beim Öffnen ermittelten SHA-256-Stand entsprechen.
- Das Backup muss eine gültige UTF-8-YAML-Datei sein.
- Die aktuelle Fassung wird vor dem Austausch erneut gesichert.
- Der Schreibvorgang erfolgt atomar.
- Nach Wiederherstellung von `configuration.yaml` läuft die Home-Assistant-Prüfung erneut.

## Git-Versionierung

Die Schaltfläche **Git-Historie** im Konfigurationseditor und das **G** im
Package-Editor öffnen die Commit-Historie der jeweiligen Datei. Die App
initialisiert dafür bei Bedarf ein Repository direkt im gemounteten
Home-Assistant-Konfigurationsverzeichnis `/config` beziehungsweise intern
`/homeassistant`. Git-Objekte bleiben dadurch gemeinsam mit der Konfiguration
persistiert.

Vor einem Schreibvorgang übernimmt die App einen noch nicht eingecheckten Stand
der betroffenen Datei als Zwischenstand. Nach erfolgreicher Änderung entsteht
ein weiterer Commit mit einer beschreibenden Nachricht. Das gilt für:

- Erstellen und Speichern von Package-Dateien,
- Umbenennen, Verschieben und Löschen,
- Änderungen an `configuration.yaml` und eingebundenen Core-Dateien,
- Package-Einbindung und Konfigurationsmigration,
- Wiederherstellung aus Datei-Backups oder Git.

Git-Commits werden mit `YAML Script Manager <yaml-script-manager@local>` erstellt.
Jeder Commit ist explizit auf die von der App bearbeiteten Pfade begrenzt. Bereits
vom Nutzer vorgemerkte Änderungen an anderen Dateien bleiben im Index und werden
nicht Teil des App-Commits. Auch durch `.gitignore` ausgeschlossene, verwaltete
Package-Dateien werden gezielt versioniert.

Die Git-Ansicht zeigt bis zu 100 Commits mit Kurz-ID, Zeitpunkt, Autor und
Nachricht. Der Diff vergleicht den gewählten Commit mit der aktuellen Datei. Vor
einem Zurücksetzen prüft die App erneut den SHA-256-Stand des Editors und die
YAML-Gültigkeit der alten Version. Zusätzlich wird die aktuelle Fassung unter
`/data/backups` gesichert und der wiederhergestellte Stand als neuer Commit
festgehalten. Die Historie wird also nicht destruktiv umgeschrieben.

Die zugehörigen HTTP-Endpunkte sind:

- `GET /api/git/history`
- `GET /api/git/diff`
- `POST /api/git/restore`

## Globale Package-Konfliktprüfung

Der Eintrag **Package-Konflikte** in der Seitenleiste analysiert alle Dateien
unter `/config/packages` gemeinsam. Die Prüfung erkennt:

- gleiche Package-Dateinamen auch in verschiedenen Unterverzeichnissen,
- `.yml`-Dateien, die von Verzeichnis-Includes nicht automatisch geladen werden,
- doppelte Entity-IDs in mappingbasierten Integrationen,
- doppelte, nicht zusammenführbare Integrationsschlüssel,
- mehrfach verwendete `unique_id`- und Automation-ID-Werte,
- ungültige YAML- oder Package-Wurzelstrukturen.

Listenbasierte Plattformdefinitionen dürfen gemäß den Package-Merge-Regeln in
mehreren Dateien vorkommen. Bei `!include_dir_merge_named` wird zusätzlich die
äußere Package-Ebene berücksichtigt. Die Hauptkonfiguration wird für mögliche
Kollisionen mit den Packages mitgeprüft.

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
