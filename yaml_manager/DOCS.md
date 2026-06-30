# HA Maintenance Hub

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

## Script-Abhängigkeiten und Umbenennung

Der Tab **Bezüge** im rechten Hilfebereich zeigt für die geöffnete Datei:

- alle darin definierten Scripts,
- ausgehende Verweise auf Scripts, Szenen und Entitäten,
- eingehende Verweise aus anderen Package-Scripts,
- bekannte Script-Definitionen als direktes Navigationsziel.

Erkannt werden `entity_id`-Werte, direkte Script- und Szenenaktionen sowie
Entitäten in üblichen `states(...)`- und `is_state(...)`-Templates. Ein Klick
auf einen Bezug öffnet die betreffende Datei und markiert die Fundstelle.

**Umbenennen** an einer Script-Definition arbeitet ausschließlich auf dem
gespeicherten Package-Stand. Zuerst wird eine Vorschau mit allen betroffenen
Dateien erzeugt. Vor der Anwendung prüft das Backend einen SHA-256-Zustandshash
über sämtliche Packages. Zwischenzeitliche Änderungen führen zu HTTP `409`.
Die neuen Inhalte werden als YAML validiert und dürfen keine zusätzlichen
Package-Konflikte erzeugen. Anschließend werden Backups angelegt, alle Dateien
atomar geschrieben, gemeinsam in Git versioniert und durch Home Assistant
geprüft. Freitext in Alias oder Beschreibung wird nicht als Referenz geändert.

Die zugehörigen HTTP-Endpunkte sind:

- `GET /api/dependencies?path=<package>`
- `POST /api/script/rename-preview`
- `POST /api/script/rename`

## Live-HA-Semantikprüfung

Die normale YAML- und Package-Prüfung läuft weiterhin lokal während der Eingabe.
Wenn die App innerhalb von Home Assistant einen Supervisor-Token erhält, ergänzt
sie diese Prüfung um semantische Hinweise aus den aktuellen HA-Helferdaten. Dafür
werden `states`, `services`, `config/device_registry/list` und
`config/area_registry/list` serverseitig gelesen und kurzzeitig gecacht.

Die Prüfung erkennt unter anderem:

- unbekannte Dienste unter `action:` beziehungsweise `service:`,
- fehlende Service-Felder, die Home Assistant als erforderlich meldet,
- unbekannte `entity_id`, `device_id` und `area_id`-Werte,
- offensichtliche Domain-Konflikte zwischen Dienst und Zielentität.

Ist die Home-Assistant-API lokal nicht verfügbar, bleibt die Zusatzprüfung ohne
Fehlermeldung inaktiv.

API-Endpunkt:

- `GET /api/helpers`

## Backend-Module

Die Backend-Verantwortlichkeiten sind getrennt aufgebaut:

- `app.py`: Service-Fassade, Package-Dateien, Analyse und Orchestrierung
- `api.py`: HTTP-Routing, JSON und statische Dateien
- `configuration.py`: `configuration.yaml`, Package-Einbindung und Migration
- `git.py`: lokale Historie, Restore und geschützter Remote-Sync
- `backup.py`: Backup-Historie, Diff und Wiederherstellung
- `validation.py`: Home-Assistant-kompatibler YAML-Loader und Syntaxprüfung
- `dependencies.py`: Script-Graph und quellpositionsbasierte Umbenennung
- `semantic.py`: Live-HA-Semantikprüfung anhand von States, Services, Devices und Areas
- `blueprints.py`: Blueprint-Index, Import, Erzeugung und Package-Instanziierung
- `documentation.py`: Markdown- und HTML-Dokumentationsdaten
- `security.py`: Secret-Referenzen, Klartext-Heuristiken und Push-Warnungen
- `traces.py`: Home-Assistant-Trace-Index und Trace-Detaildaten
- `flow.py`: Ablaufgraphen für Scripts und Automationen
- `impact.py`: Vor-Speichern-Vergleich und Risikoübersicht
- `review.py`: Änderungspakete mit Overlay-Prüfung, Gesamt-Diff und gemeinsamer Anwendung
- `lint.py`: konfigurierbare Projektregeln für HA-YAML
- `compatibility.py`: HA-Kompatibilitäts- und Deprecation-Hinweise
- `refactor.py`: typisiertes Refactoring für Objekte, IDs und Package-Pfade
- `graph.py`: globaler Objekt-, Entity-, Secret- und Blueprint-Graph
- `entity_health.py`: Entity-Status aus YAML-Referenzen, States und Registry
- `entity_refactor.py`: entity-exakte Multi-Datei-Umbenennungen
- `secrets_manager.py`: maskierte `secrets.yaml`-Verwaltung
- `preflight.py`: gebündelte Push-Bereitschaftsprüfung
- `maintenance.py`: manuelle und geplante Wartungsläufe mit Historie
- `errors.py`: gemeinsamer erwarteter API-Fehlertyp

