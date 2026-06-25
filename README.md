# Home Assistant YAML Script Manager

Eine Home-Assistant-App zum Kategorisieren und Bearbeiten von YAML-Skripten,
Automationen, Szenen und zugehörigen YAML-Ressourcen.

## Funktionen

- Scrollbare Dateiliste mit Suche, Kategorien und Tags
- YAML-Editor mit Syntaxhervorhebung, Zeilennummern und Live-Validierung
- YAML-Strukturansicht, Editor-Autocomplete und Shortcuts für häufige Aktionen
- Kontextbezogene Script-Prüfung für doppelte Schlüssel, Script-IDs und Entitäten
- Live-HA-Semantikprüfung für Dienste, Ziel-Entitäten, Geräte, Bereiche und Pflichtfelder
- Script-Abhängigkeitsansicht mit Sprung zu Verwendung und Definition
- Vorschau-basierte Script-ID-Umbenennung einschließlich erkannter Referenzen
- Objektbrowser für Automationen, Scripts und Szenen aus Packages und Includes
- In die Sidebar integrierte, kompakte HA-Objektliste statt modaler Kartenansicht
- Blueprint-Browser mit Import, YAML-basierter Blueprint-Erzeugung und Package-Instanziierung
- Markdown-Dokumentationsgenerator für Packages, HA-Objekte, Bezüge, Entitäten und Git-Historie
- Geschützter Editor für `automations.yaml`, `scripts.yaml`, `scenes.yaml` und Include-Verzeichnisse
- Multi-Datei-Suche und Ersetzung mit Vorschau, Backups und gemeinsamem Git-Commit
- Schutz vor dem Überschreiben parallel geänderter Dateien
- Vorlagen für Aktionen, Bedingungen, Verzögerungen, Auswahl und Wiederholungen
- Suche nach Home-Assistant-Entitäten und -Diensten
- Sicheres Speichern mit Sicherungskopien und Papierkorb
- Papierkorb-Dialog zum Wiederherstellen oder endgültigen Entfernen gelöschter Dateien
- Automatische Papierkorb-Aufbewahrung nach Alter und Maximalgröße
- Umbenennen und Verschieben von Dateien innerhalb des Package-Ordners
- Direkter Aufruf von `script.reload`
- Prüfung, ob `/config/packages` über `homeassistant.packages` eingebunden ist
- Editor für `configuration.yaml` mit Ein-Klick-Package-Import
- Vorschau-basierte Auslagerung der Top-Level-Konfiguration in ein Package
- Automatische Home-Assistant-Konfigurationsprüfung nach Konfigurationsänderungen
- Versionsverlauf mit Side-by-side-Diff und Wiederherstellung für Konfiguration und Packages
- Automatische lokale Git-Commits mit Historie, Side-by-side-Diff und Wiederherstellung
- Eigene Git-Seite zum Anzeigen, Erstellen, Wechseln, Vergleichen und konfliktgeprüften Zusammenführen lokaler Branches
- Optionaler manueller GitHub-/GitLab-Remote-Sync mit geschützter Token-Ablage
- Optionaler automatischer Remote-Push nach jedem erfolgreichen Speichern
- Globale Package-Konfliktprüfung nach den Home-Assistant-Merge-Regeln
- Qualitätsdashboard für Konflikte, Warnungen, Script-Nutzung und Backups
- Erweitertes Dashboard für HA-Objekte, Referenzen, Blueprints, Live-HA-Semantik und Dokumentationsstatus
- Systemstatus im Dashboard für Home Assistant, Backups, Papierkorb und Importlimits
- Einstellungsdialog für Aufbewahrung, Importlimits, Dashboard-Regeln, Theme und Speicherverhalten
- Konfliktgeprüfter ZIP-Import und Export nach Datei, Kategorie oder Gesamtbestand
- Responsive Ingress-Oberfläche mit Hell- und Dunkelmodus

## Installation

1. Dieses Repository in Home Assistant unter **Einstellungen → Apps → App-Store →
   Repositories** hinzufügen.
2. **YAML Script Manager** installieren und starten.
3. Optional **In Seitenleiste anzeigen** aktivieren.

Die App bindet die Home-Assistant-Konfiguration schreibbar unter `/homeassistant`
ein und verwaltet ausschließlich `.yaml`- und `.yml`-Dateien im Unterverzeichnis
`packages`.

