# Home Assistant YAML Script Manager

Eine Home-Assistant-App zum Kategorisieren und Bearbeiten von YAML-Skripten,
Automationen, Szenen und zugehörigen YAML-Ressourcen.

## Funktionen

- Scrollbare Dateiliste mit Suche, Kategorien und Tags
- YAML-Editor mit Syntaxhervorhebung, Zeilennummern und Live-Validierung
- Kontextbezogene Script-Prüfung für doppelte Schlüssel, Script-IDs und Entitäten
- Script-Abhängigkeitsansicht mit Sprung zu Verwendung und Definition
- Vorschau-basierte Script-ID-Umbenennung einschließlich erkannter Referenzen
- Objektbrowser für Automationen, Scripts und Szenen aus Packages und Includes
- Geschützter Editor für `automations.yaml`, `scripts.yaml`, `scenes.yaml` und Include-Verzeichnisse
- Multi-Datei-Suche und Ersetzung mit Vorschau, Backups und gemeinsamem Git-Commit
- Schutz vor dem Überschreiben parallel geänderter Dateien
- Vorlagen für Aktionen, Bedingungen, Verzögerungen, Auswahl und Wiederholungen
- Suche nach Home-Assistant-Entitäten und -Diensten
- Sicheres Speichern mit Sicherungskopien und Papierkorb
- Umbenennen und Verschieben von Dateien innerhalb des Package-Ordners
- Direkter Aufruf von `script.reload`
- Prüfung, ob `/config/packages` über `homeassistant.packages` eingebunden ist
- Editor für `configuration.yaml` mit Ein-Klick-Package-Import
- Vorschau-basierte Auslagerung der Top-Level-Konfiguration in ein Package
- Automatische Home-Assistant-Konfigurationsprüfung nach Konfigurationsänderungen
- Versionsverlauf mit Diff und Wiederherstellung für Konfiguration und Packages
- Automatische lokale Git-Commits mit Historie, Diff und Wiederherstellung
- Git-Branches anzeigen, erstellen, wechseln, vergleichen und konfliktgeprüft zusammenführen
- Optionaler manueller GitHub-/GitLab-Remote-Sync mit geschützter Token-Ablage
- Globale Package-Konfliktprüfung nach den Home-Assistant-Merge-Regeln
- Qualitätsdashboard für Konflikte, Warnungen, Script-Nutzung, Backups und Git
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
`validation.py` und `dependencies.py` getrennt. Das Backend verwendet
ausschließlich die Python-Standardbibliothek für HTTP und Dateizugriffe;
PyYAML übernimmt die Syntaxprüfung. Home-Assistant-spezifische YAML-Tags wie
`!secret` und `!include` werden bei der Prüfung akzeptiert, doppelte Schlüssel
werden dagegen als Fehler gemeldet.

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

Der Versionsdialog ermittelt pro Datei alle Sicherungen, zeigt Additionen und
Löschungen sowie einen serverseitig erzeugten Unified Diff und stellt einen
ausgewählten Stand wieder her. Vor der Wiederherstellung wird die aktuelle
Fassung erneut gesichert. Ein SHA-256-Versionsvergleich verhindert, dass dabei
eine extern geänderte Datei überschrieben wird.

Die globale Konfliktanalyse liest alle Package-Dateien als YAML-Knotenbaum. Sie
erkennt doppelte Package-Dateinamen über Unterordner hinweg, kollidierende
Entity- und Integrationsschlüssel sowie doppelte `unique_id`- und Automation-ID-
Werte. Listenbasierte Plattformintegrationen werden entsprechend den
Home-Assistant-Package-Regeln als zusammenführbar behandelt.

Zusätzlich initialisiert die App bei Bedarf ein lokales Git-Repository im
Home-Assistant-Konfigurationsverzeichnis. Vor und nach jeder von der App
ausgeführten Dateiänderung werden ausschließlich die betroffenen Pfade
versioniert. Bereits vom Nutzer vorgemerkte Änderungen an anderen Dateien
bleiben unangetastet. Die Git-Historie in beiden Editoren bietet Commit-Metadaten,
Unified Diffs und eine konfliktgeschützte Wiederherstellung. Das bestehende
Datei-Backup wird dabei weiterhin zusätzlich angelegt.

Das Qualitätsdashboard ist der erste Eintrag links oben und fasst Package-Konflikte,
mögliche ungenutzte Scripts, Backup-Anzahl und Git-Remote-Status zusammen. Ein
optionaler HTTPS-Remote für GitHub.com oder GitLab.com kann manuell per Fetch,
Pull, Push oder sicherer
Synchronisation bedient werden. Das Token wird mit Dateimodus `0600` unter
`/data` gespeichert, nie an das Frontend zurückgesendet und nicht in
`.git/config` geschrieben.

Bei einer divergierten Historie bietet das Dashboard zwei bewusste Lösungen:
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