## Home-Assistant-Objektbrowser

**HA-Objekte** ist ein eigener Navigationseintrag in der linken Sidebar und
öffnet eine durchsuchbare Inhaltsseite über Automationen, Scripts und Szenen.
Die Sidebar bleibt dabei sichtbar; ein modaler Dialog wird nicht mehr verwendet.
Die kompakte Liste trennt Objektname und Entity-ID, Quelldatei und Zeile,
erkannte Referenzen sowie ein- und ausgehende Bezüge. Berücksichtigt werden
Definitionen in Packages sowie die
Top-Level-Bereiche `automation`, `script` und `scene` aus `configuration.yaml`.
Folgende ausgelagerte Varianten werden verfolgt:

- `!include`
- `!include_dir_list`
- `!include_dir_named`
- `!include_dir_merge_list`
- `!include_dir_merge_named`

Package-Treffer öffnen den normalen Package-Editor, direkte Definitionen öffnen
den `configuration.yaml`-Editor und ausgelagerte Dateien den neuen
Ressourceneditor. Der Index zeigt außerdem erkannte Script-, Szenen- und
Entitätsreferenzen sowie ein- und ausgehende Bezüge.

Der Ressourceneditor akzeptiert nur tatsächlich eingebundene YAML-Dateien
innerhalb des Home-Assistant-Konfigurationsverzeichnisses. Symlinks und Pfade
außerhalb dieses Verzeichnisses werden abgewiesen. Speichern verwendet
Versionsvergleich, YAML-Prüfung, Backup, atomaren Austausch, Git-Commit und
Home-Assistant-Prüfung.

API-Endpunkte:

- `GET /api/ha-objects`
- `GET /api/resource`
- `PUT /api/resource`

## Multi-Datei-Suche und Ersetzen

**Suchen/Ersetzen** durchsucht `configuration.yaml`, alle Packages und die vom
Objektindex erkannten Includes. Die Ersetzung ist literal; optional wird die
Groß-/Kleinschreibung ignoriert. Die Vorschau nennt Treffer, Dateien und Zeilen.
Sie ist auf 5000 Treffer begrenzt.

Vor der Anwendung werden sämtliche erzeugten Inhalte als YAML validiert. Neue
Package-Konflikte führen zum Abbruch. Ein SHA-256-Hash über den vollständigen
verwalteten Dateibestand schützt vor parallelen Änderungen. Danach werden alle
Originale gesichert, atomar ausgetauscht und in einem gemeinsamen Git-Commit
festgehalten. Ein Schreibfehler löst ein Rollback aller bereits geschriebenen
Dateien aus.

API-Endpunkte:

- `POST /api/search-replace/preview`
- `POST /api/search-replace/apply`

## Review-Modus

**Review** sammelt mehrere geplante Dateiänderungen in einem stateless
Änderungspaket. Die Vorschau erzeugt pro Datei einen Unified Diff und prüft den
Overlay-Stand gegen YAML-Syntax, Package-Konflikte, konfigurierbare Lint-Regeln
und HA-Kompatibilitätsregeln. Die Vorschau enthält einen SHA-256-Zustandshash
über alle verwalteten YAML-Dateien.

Beim Anwenden wird derselbe Hash erneut geprüft. Danach werden alle betroffenen
Dateien gesichert, atomar geschrieben, gemeinsam in Git versioniert und durch
Home Assistant geprüft. Bei einem Schreibfehler wird der gesamte Dateisatz auf
den vorherigen Stand zurückgerollt.

API-Endpunkte:

- `POST /api/review/preview`
- `POST /api/review/apply`

## Lint-Regeln und Kompatibilität