## Lokale Entwicklung

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r yaml_manager/requirements.txt
python yaml_manager/app.py \
  --packages-path /tmp/ha-packages \
  --data-path /tmp/yaml-manager-data
```

Danach ist die Oberfläche unter `http://localhost:8099` erreichbar. Die
Home-Assistant-Hilfsdaten und `script.reload` stehen lokal ohne Supervisor-Token
nicht zur Verfügung.

## Technische Beschreibung der Anpassungen

Die Implementierung ist in [yaml_manager](yaml_manager) gekapselt. `app.py`
stellt die kompatible Service-Fassade und Orchestrierung bereit. HTTP-Transport,
Konfigurationsbearbeitung, Git, Backups, YAML-Validierung und
Script-Abhängigkeiten sind in `api.py`, `configuration.py`, `git.py`, `backup.py`,
`validation.py` und `dependencies.py` getrennt. Metadatenverwaltung und
wiederholte YAML-Dateiscans sind zusätzlich in `metadata.py` und `file_cache.py`
ausgelagert, damit `app.py` weniger persistente Nebenlogik enthält. Das Backend
verwendet ausschließlich die Python-Standardbibliothek für HTTP und Dateizugriffe;
PyYAML übernimmt die Syntaxprüfung. Home-Assistant-spezifische YAML-Tags wie
`!secret` und `!include` werden bei der Prüfung akzeptiert, doppelte Schlüssel
werden dagegen als Fehler gemeldet.

Die Projektkonfiguration liegt in `pyproject.toml`. Die Test-Suite ist als
importierbares `tests`-Paket angelegt, sodass sowohl `python -m unittest` als
auch `python -m unittest discover -s tests` alle Tests finden. Der CI-Workflow
unter `.github/workflows/ci.yml` kompiliert die Python-Dateien, führt die
Unit-Tests unter Python 3.10, 3.11 und 3.13 aus und prüft den Docker-Build der
Home-Assistant-App.

Benutzerkonfigurationen werden als `/data/settings.json` gespeichert. Die App
normalisiert alle Werte serverseitig und begrenzt Backup-Aufbewahrung,
Importanzahl sowie ZIP- und Entpackgröße auf feste sichere Bereiche. Die
Einstellungen steuern unter anderem die Papierkorb-/Backup-Aufbewahrung, die
Anzeige möglicherweise ungenutzter Scripts im Dashboard, das bevorzugte
Branch-Präfix, das Theme und das Verhalten nach erfolgreichem Speichern.

Schreibzugriffe erfolgen atomar über eine temporäre Datei im Zielverzeichnis.
Ein SHA-256-Hash dient als Versionskennung und verhindert, dass eine zwischenzeitlich
extern geänderte Datei überschrieben wird. Vor jeder Änderung wird die bisherige
Fassung nach `/data/backups` kopiert. Beim Löschen wird die Datei nach `/data/trash`
verschoben. Kategorien und Tags stehen getrennt von den eigentlichen YAML-Dateien
in `/data/metadata.json`; dadurch verändern sie keine Home-Assistant-Konfiguration.
Das frühere Metadatenformat mit einer reinen Kategorie pro Datei wird beim Lesen
weiterhin unterstützt.

Die kontextbezogene Analyse verarbeitet das aktuell im Editor stehende YAML und
gleicht Script-IDs zusätzlich mit den übrigen Package-Dateien ab. Doppelte
YAML-Schlüssel, wiederholte Entitätsreferenzen, unausgeglichene Jinja-Klammern
und fehlende Script-Felder werden als priorisierte Hinweise ausgegeben. Hinweise
mit Zeilennummer können direkt angeklickt werden.

Die globale Abhängigkeitsanalyse ordnet Referenzen innerhalb jeder
Script-Definition ihrem Quell-Script zu. Sie erkennt direkte Script- und
Szenenaktionen, Werte unter `entity_id` sowie Entitäten in gebräuchlichen
`states(...)`- und `is_state(...)`-Templates. Der Editor zeigt ausgehende und
eingehende Bezüge und springt zur Verwendung oder zu einer bekannten
Script-Definition.

