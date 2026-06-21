# Home Assistant YAML Script Manager

Eine Home-Assistant-App zum Kategorisieren und Bearbeiten von YAML-Skripten im
Verzeichnis `/config/packages`.

## Funktionen

- Scrollbare Dateiliste mit Suche, Kategorien und Tags
- YAML-Editor mit Syntaxhervorhebung, Zeilennummern und Live-Validierung
- Kontextbezogene Script-Prüfung für doppelte Schlüssel, Script-IDs und Entitäten
- Schutz vor dem Überschreiben parallel geänderter Dateien
- Vorlagen für Aktionen, Bedingungen, Verzögerungen, Auswahl und Wiederholungen
- Suche nach Home-Assistant-Entitäten und -Diensten
- Sicheres Speichern mit Sicherungskopien und Papierkorb
- Umbenennen und Verschieben von Dateien innerhalb des Package-Ordners
- Direkter Aufruf von `script.reload`
- Prüfung, ob `/config/packages` über `homeassistant.packages` eingebunden ist
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
PACKAGES_PATH=/tmp/ha-packages DATA_PATH=/tmp/yaml-manager-data \
  python yaml_manager/app.py
```

Danach ist die Oberfläche unter `http://localhost:8099` erreichbar. Die
Home-Assistant-Hilfsdaten und `script.reload` stehen lokal ohne Supervisor-Token
nicht zur Verfügung.

## Technische Beschreibung der Anpassungen

Die Implementierung ist in [yaml_manager](yaml_manager) gekapselt. Das Backend
verwendet ausschließlich die Python-Standardbibliothek für HTTP und Dateizugriffe;
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

Weitere Betriebsinformationen stehen in [yaml_manager/DOCS.md](yaml_manager/DOCS.md).