**Lint** verwendet Regeln aus den normalen App-Einstellungen. Unterstützt werden
Pflichten für Alias beziehungsweise Name, Script-`mode`, Automation-`id`,
Regex-Muster für Script- und Entity-IDs, erlaubte Entity-Domains, verbotene
Klartextmuster sowie Pflicht-Tags für Package-Dateien. Die Findings erscheinen
in der Live-Editoranalyse, im Dashboard, im Preflight und auf der eigenen
Lint-Seite.

**HA-Kompatibilität** prüft konservativ auf historische Schlüssel wie
`data_template`, alte Dienste aus der lokalen Regelbasis und Syntaxstellen, die
bei einer späteren Migration geprüft werden sollten. Wenn die Supervisor-API
verfügbar ist, wird zusätzlich die laufende Home-Assistant-Version angezeigt.

API-Endpunkte:

- `GET /api/lint`
- `GET /api/compatibility`
- `PUT /api/settings` mit `lintRules`

## Refactoring und Gesamtgraph

Der neue Refactor-Bereich nutzt `POST /api/refactor/preview` und
`POST /api/refactor/apply`. Unterstützt werden Entity-IDs, Helper-Entities,
Szenen, Automationen, `device_id`, `area_id` und Package-Verschiebungen. Alle
Inhaltsänderungen laufen mit YAML-Prüfung, Zustandshash, Backup, atomarem Write,
Package-Konfliktprüfung, Git-Commit und Home-Assistant-Check. Package-
Verschiebungen übernehmen zusätzlich Kategorie und Tags aus den Metadaten.

**Graph** baut aus dem HA-Objektindex, den erkannten Referenzen, `!secret`-
Verwendungen und `use_blueprint`-Blöcken eine globale Knoten-/Kantenliste. Die
Oberfläche filtert nach Knotenart und Suchtext; Fundstellen öffnen direkt den
Package-, Konfigurations- oder Ressourceneditor.

API-Endpunkte:

- `GET /api/graph`
- `POST /api/refactor/preview`
- `POST /api/refactor/apply`

## Git-Branch-Verwaltung

Die eigene Seite **Git** zeigt alle lokalen Branches und den aktiven Branch. Neue Branches
werden vom aktuellen `HEAD` erstellt und sofort ausgecheckt. Vor Branch-Wechseln
und Merges legt die App einen Git-Zwischenstand der verwalteten Konfiguration an.

**Vergleichen** zeigt Ahead/Behind-Werte, betroffene Dateien und einen gekürzten
Unified Diff für `configuration.yaml` und Packages. Erst diese Vorschau schaltet
**Geprüft zusammenführen** frei. Ändert sich einer der beiden Commits, muss der
Vergleich wiederholt werden. Merge-Konflikte oder ungültiges Ergebnis-YAML
führen zu `git merge --abort`; ein fehlerhafter Merge-Commit bleibt nicht zurück.

API-Endpunkte:

- `GET /api/git/branches`
- `POST /api/git/branches/create`
- `POST /api/git/branches/switch`
- `POST /api/git/branches/compare`
- `POST /api/git/branches/merge`

## Automatischer Git-Remote-Push

Die App erstellt bei jedem erfolgreichen Schreibvorgang weiterhin zuerst einen
lokalen, pfadbegrenzten Commit. Auf der Seite **Git** kann unter **Git Remote** zusätzlich
**Nach jedem Speichern automatisch pushen** aktiviert werden. Diese Einstellung
wird zusammen mit der Remote-Konfiguration unter `/data/git_remote.json`
gespeichert und ist bei konfigurierten Remotes standardmäßig aktiv.

Nach dem lokalen Commit führt das Backend die geschützte Push-Variante der
bestehenden Synchronisation aus. Vor dem Push wird der Remote-Branch abgerufen.
Ist er neuer oder divergiert, wird nicht überschrieben. Der Datei-Speichervorgang
bleibt in diesem Fall erfolgreich und die API liefert unter `gitSync` eine
separate Fehlermeldung, die das Frontend sichtbar anzeigt.

Auto-Push gilt für Package- und Konfigurationsspeicherungen, HA-Ressourcen,
Package-Einbindung, Migration, Script-Umbenennung, Multi-Datei-Ersetzung und
ZIP-Import. Tokens bleiben aus API-Antworten, Remote-URLs und Prozessargumenten
ausgeschlossen.

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