Beim Umbenennen einer Script-ID ermittelt das Backend anhand der YAML-Knoten
exakte Quellbereiche für die Definition und alle erkannten Referenzen. Eine
Vorschau nennt Dateien und Änderungszahl. Ein SHA-256-Hash über den gesamten
Package-Bestand verhindert die Anwendung einer veralteten Vorschau. Alle
Ergebnisse werden vorab als YAML und gegen neu entstehende Package-Konflikte
geprüft, gesichert, atomar geschrieben und gemeinsam in Git versioniert. Bei
einem Schreibfehler werden bereits ausgetauschte Dateien zurückgerollt.

Der HA-Objektindex liest zusätzlich die Top-Level-Bereiche `automation`,
`script` und `scene` aus `configuration.yaml`. Scalar-Includes über `!include`
sowie die vier `!include_dir_*`-Varianten werden innerhalb des
Konfigurationsverzeichnisses verfolgt. Gemeinsam mit den Packages entsteht so
eine durchsuchbare Liste aus Automationen, Scripts und Szenen. Ausgelagerte
Dateien werden nur bearbeitet, wenn sie über einen dieser Bereiche tatsächlich
eingebunden sind. Schreibvorgänge verwenden SHA-256-Konfliktschutz, YAML-Prüfung,
Backups, atomaren Austausch, Git und die Home-Assistant-Konfigurationsprüfung.

Die Multi-Datei-Ersetzung arbeitet auf `configuration.yaml`, allen Packages und
den erkannten HA-Includes. Die Vorschau enthält Trefferzahl, Dateien und Zeilen.
Ein Hash über den vollständigen verwalteten Dateibestand macht die Vorschau bei
Paralleländerungen ungültig. Vor dem gemeinsamen Schreibvorgang werden alle
Ergebnisse als YAML validiert und neue Package-Konflikte ausgeschlossen.

Die Branch-Verwaltung arbeitet ausschließlich mit lokalen Git-Branches. Vor
einem Wechsel oder Merge wird der aktuelle verwaltete Stand eingecheckt. Ein
Vergleich bindet Branch-Kopf und Ziel-Commit kryptografisch an die anschließende
Merge-Aktion. Ziel-YAML wird vorab geprüft; der Merge bleibt zunächst ohne
Commit, wird erneut validiert und bei Konflikten oder ungültigem YAML über
`git merge --abort` vollständig abgebrochen.

Die HA-Objektübersicht ist wie das Dashboard als eigener Inhaltsbereich rechts
neben der dauerhaft sichtbaren Sidebar eingebunden. Automationen, Scripts und
Szenen erscheinen in kompakten Tabellenzeilen mit Typ, Entity-ID, Quelldatei,
Fundzeile, Referenzen und Beziehungszählern. Dadurch bleiben auch große
`automations.yaml`-Bestände ohne überlagernden Dialog durchsuchbar.

Lokale Git-Commits werden weiterhin bei jedem Schreibvorgang erzeugt. Ist im
Bereich **Git Remote** auf der Git-Seite **Nach jedem Speichern automatisch pushen** aktiviert, führt das
Backend danach zusätzlich einen geschützten Push auf den konfigurierten
Remote-Branch aus. Dabei wird zuerst der Remote-Stand ermittelt; ein neuerer oder
divergierter Remote führt zu einem sichtbaren Sync-Fehler, ohne den bereits
erfolgreichen lokalen Speichervorgang rückgängig zu machen.

Das Frontend ist ohne externe Laufzeitabhängigkeiten umgesetzt. HTML, CSS und
JavaScript werden direkt von der App ausgeliefert und funktionieren unter dem von
Home Assistant gesetzten Ingress-Pfad. Die Syntaxhervorhebung liegt als synchronisierte
Darstellung unter einem nativen Textbereich. Die Home-Assistant-REST-API wird nur
serverseitig über den Supervisor-Token angesprochen.

Beim Laden der Dateiliste analysiert das Backend zusätzlich die
`configuration.yaml`. Die Statusanzeige erkennt die direkte Einbindung über
`!include_dir_named` beziehungsweise `!include_dir_merge_named` und folgt bei
Bedarf einer ausgelagerten `homeassistant: !include ...`-Konfiguration. Die App
verändert `configuration.yaml` dabei nicht automatisch.

