# Changelog

## 0.6.0 - 2026-06-22

- Lokales Git-Repository im Home-Assistant-Konfigurationsverzeichnis mit automatischer Initialisierung
- Automatische, pfadbegrenzte Commits nach Erstellen, Speichern, Umbenennen, Löschen, Migration und Wiederherstellung
- Git-Checkpoint vor Änderungen, damit auch ein noch nicht eingecheckter Ausgangsstand erhalten bleibt
- Git-Historie für `configuration.yaml` und einzelne Package-Dateien mit Commit-ID, Zeitpunkt, Autor und Nachricht
- Unified Diff zwischen einem ausgewählten Commit und der aktuellen Fassung
- Konfliktgeschützte Wiederherstellung früherer Git-Stände mit zusätzlichem Datei-Backup und Home-Assistant-Prüfung
- Schutz bereits vorgemerkter, fremder Git-Änderungen vor der Aufnahme in App-Commits

## 0.5.0 - 2026-06-22

- Automatische Home-Assistant-Konfigurationsprüfung nach Speichern oder Erstellen von Package-Dateien sowie nach Package-Einbindung, Migration und Wiederherstellung
- Manuell auslösbare Prüfung über `POST /api/config/core/check_config` mit Fehleranzeige und Zeilensprung im Editor
- Versionsverlauf für `configuration.yaml` und Package-Dateien mit Änderungsstatistik und Unified Diff
- Wiederherstellung einzelner Sicherungen mit vorherigem Backup, YAML-Prüfung und Versionskonfliktschutz
- Globale Package-Konfliktprüfung für doppelte Dateinamen, Entity-IDs, Integrationsschlüssel, `unique_id` und Automation-IDs
- Berücksichtigung der Home-Assistant-Merge-Regeln für Listen, Mappings, `!include_dir_named` und `!include_dir_merge_named`

## 0.4.0 - 2026-06-22

- Editor mit Syntaxhervorhebung und Live-Prüfung für `configuration.yaml`
- Ein-Klick-Einbindung von `/config/packages` unter `homeassistant.packages`
- Unterstützung einer über `homeassistant: !include ...` ausgelagerten Core-Konfiguration
- Vorschau-basierte Migration aller auslagerbaren Top-Level-Bereiche in ein Package
- Automatische Anpassung relativer `!include`-Pfade beim Verschieben
- Schutz von `homeassistant:` und `auth_providers` vor einer unsicheren Auslagerung
- Versionskonfliktschutz, atomisches Speichern, Backups und Rollback für Konfigurationsänderungen

## 0.3.0 - 2026-06-21

- Zuverlässig scrollbar gehaltene Scriptliste mit sichtbarer Scrollbar
- Tags für Dateien einschließlich Filterung und Suche
- Kontextbezogene Script-Prüfung mit Qualitätswert und Zeilensprung
- Erkennung doppelter YAML-Schlüssel, Script-IDs und Entitätsreferenzen
- Hinweise für Script-Struktur, IDs, Modus, Alias und Jinja-Klammern
- Sicheres Umbenennen und Verschieben von Dateien innerhalb von `packages`

## 0.2.0

- Statusprüfung für die Einbindung von `/config/packages` in `configuration.yaml`
- Sichtbarer Diagnosehinweis für fehlende und fehlerhafte Konfigurationen
- Unterstützung ausgelagerter `homeassistant`-Konfigurationsdateien

## 0.1.0

- Erste Version des YAML Script Managers
- Kategorien, Suche und responsive Ingress-Oberfläche
- YAML-Editor mit Syntaxhervorhebung und Live-Validierung
- Einfügehilfen für Skriptbausteine, Entitäten und Dienste
- Atomare Schreibvorgänge, Konflikterkennung, Backups und Papierkorb
- Home-Assistant-Dienst zum Neuladen von Skripten