Git-Commits werden mit `HA Maintenance Hub <ha-maintenance-hub@local>` erstellt.
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

## GitHub- und GitLab-Remote

Die Seite **Git** enthält eine optionale Git-Remote-Konfiguration. Erlaubt
sind ausschließlich HTTPS-Repository-URLs auf `github.com` und `gitlab.com`;
eingebettete Benutzernamen, Tokens, Query-Parameter und URL-Fragmente werden
abgewiesen. Die App verwendet den eigenen Remote-Namen `yaml-manager` und
verändert einen eventuell vorhandenen `origin`-Remote nicht.

Benutzername und Personal Access Token werden in `/data/git_remote.json`
gespeichert. Die Datei erhält Modus `0600`. API-Antworten enthalten nur die
Information, ob ein Token vorhanden ist. Während eines Netzwerkbefehls liefert
ein kurzlebiger Askpass-Prozess die Zugangsdaten aus Umgebungsvariablen; damit
stehen sie weder in `.git/config`, der Remote-URL noch in Prozessargumenten.
GitHub und GitLab unterstützen Personal Access Tokens als Passwort für Git über
HTTPS. Verwende nur minimal berechtigte Tokens und ein privates Repository.
Siehe dazu die offiziellen Hinweise von
[GitHub](https://docs.github.com/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
und [GitLab](https://docs.gitlab.com/user/profile/personal_access_tokens/).

Die Synchronisation erfolgt ausschließlich nach einer manuellen Aktion:

- **Fetch** aktualisiert die lokale Remote-Referenz ohne Arbeitsdateien zu ändern.
- **Pull** übernimmt nur Fast-forward-Änderungen.
- **Push** überträgt den lokalen `HEAD` auf den konfigurierten Remote-Branch.
- **Sicher synchronisieren** führt Fetch, einen möglichen Fast-forward und Push aus.

Sind lokale und entfernte Historie divergiert, zeigt die Git-Seite zwei
Auflösungswege:

- **Historien verbinden** ist für ein neu angelegtes Remote mit eigenem README-
  oder Lizenz-Commit vorgesehen. Die App prüft den Remote-Baum, sichert lokale
  YAML-Dateien, führt einen Merge mit `--allow-unrelated-histories` aus und pusht
  den gemeinsamen Stand. Bei Dateikonflikten wird der Merge vollständig
  abgebrochen.
- **Remote durch lokalen Stand ersetzen** verwendet `force-with-lease`. Dadurch
  wird nur gepusht, wenn der Remote-Branch seit dem letzten Fetch unverändert
  geblieben ist. Die bisherige Remote-Historie wird dabei bewusst verworfen.

Automatisch übernommene Remote-Pfade bleiben auf `configuration.yaml`, gültige
Package-YAML-Dateien sowie README, LICENSE, CHANGELOG, `.gitignore` und
`.gitattributes` beschränkt. Andere Pfade, Symlinks, zu große Dateien und
ungültiges YAML führen zum Abbruch. Automatische Rebases und ungeschützte
Force-Pushes werden nicht ausgeführt.

API-Endpunkte:

- `GET|PUT|DELETE /api/git/remote`
- `POST /api/git/remote/sync`

## Qualitätsdashboard

Das Dashboard ist der erste Eintrag oben in der linken Seitenleiste. Kategorien,
Tags und die Script-Direktauswahl bleiben während der Dashboard-Anzeige sichtbar.
Ein Klick auf eine Datei öffnet sie unmittelbar im Script-Editor; der Eintrag
**Dashboard** führt zurück, ohne den geöffneten Editorstand zu verwerfen. Das
Dashboard kombiniert die
globale Package-Konfliktprüfung mit Betriebs-, Objekt-, Blueprint-, Security-,
Trace- und Semantikdaten. Angezeigt werden Package-Dateien, Automationen,
Scripts, Szenen, Bezüge, Blueprints, Security-Hinweise, Entity-Health,
Trace-Status, Fehler, Warnungen, Backups und ein daraus berechneter
Qualitätswert. Git-Branches und Remote-Sync sind bewusst auf die eigene Seite
**Git** verschoben.

Findings können ein `action`-Objekt enthalten. Das Frontend öffnet damit je nach
Hinweis die Konfliktübersicht, die Blueprint-Seite, die Sicherheitsprüfung, die
Trace-Ansicht oder eine konkrete Datei mit Zeilensprung. Das Dashboard bleibt
dadurch der Einstiegspunkt zur Behebung, ohne Git-Bedienelemente wieder in die
Qualitätsseite zu mischen.

Jeder Dashboard-Hinweis erhält serverseitig einen stabilen Schlüssel aus Code,
Schwere, Text, Datei und Zeile. Über die Oberfläche kann ein Hinweis
ausgeblendet oder als gegenstandslos markiert werden. Diese Markierungen werden
unter `/data/dashboard_findings.json` gespeichert, aus der aktiven Hinweis- und
Score-Berechnung entfernt und über **Ausgeblendete anzeigen** wieder sichtbar.
Von dort kann ein Hinweis erneut eingeblendet werden.

Für die Nutzungsanalyse werden Script-Definitionen mit `script.<id>`-Referenzen
in allen lesbaren YAML-Dateien unterhalb des Konfigurationsverzeichnisses
verglichen. Nicht gefundene Referenzen werden bewusst nur als **möglicherweise
ungenutzt** gemeldet: Aufrufe aus Dashboards, der Benutzeroberfläche, Apps oder
externen Integrationen sind aus YAML allein nicht vollständig ableitbar.

## Blueprint-Unterstützung

**Blueprints** ist eine eigene Inhaltsseite in der linken Navigation. Die App
liest YAML-Dateien unter `/config/blueprints/automation`,
`/config/blueprints/script` und `/config/blueprints/scene`, validiert den
`blueprint:`-Block und zeigt Domain, Eingaben und Quellpfad an.

Unterstützt werden:

- vorhandene Blueprints anzeigen und filtern,
- Blueprint-YAML in einen sicheren Zielpfad importieren,
- aus einem Automation-, Script- oder Szenen-YAML einen Blueprint-Skeleton erzeugen,
- Automation- und Script-Blueprints als neue Package-Datei mit `use_blueprint`
  instanziieren.

Blueprint-Import und YAML-basierte Erzeugung schreiben atomar, erzeugen lokale
Git-Commits und verwenden die vorhandene geschützte Token-/Remote-Sync-Logik.
Die Instanziierung läuft über den normalen Package-Erstellungsweg mit YAML-
Prüfung, Metadaten, Git-Commit und Home-Assistant-Konfigurationsprüfung.

API-Endpunkte:

- `GET /api/blueprints`
- `GET /api/blueprint`
- `POST /api/blueprints/import`
- `POST /api/blueprints/from-yaml`
- `POST /api/blueprints/instantiate`

## Dokumentationsgenerator

Die Seite **Doku** erzeugt eine Markdown-Übersicht und eine interne HTML-Ansicht
über den verwalteten Bestand. Die generierte Markdown-Datei enthält
Package-Dateien, Automationen, Scripts, Szenen, erkannte Script-/Szenenbezüge,
verwendete Entitäten, Package-Auffälligkeiten und die letzten Git-Commits.

Die HTML-Ansicht verwendet dieselbe API-Antwort, arbeitet aber mit den
strukturierten Daten aus `data`. Tabs zeigen:

- Übersichtskarten und Objekt-Tabelle,
- Objektgraph aus Script- und Szenenbezügen,
- Entity-Liste mit Domain und Verwendungszahl,
- Änderungsverlauf aus Git-Commits und Findings,
- die Markdown-Rohansicht.

Der Suchfilter wird clientseitig auf die jeweils aktive Ansicht angewendet.
Über **Unter /data speichern** wird der aktuelle Markdown-Stand atomar unter
`/data/documentation/packages.md` abgelegt.

API-Endpunkte:

- `GET /api/documentation`
- `POST /api/documentation/write`

## Secret- und Sicherheitsprüfung

Die Seite **Sicherheit** scannt alle verwalteten Package-YAML-Dateien. Das
Backend liest zusätzlich `/config/secrets.yaml`, ohne die Datei zu verändern.
Geprüft werden:

- `!secret`-Referenzen auf eine fehlende `secrets.yaml`,
- `!secret`-Namen, die nicht in `secrets.yaml` definiert sind,
- mögliche Klartext-Tokens in URL-Parametern und typischen Feldern wie
  `token`, `api_key`, `password` oder `client_secret`,
- wahrscheinlich ungenutzte Secrets.

Fehlende Secrets werden als Fehler, Klartext-Heuristiken als Warnung und
ungenutzte Secrets als Tipp ausgegeben. Vor manuellem Git-Push, sicherer
Synchronisation, Merge-Push und Force-Push ruft das Frontend zusätzlich
`/api/security/push-warning` auf. Enthält die Antwort Fehler oder Warnungen,
muss die Remote-Aktion bewusst bestätigt werden. Der automatische Push nach
einem Speichervorgang kann nicht interaktiv nachfragen und wird deshalb
serverseitig blockiert; die API meldet dies unter `gitSync`, während der lokale
Commit erhalten bleibt.

API-Endpunkte:

- `GET /api/security`
- `GET /api/security/push-warning`

## Jinja-Template-Tester

Der Hilfebereich enthält den Tab **Templates**. Das eingegebene Template wird
serverseitig über Home Assistants `POST /api/template` gerendert. Das Ergebnis
oder die Fehlermeldung erscheint direkt im Tab.

Die App extrahiert verwendete Entitäten lokal aus `states(...)`, `is_state(...)`,
`state_attr(...)`, `is_state_attr(...)` und `states.domain.object`. Dadurch ist
die Entity-Liste auch dann hilfreich, wenn die Home-Assistant-API in der lokalen
Entwicklung nicht verfügbar ist.

API-Endpunkt:

- `POST /api/template/render`

## Trace-/Debug-Ansicht

Die Seite **Traces** nutzt den HA-Objektindex und fragt für Automationen und
Scripts die Home-Assistant-Trace-API ab. Die Liste enthält Entity-ID, Alias,
Zeitpunkt, Status, letzten Schritt und Fehlerhinweis. Ein Klick auf einen Trace
lädt die Detailantwort für die Run-ID nach und zeigt sie als JSON an.

Die Trace-Ansicht ist ein Best-effort-Debugwerkzeug. Ohne Supervisor-Token oder
ohne verfügbare Trace-API bleibt die Seite erreichbar und zeigt die
Nichtverfügbarkeit an, statt die übrige App zu blockieren.

Unter **Testlauf** startet die Seite erkannte Scripts und Automationen direkt
über Home Assistant. Scripts verwenden `script.turn_on`, Automationen
`automation.trigger` mit `skip_condition: true`; die Entity-ID wird dabei als
Servicedatum gesendet, damit der REST-Serviceaufruf auch ohne UI-Target-Schema
funktioniert. Nach einem erfolgreichen Serviceaufruf fragt die Oberfläche den
Trace-Index mehrmals kurz nach und öffnet den neuesten passenden Trace, sobald
Home Assistant ihn bereitstellt. Lehnt Home Assistant den Serviceaufruf ab,
liest das Backend die konkrete HTTP-Fehlermeldung aus und zeigt sie im
Trace-Detailbereich an.

API-Endpunkte:

- `GET /api/traces`
- `GET /api/trace?domain=<automation|script>&itemId=<id>&runId=<run>`
- `POST /api/ha-object/run`

## Visuelle Flow-Ansicht

Der Hilfebereich enthält den Tab **Flow**. Die Analyse läuft auf dem aktuell im
Editor stehenden YAML und muss nicht gespeichert sein. Serverseitig wird der
YAML-Knotenbaum verarbeitet, damit Zeilennummern erhalten bleiben.

Erkannt werden:

- Script-Start und Automation-Start,
- Automation-Trigger und globale Bedingungen,
- Serviceaufrufe unter `action:` beziehungsweise `service:`,
- Bedingungen,
- `choose`-Zweige inklusive `default`,
- `repeat`,
- `if`/`then`/`else`,
- `delay`, `wait_template`, `wait_for_trigger`,
- Events, Variablen und `stop`.

Jeder Knoten im Frontend springt per Klick zur Quellzeile. Die Ansicht ist eine
Orientierungshilfe und ersetzt nicht Home Assistants eigene Trace-Engine.

API-Endpunkt:

- `POST /api/flow`

## Impact-Analyse vor dem Speichern

Vor dem Speichern einer Package-Datei fragt das Frontend `POST /api/impact` ab.
Das Backend vergleicht die gespeicherte Datei mit dem Editorinhalt und baut
zusätzlich einen Dependency-Graph vor und nach der Änderung auf.

Der Dialog zeigt:

- hinzugefügte und entfernte Entities,
- geänderte Script- und Entity-Referenzen,
- entfernte Script-Definitionen mit eingehenden Bezügen,
- neue oder entfernte `!secret`-Referenzen,
- neue oder entfernte Blueprint-Pfade,
- betroffene Script-Entities, deren Traces nach einem Testlauf relevant wären.

Ein erkannter Fehler verhindert das Speichern nicht technisch, erzwingt aber
eine bewusste Bestätigung. Danach läuft der normale geschützte Schreibpfad mit
Versionsvergleich, YAML-Prüfung, Backup, Git-Commit und HA-Konfigurationsprüfung.

API-Endpunkt:

- `POST /api/impact`

## Entity-Health

**Entity-Health** ist eine eigene Inhaltsseite in der linken Navigation. Sie
kombiniert erkannte YAML-Entity-Referenzen mit Home Assistants `states` und dem
Entity-Registry-Listing.

Kategorien:

- **Unbekannt**: referenziert, aber weder State noch deaktivierter Registry-Eintrag vorhanden.
- **Unavailable/Unknown**: referenziert und in HA bekannt, aber mit problematischem Zustand.
- **Deaktiviert**: referenziert, aber laut Entity Registry deaktiviert.
- **Nicht in YAML genutzt**: in HA bekannt, aber in verwaltetem YAML nicht referenziert.

Die letzten drei Werte werden nur innerhalb der verfügbaren Home-Assistant-Daten
bewertet. Ohne Supervisor-Token zeigt die Seite die Nichtverfügbarkeit an und
blockiert keine anderen Funktionen.

API-Endpunkt:

- `GET /api/entity-health`

## Entity-Refactoring

Die Seite **Refactor** ersetzt eine Entity-ID über alle verwalteten YAML-Dateien:
Packages, `configuration.yaml` und erkannte HA-Includes. Die Suche ist
entity-exakt und nutzt Grenzen um die Entity-ID, damit ähnlich benannte Entities
nicht berührt werden.

Die Vorschau enthält Trefferzahl, Dateien und Zeilen. Beim Anwenden gelten:

- Zustandshash über den verwalteten YAML-Bestand,
- YAML-Validierung jeder geänderten Datei,
- Package-Konfliktprüfung für betroffene Packages,
- Backups vor dem Schreiben,
- atomarer Austausch mit Rollback bei Schreibfehlern,
- Git-Commit und optional geschützter Auto-Push,
- Home-Assistant-Konfigurationsprüfung nach dem Schreiben.

API-Endpunkte:

- `POST /api/entity-refactor/preview`
- `POST /api/entity-refactor/apply`

## Secrets-Manager

Die Seite **Secrets** verwaltet `/config/secrets.yaml` maskiert. Das Backend
gibt Secret-Werte nie zurück, sondern nur Name, Maske und Referenzanzahl.

Unterstützte Aktionen:

- Secret anlegen oder aktualisieren,
- Secret löschen,
- Klartext-Zeile in einer verwalteten YAML-Datei durch `!secret <name>` ersetzen
  und den Wert gleichzeitig in `secrets.yaml` speichern.

Die Umwandlung prüft Pfad, Zeile und YAML-Schlüssel. Danach werden sowohl die
YAML-Datei als auch `secrets.yaml` gesichert, atomar geschrieben und gemeinsam
versioniert.

API-Endpunkte:

- `GET /api/secrets`
- `POST /api/secrets`
- `DELETE /api/secrets`
- `POST /api/secrets/convert`

## Preflight

**Preflight** ist die zusammengefasste Prüfung vor einem Push. Die Seite ruft
serverseitig folgende Checks auf:

- YAML-Syntax aller verwalteten Dateien,
- Package-Konflikte,
- Security- und Secret-Scan,
- Entity-Health,
- Home-Assistant-Konfigurationsprüfung,
- Dokumentationsstatus,
- Git-Remote-Status.

Die Antwort enthält `blockers`, `warnings`, `ready` und eine Checkliste mit
Details. Blocker sind harte Probleme wie ungültiges YAML, Package-Fehler,
Security-Fehler oder ein fehlgeschlagener Home-Assistant-Check.

API-Endpunkt:

- `GET /api/preflight`

## Wartung

**Wartung** erweitert den Preflight zu einem wiederholbaren Betriebscheck. Ein
Wartungslauf kombiniert Preflight, Recorder-Health und Systemstatus, leitet eine
kompakte Checkliste sowie aktive Findings ab und speichert das Ergebnis unter
`/data/maintenance-history.json`. Jeder Eintrag enthält Status, Blocker,
Warnungen, Laufdauer, Detaildaten und ein Delta zum vorherigen Lauf.

Die Einstellungen liegen in `/data/settings.json` und steuern automatische
Ausführung, Intervall, Historienlänge, Recorder-Prüfung und optionale
Home-Assistant-Benachrichtigung über `persistent_notification.create`. Der
Hintergrundplaner wird nur beim normalen App-Start aktiviert; Tests und reine
Imports starten keinen Wartungsthread.

API-Endpunkte:

- `GET /api/maintenance/status`
- `GET /api/maintenance/history`
- `POST /api/maintenance/run`

## Package-Import und -Export

Der ZIP-Export unterstützt den aktuellen Editor, eine Kategorie oder den
vollständigen Package-Bestand. Neben den YAML-Dateien enthält `manifest.json`
die Kategorien und Tags. Ein Export ist auf 500 Dateien und 50 MiB ungepackte
Daten begrenzt.

Beim ZIP-Import gelten folgende Prüfungen:

- höchstens 10 MiB Archivgröße, 500 Dateien und 50 MiB entpackte Daten,
- keine verschlüsselten Einträge oder Pfade außerhalb von `packages`,
- ausschließlich `.yaml` und `.yml` in UTF-8,
- gültige YAML-Syntax und eindeutige Archivpfade,
- globale Package-Konfliktprüfung mit dem geplanten Zielbestand,
- Anzeige vorhandener Zieldateien vor dem Schreiben.

Die Strategien **Überspringen** und **Überschreiben** bestimmen den Umgang mit
vorhandenen Dateien. Der Vorschau-Hash umfasst das Archiv und den vollständigen
Package-Bestand. Ändert sich bis zur Bestätigung eine Package-Datei, wird der
Import abgebrochen. Beim Anwenden werden vorhandene Dateien gesichert, alle
Schreibvorgänge gemeinsam ausgeführt und bei einem Dateifehler zurückgerollt.
Danach entstehen ein Git-Commit und eine Home-Assistant-Konfigurationsprüfung.

Die zugehörigen Endpunkte sind:

- `GET /api/export`
- `POST /api/import/preview`
- `POST /api/import/apply`
- `GET /api/dashboard`
- `POST /api/dashboard/finding`
- `DELETE /api/dashboard/finding`

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

## Package-Prüfung

Der Tab **Prüfung** wird während der Eingabe aktualisiert und zeigt einen
Qualitätswert sowie priorisierte Hinweise. Geprüft werden unter anderem:

- doppelte YAML-Schlüssel wie zwei `template:`-Blöcke im selben Bereich,
- gleiche Script-IDs in anderen Package-Dateien,
- mehrfach verwendete `entity_id`-Werte,
- unausgeglichene Jinja-Klammern,
- fehlende oder leere `sequence:`-Blöcke,
- fehlende Aliase und Script-Modi,
- Script-IDs mit ungeeigneten Zeichen.

Package-Dateien müssen keine `script:`-Sektion enthalten. Reine ausgelagerte
Konfigurationen aus `configuration.yaml`, etwa `template:`, `sensor:` oder
andere Home-Assistant-Domains, werden ohne Script-spezifischen Hinweis bewertet.

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
- **Flow** zeigt ein klickbares Ablaufdiagramm für Scripts und Automationen.
- **Entitäten** durchsucht die aktuellen Home-Assistant-Zustände und fügt eine
  `entity_id` ein.
- **Dienste** durchsucht verfügbare Aktionen und fügt einen Aktionsblock ein.
- **Templates** rendert Jinja-Ausdrücke gegen aktuelle Home-Assistant-States und
  zeigt die dabei erkannten Entitäten.

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