Über den separaten Konfigurationseditor kann `configuration.yaml` nun bewusst
bearbeitet und gespeichert werden. Die Aktion **Packages einbinden** ergänzt
`homeassistant.packages`, ohne eine bereits abweichend konfigurierte Definition
zu überschreiben. **Alles in Package auslagern** zeigt zuerst die betroffenen
Top-Level-Bereiche und verschiebt sie anschließend nach
`/config/packages/configuration_import.yaml`. Relative `!include`-Pfade werden
an den neuen Standort angepasst. Der komplette `homeassistant:`-Block bleibt in
der Hauptdatei, damit frühe Core-Optionen wie `auth_providers` dort verbleiben.

Vor Konfigurationsänderungen legt die App Sicherungen unter `/data/backups` an.
YAML-Syntax und parallele Dateiänderungen werden geprüft. Nach Speichern,
Package-Einbindung, Migration und Wiederherstellung sowie nach dem Speichern oder
Erstellen einer Package-Datei ruft das Backend zusätzlich Home Assistants
`POST /api/config/core/check_config` über die Supervisor-API auf.
Das Ergebnis erscheint direkt oberhalb des Editors; enthält die Fehlermeldung
eine Zeilennummer, springt ein Klick zur betroffenen Stelle.

Gelöschte Package-Dateien werden mit Metadatenmanifest nach `/data/trash`
verschoben. Der Papierkorb-Dialog listet gelöschte Dateien mit ursprünglichem
Pfad, Kategorie, Tags, Version und Belegungsstatus des Zielpfads. Beim Öffnen
des Papierkorbs, nach dem Löschen und nach Einstellungsänderungen entfernt das
Backend abgelaufene Einträge und reduziert einen zu großen Papierkorb über die
ältesten Stände. Beim Wiederherstellen validiert das Backend das YAML erneut,
schützt vorhandene Zieldateien über SHA-256-Versionsvergleich, legt bei
Überschreibungen ein Backup an und erzeugt wie bei normalen Schreibvorgängen
einen Git-Commit.

Der Versionsdialog ermittelt pro Datei alle Sicherungen, zeigt Additionen und
Löschungen sowie einen serverseitig erzeugten Diff und stellt einen ausgewählten
Stand wieder her. Im Frontend wird der Diff als Side-by-side-Ansicht mit
Zeilennummern dargestellt; **Nur Änderungen** blendet Kontextzeilen aus und
fokussiert geänderte YAML-Blöcke. Vor der Wiederherstellung wird die aktuelle
Fassung erneut gesichert. Ein SHA-256-Versionsvergleich verhindert, dass dabei
eine extern geänderte Datei überschrieben wird.

Die globale Konfliktanalyse liest alle Package-Dateien als YAML-Knotenbaum. Sie
erkennt doppelte Package-Dateinamen über Unterordner hinweg, kollidierende
Entity- und Integrationsschlüssel sowie doppelte `unique_id`- und Automation-ID-
Werte. Listenbasierte Plattformintegrationen werden entsprechend den
Home-Assistant-Package-Regeln als zusammenführbar behandelt.

Wiederholte Lesevorgänge für Dashboard, Konfliktanalyse, Objektindex,
Abhängigkeitsanalyse und Include-Prüfungen verwenden einen gemeinsamen
UTF-8-Textcache. Der Cache ist pro absolutem Pfad, Dateigröße und `mtime_ns`
adressiert. Externe Änderungen werden dadurch beim nächsten Zugriff automatisch
sichtbar, während mehrere Analysen innerhalb eines Requests nicht dieselben
Dateien mehrfach von der Platte lesen müssen.

Zusätzlich initialisiert die App bei Bedarf ein lokales Git-Repository im
Home-Assistant-Konfigurationsverzeichnis. Vor und nach jeder von der App
ausgeführten Dateiänderung werden ausschließlich die betroffenen Pfade
versioniert. Bereits vom Nutzer vorgemerkte Änderungen an anderen Dateien
bleiben unangetastet. Die Git-Historie in beiden Editoren bietet Commit-Metadaten,
Side-by-side-Diffs mit Änderungsfokus und eine konfliktgeschützte Wiederherstellung.
Das bestehende Datei-Backup wird dabei weiterhin zusätzlich angelegt.

Das Qualitätsdashboard ist der erste Eintrag links oben und fasst Package-Konflikte,
mögliche ungenutzte Scripts, Backup-Anzahl, HA-Objekte, Blueprint-Bestand,
semantische Live-HA-Hinweise und den Dokumentationsstatus zusammen. Git-Branches
und Git-Remote-Aktionen sind aus dem Dashboard in eine eigene Inhaltsseite
verschoben. Ein optionaler HTTPS-Remote für GitHub.com oder GitLab.com kann dort
manuell per Fetch, Pull, Push oder sicherer Synchronisation bedient werden. Das
Token wird mit Dateimodus `0600` unter `/data` gespeichert, nie an das Frontend
zurückgesendet und nicht in `.git/config` geschrieben.

Die Live-HA-Semantikprüfung verwendet gecachte Daten aus `states`, `services`,
`config/device_registry/list` und `config/area_registry/list`. Während die
normale YAML- und Script-Prüfung unverändert lokal funktioniert, ergänzt die App
innerhalb von Home Assistant Hinweise zu unbekannten Diensten, fehlenden
Pflichtfeldern, nicht gefundenen Entitäten, Geräten und Bereichen sowie
offensichtlichen Service-/Entity-Domain-Konflikten. In der lokalen Entwicklung
ohne Supervisor-Token wird diese Zusatzprüfung als nicht verfügbar behandelt.

Blueprints werden unter `/config/blueprints/<domain>/...` gelesen und als eigene
Seite in der linken Navigation angezeigt. Importierte oder aus YAML erzeugte
Blueprint-Dateien werden validiert, atomar geschrieben und über Git versioniert.
Die Instanziierung erzeugt eine normale Package-Datei mit `use_blueprint` und
läuft dadurch durch dieselben Schutzmechanismen wie andere Package-Erstellungen.

Der Dokumentationsgenerator erstellt serverseitig eine Markdown-Übersicht über
Package-Dateien, Automationen, Scripts, Szenen, erkannte Bezüge, verwendete
Entitäten, Package-Auffälligkeiten und die letzten Git-Commits. Die Vorschau
erscheint in der Oberfläche; optional wird der Stand unter
`/data/documentation/packages.md` abgelegt.

Der Systemstatus im Dashboard ergänzt diese Qualitätswerte um konkrete
Betriebsinformationen: Home-Assistant-Token und letzte Konfigurationsprüfung,
Backup- und Papierkorbgröße sowie aktive Importlimits. Git-Verfügbarkeit und
Remote-Zustand bleiben über die eigene Git-Seite beziehungsweise
`/api/system/health` abrufbar.

Der Editor bleibt ein nativer Textbereich mit synchronisierter Highlighting-
Ebene. Ergänzend gibt es eine YAML-Strukturansicht aus erkannten Mapping-
Schlüsseln, eine Completion-Palette über `Strg`/`Cmd` + Leertaste für Entitäten,
Dienste, erkannte Scripts und Bausteine sowie Shortcuts für Speichern und
globale Suche/Ersetzung.

Bei einer divergierten Historie bietet die Git-Seite zwei bewusste Lösungen:
**Historien verbinden** übernimmt einen typischen initialen README-/Lizenz-Commit
und erzeugt einen gemeinsamen Merge. **Remote durch lokalen Stand ersetzen**
verwendet `force-with-lease` und verwirft die bisherige Remote-Historie nur,
solange sie seit dem letzten Fetch nicht erneut geändert wurde.

Die linke Spalte mit Kategorien, Tags und Script-Dateien bleibt auch im Dashboard
sichtbar. Ein Klick auf eine Datei wechselt unmittelbar in den YAML-Editor; über
den Dashboard-Eintrag gelangt man zurück zur Qualitätsübersicht.

Package-Dateien lassen sich einzeln, kategorieweise oder vollständig als ZIP
exportieren. Der Import prüft Archivpfade, Größenlimits, UTF-8, YAML und die
globalen Package-Merge-Regeln. Erst nach einer Vorschau werden Dateien
transaktional geschrieben; parallele Änderungen führen über einen globalen
Zustands-Hash zum Abbruch.

Weitere Betriebsinformationen stehen in [yaml_manager/DOCS.md](yaml_manager/DOCS.md).
Die ausführlichen Hinweise zur aktuellen Version stehen in
[yaml_manager/RELEASE_NOTES.md](yaml_manager/RELEASE_NOTES.md).
