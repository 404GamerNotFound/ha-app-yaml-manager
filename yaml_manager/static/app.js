"use strict";

const DEFAULT_CATEGORY = "Ohne Kategorie";
const NEW_CATEGORY = "+ Neue Kategorie";
const NEW_TEMPLATE = (scriptId) => `script:
  ${scriptId}:
    alias: Neues Skript
    description: ""
    mode: single
    sequence:
      - action: light.turn_on
        target:
          entity_id: light.beispiel
`;

const snippets = [
  { symbol: "A", name: "Aktion", description: "Dienst mit Ziel", text: "- action: light.turn_on\n  target:\n    entity_id: light.beispiel" },
  { symbol: "IF", name: "Bedingung", description: "Zustand prüfen", text: "- condition: state\n  entity_id: binary_sensor.beispiel\n  state: \"on\"" },
  { symbol: "T", name: "Verzögerung", description: "Ausführung pausieren", text: "- delay:\n    seconds: 5" },
  { symbol: "?", name: "Auswahl", description: "choose / conditions", text: "- choose:\n    - conditions:\n        - condition: state\n          entity_id: input_boolean.beispiel\n          state: \"on\"\n      sequence:\n        - action: light.turn_on\n          target:\n            entity_id: light.beispiel\n  default: []" },
  { symbol: "↻", name: "Wiederholung", description: "repeat mit Anzahl", text: "- repeat:\n    count: 3\n    sequence:\n      - action: light.toggle\n        target:\n          entity_id: light.beispiel" },
  { symbol: "{{", name: "Variable", description: "Jinja-Template", text: "variables:\n  wert: \"{{ states('sensor.beispiel') }}\"" },
  { symbol: "E", name: "Ereignis auslösen", description: "Event mit Daten", text: "- event: eigenes_ereignis\n  event_data:\n    quelle: script" },
];

const state = {
  files: [], categories: [], tags: [], selectedCategory: "Alle", selectedTag: "", selected: null,
  originalContent: "", originalCategory: "", originalTags: [], dirty: false, helpers: null,
  configuration: null, configurationOriginal: "", configurationDirty: false,
  packageConflicts: null,
  history: { scope: "", path: "", currentVersion: "", selectedId: "" },
  gitHistory: { scope: "", path: "", currentVersion: "", selectedCommit: "" },
  dashboard: null,
  dependencies: null,
  branches: null,
  branchPreview: null,
  haObjects: null,
  resource: { path: "", content: "", version: "", dirty: false },
  searchPreview: null,
  importArchive: "",
  importPreview: null,
};

const elements = Object.fromEntries([
  "workspace", "sidebar", "sidebar-toggle", "sidebar-close", "file-search", "configuration-status", "categories", "tags", "file-list", "file-count", "root-path",
  "empty-state", "empty-new-button", "editor-content", "document-name", "document-path", "dirty-dot", "category-select", "tag-input",
  "rename-button", "duplicate-button", "delete-button", "editor", "highlighting", "line-numbers", "validation-status", "file-ha-check", "cursor-status",
  "save-button", "new-button", "reload-button", "helpers", "helpers-toggle", "helpers-close", "snippet-list", "analysis-summary", "analysis-list", "api-notice",
  "dependency-summary", "dependency-list",
  "entity-search", "entity-list", "service-search", "service-list", "new-dialog", "new-form", "new-path", "new-script-id",
  "new-category", "new-tags", "category-options", "create-button", "toast-region",
  "configuration-button", "configuration-dialog", "configuration-close", "configuration-editor", "configuration-highlighting",
  "configuration-line-numbers", "configuration-validation", "configuration-cursor", "configuration-save",
  "configuration-enable-packages", "configuration-migrate", "migration-package-name", "configuration-notice",
  "configuration-check", "configuration-history", "configuration-git-history", "home-assistant-check", "history-button", "git-history-button",
  "history-dialog", "history-close", "history-path", "history-list", "diff-placeholder", "diff-view", "history-summary", "history-restore",
  "git-dialog", "git-history-close", "git-history-path", "git-history-list", "git-diff-placeholder", "git-diff-view", "git-history-summary", "git-history-restore",
  "package-conflicts-button", "conflict-dialog", "conflict-close", "conflict-summary", "conflict-list",
  "dashboard-button", "dashboard-dialog", "dashboard-close", "dashboard-refresh", "quality-score", "quality-stats", "dashboard-findings",
  "remote-status", "remote-badge", "remote-url", "remote-branch", "remote-username", "remote-token", "remote-auto-push", "remote-clear-token", "remote-save", "remote-fetch", "remote-pull", "remote-push", "remote-sync", "remote-remove", "remote-resolution", "remote-merge", "remote-force-push",
  "transfer-button", "transfer-dialog", "transfer-close", "export-scope", "export-category", "export-start", "import-file", "import-strategy", "import-preview", "import-apply", "import-summary", "import-preview-list",
  "objects-button", "objects-dialog", "objects-close", "objects-refresh", "object-search", "object-domain", "objects-summary", "object-list",
  "resource-dialog", "resource-close", "resource-title", "resource-path", "resource-save", "resource-editor", "resource-highlighting", "resource-line-numbers", "resource-validation", "resource-cursor",
  "search-replace-button", "search-replace-dialog", "search-replace-close", "replace-search", "replace-value", "replace-case-sensitive", "replace-preview", "replace-apply", "replace-summary", "replace-file-list",
  "branch-status", "branch-current", "branch-new-name", "branch-create", "branch-select", "branch-switch", "branch-compare", "branch-merge", "branch-summary", "branch-diff",
].map((id) => [id, document.getElementById(id)]));

let validationTimer;
let configurationValidationTimer;
let resourceValidationTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const error = new Error(body.error || `HTTP ${response.status}`);
    error.details = body;
    error.status = response.status;
    throw error;
  }
  return body;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function commentIndex(line) {
  let quote = null;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (quote === '"' && char === "\\") { index += 1; continue; }
    if (char === quote) { quote = null; continue; }
    if (!quote && (char === '"' || char === "'")) { quote = char; continue; }
    if (!quote && char === "#" && (index === 0 || /\s/.test(line[index - 1]))) return index;
  }
  return -1;
}

function highlightLine(line) {
  const split = commentIndex(line);
  const code = split >= 0 ? line.slice(0, split) : line;
  const comment = split >= 0 ? line.slice(split) : "";
  const tokenPattern = /({{.*?}}|{%.*?%}|!(?:include|include_dir_list|include_dir_named|include_dir_merge_list|include_dir_merge_named|secret)\b|"(?:\\.|[^"\\])*"|'(?:''|[^'])*'|\b(?:true|false|null)\b|(?<![\w.])-?\d+(?:\.\d+)?\b|^[\s-]*[A-Za-z_][\w.-]*(?=\s*:))/g;
  let output = "";
  let last = 0;
  for (const match of code.matchAll(tokenPattern)) {
    output += escapeHtml(code.slice(last, match.index));
    const token = match[0];
    let css = "yaml-number";
    if (token.includes("{{") || token.includes("{%")) css = "yaml-template";
    else if (token.trimStart().startsWith("!")) css = "yaml-tag";
    else if (/^[\s-]*[A-Za-z_]/.test(token) && !/^(true|false|null)$/.test(token)) css = "yaml-key";
    else if (token.startsWith('"') || token.startsWith("'")) css = "yaml-string";
    else if (/^(true|false|null)$/.test(token)) css = "yaml-boolean";
    output += `<span class="${css}">${escapeHtml(token)}</span>`;
    last = match.index + token.length;
  }
  output += escapeHtml(code.slice(last));
  if (comment) output += `<span class="yaml-comment">${escapeHtml(comment)}</span>`;
  return output;
}

function updateEditorRendering() {
  const value = elements.editor.value;
  elements.highlighting.firstElementChild.innerHTML = value.split("\n").map(highlightLine).join("\n") + "\n";
  const lines = Math.max(1, value.split("\n").length);
  elements["line-numbers"].textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
  syncScroll();
  updateCursor();
}

function syncScroll() {
  elements.highlighting.scrollTop = elements.editor.scrollTop;
  elements.highlighting.scrollLeft = elements.editor.scrollLeft;
  elements["line-numbers"].scrollTop = elements.editor.scrollTop;
}

function updateCursor() {
  const before = elements.editor.value.slice(0, elements.editor.selectionStart);
  const lines = before.split("\n");
  elements["cursor-status"].textContent = `Zeile ${lines.length}, Spalte ${lines.at(-1).length + 1}`;
}

function setDirty() {
  if (!state.selected) return;
  state.dirty = elements.editor.value !== state.originalContent
    || elements["category-select"].value !== state.originalCategory
    || JSON.stringify(parseTags(elements["tag-input"].value)) !== JSON.stringify(state.originalTags);
  elements["dirty-dot"].classList.toggle("visible", state.dirty);
  elements["save-button"].disabled = !state.dirty;
}

function toast(message, type = "") {
  const item = document.createElement("div");
  item.className = `toast ${type}`;
  item.textContent = message;
  elements["toast-region"].append(item);
  setTimeout(() => item.remove(), 3600);
}

function toastSaveResult(result, successMessage) {
  if (result.gitSync?.enabled && result.gitSync.success === false) {
    toast(result.gitSync.message, "error");
  } else if (result.gitSync?.enabled && !result.gitSync.skipped) {
    toast(`${successMessage} Git-Remote wurde aktualisiert.`, "success");
  } else {
    toast(successMessage, "success");
  }
}

function fileMatches(file) {
  const term = elements["file-search"].value.trim().toLocaleLowerCase("de");
  const inCategory = state.selectedCategory === "Alle" || file.category === state.selectedCategory;
  const hasTag = !state.selectedTag || file.tags.includes(state.selectedTag);
  const haystack = `${file.path} ${file.category} ${file.tags.join(" ")}`.toLocaleLowerCase("de");
  return inCategory && hasTag && (!term || haystack.includes(term));
}

function renderCategories() {
  const categories = ["Alle", ...state.categories];
  elements.categories.replaceChildren(...categories.map((category) => {
    const button = document.createElement("button");
    button.className = `category-item${state.selectedCategory === category ? " active" : ""}`;
    const count = category === "Alle" ? state.files.length : state.files.filter((file) => file.category === category).length;
    button.innerHTML = `<span class="category-dot"></span><span>${escapeHtml(category)}</span><span class="category-count">${count}</span>`;
    button.addEventListener("click", () => { state.selectedCategory = category; renderCategories(); renderFiles(); });
    return button;
  }));
}

function renderTags() {
  const tags = [{ name: "Alle Tags", value: "" }, ...state.tags.map((tag) => ({ name: `#${tag}`, value: tag }))];
  elements.tags.replaceChildren(...tags.map((tag) => {
    const button = document.createElement("button");
    const count = tag.value ? state.files.filter((file) => file.tags.includes(tag.value)).length : state.files.length;
    button.className = `tag-filter${state.selectedTag === tag.value ? " active" : ""}`;
    button.innerHTML = `<span>${escapeHtml(tag.name)}</span><span class="tag-filter-count">${count}</span>`;
    button.addEventListener("click", () => {
      state.selectedTag = tag.value;
      renderTags();
      renderFiles();
    });
    return button;
  }));
}

function renderFiles() {
  const files = state.files.filter(fileMatches);
  elements["file-count"].textContent = files.length;
  if (!files.length) {
    const empty = document.createElement("div");
    empty.className = "list-empty";
    empty.textContent = "Keine passenden YAML-Dateien";
    elements["file-list"].replaceChildren(empty);
    return;
  }
  elements["file-list"].replaceChildren(...files.map((file) => {
    const button = document.createElement("button");
    button.className = `file-item${state.selected?.path === file.path ? " active" : ""}`;
    const tags = file.tags.length ? `<span class="file-tag-line">${escapeHtml(file.tags.map((tag) => `#${tag}`).join(" "))}</span>` : "";
    button.innerHTML = `<span class="file-icon">YML</span><span class="file-label"><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.path)}</span>${tags}</span>`;
    button.title = file.path;
    button.addEventListener("click", () => openFile(file.path));
    return button;
  }));
}

function parseTags(value) {
  const source = Array.isArray(value) ? value : String(value || "").split(",");
  const result = [];
  const seen = new Set();
  source.forEach((item) => {
    const tag = String(item).trim().replace(/\s+/g, " ").slice(0, 40);
    const folded = tag.toLocaleLowerCase("de");
    if (tag && !seen.has(folded) && result.length < 12) {
      result.push(tag);
      seen.add(folded);
    }
  });
  return result;
}

function fillCategories(selected = DEFAULT_CATEGORY) {
  const categories = [...new Set([...state.categories, selected])];
  elements["category-select"].replaceChildren(...categories.map((category) => new Option(category, category)), new Option(NEW_CATEGORY, NEW_CATEGORY));
  elements["category-select"].value = selected;
  elements["category-options"].replaceChildren(...state.categories.filter((category) => category !== DEFAULT_CATEGORY).map((category) => new Option(category)));
}

function renderConfigurationStatus(configuration) {
  const status = configuration || {
    status: "unavailable", configured: false, message: "Prüfstatus ist nicht verfügbar.", expected: "",
  };
  const labels = {
    configured: ["✓", "Packages korrekt eingebunden"],
    missing: ["!", "Packages nicht eingebunden"],
    invalid: ["×", "Konfiguration fehlerhaft"],
    unavailable: ["×", "Konfiguration nicht gefunden"],
  };
  const [icon, label] = labels[status.status] || labels.unavailable;
  elements["configuration-status"].className = `configuration-status ${status.status}`;
  elements["configuration-status"].innerHTML = `<span class="configuration-status-icon" aria-hidden="true">${icon}</span><span><strong>Packages-Einbindung</strong><small>${escapeHtml(label)}</small></span>`;
  elements["configuration-status"].dataset.message = status.message || label;
  elements["configuration-status"].dataset.expected = status.configured ? "" : status.expected || "";
  elements["configuration-status"].title = status.message || label;
}

function syncConfigurationScroll() {
  elements["configuration-highlighting"].scrollTop = elements["configuration-editor"].scrollTop;
  elements["configuration-highlighting"].scrollLeft = elements["configuration-editor"].scrollLeft;
  elements["configuration-line-numbers"].scrollTop = elements["configuration-editor"].scrollTop;
}

function updateConfigurationCursor() {
  const before = elements["configuration-editor"].value.slice(0, elements["configuration-editor"].selectionStart);
  const lines = before.split("\n");
  elements["configuration-cursor"].textContent = `Zeile ${lines.length}, Spalte ${lines.at(-1).length + 1}`;
}

function updateConfigurationRendering() {
  const value = elements["configuration-editor"].value;
  elements["configuration-highlighting"].firstElementChild.innerHTML = value.split("\n").map(highlightLine).join("\n") + "\n";
  const lines = Math.max(1, value.split("\n").length);
  elements["configuration-line-numbers"].textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
  syncConfigurationScroll();
  updateConfigurationCursor();
}

function setConfigurationNotice(message, type = "") {
  elements["configuration-notice"].className = `configuration-notice ${type}`;
  elements["configuration-notice"].textContent = message;
}

function setConfigurationDirty() {
  state.configurationDirty = elements["configuration-editor"].value !== state.configurationOriginal;
  elements["configuration-save"].disabled = !state.configurationDirty;
}

function renderHomeAssistantCheck(check = null) {
  const result = check || {
    status: "unavailable", message: "Noch nicht ausgeführt", valid: null,
  };
  const css = result.status === "valid" ? "valid" : result.status === "invalid" ? "invalid" : "unavailable";
  const icon = css === "valid" ? "✓" : css === "invalid" ? "×" : "?";
  elements["home-assistant-check"].className = `home-assistant-check ${css}`;
  elements["home-assistant-check"].innerHTML = `<span class="check-indicator" aria-hidden="true">${icon}</span><span><strong>Home-Assistant-Prüfung</strong><small>${escapeHtml(result.message || "Kein Ergebnis")}</small></span>`;
  const source = result.source || "";
  const canJump = !source || source === "/config/configuration.yaml";
  elements["home-assistant-check"].dataset.line = canJump ? result.line || "" : "";
  elements["home-assistant-check"].dataset.source = source;
  elements["home-assistant-check"].title = result.message || "";
}

function renderFileHomeAssistantCheck(check = null) {
  const button = elements["file-ha-check"];
  if (!check) {
    button.className = "file-ha-check hidden";
    button.dataset.line = "";
    button.dataset.source = "";
    return;
  }
  const css = check.valid === true ? "valid" : check.valid === false ? "invalid" : "unavailable";
  const label = check.valid === true ? "✓ HA-Konfiguration gültig" : check.valid === false ? `HA-Fehler: ${check.message}` : "HA-Prüfung nicht verfügbar";
  const currentSource = state.selected ? `/config/packages/${state.selected.path}` : "";
  button.className = `file-ha-check ${css}`;
  button.textContent = label;
  button.title = check.message || label;
  button.dataset.source = check.source || "";
  button.dataset.line = check.source === currentSource ? check.line || "" : "";
}

function showConfigurationActionResult(result, successMessage) {
  const check = result.configurationCheck;
  if (check?.valid === false) {
    setConfigurationNotice(`${successMessage} Home Assistant meldet: ${check.message}`, "error");
    return;
  }
  if (check?.valid === true) {
    setConfigurationNotice(`${successMessage} Home Assistant bestätigt die Konfiguration.`, "success");
    return;
  }
  setConfigurationNotice(`${successMessage} Die Home-Assistant-Prüfung war nicht verfügbar.`, "warning");
}

function applyConfigurationResult(result) {
  state.configuration = result;
  state.configurationOriginal = result.content;
  state.configurationDirty = false;
  elements["configuration-editor"].value = result.content;
  elements["configuration-save"].disabled = true;
  updateConfigurationRendering();
  if (result.packages) renderConfigurationStatus(result.packages);
  scheduleConfigurationValidation();
  renderHomeAssistantCheck(result.configurationCheck || null);
}

async function openConfigurationEditor() {
  try {
    const result = await api("api/configuration");
    applyConfigurationResult(result);
    setConfigurationNotice("Der Bereich homeassistant: bleibt aus Sicherheitsgründen in der Hauptdatei.");
    elements["configuration-dialog"].showModal();
    setTimeout(() => elements["configuration-editor"].focus(), 0);
  } catch (error) { toast(error.message, "error"); }
}

function closeConfigurationEditor() {
  if (state.configurationDirty && !confirm("Ungespeicherte Änderungen an configuration.yaml verwerfen?")) return;
  elements["configuration-dialog"].close();
}

function showConfigurationValidation(result) {
  const button = elements["configuration-validation"];
  button.className = `validation-status ${result.valid ? "valid" : "invalid"}`;
  button.textContent = result.valid ? "✓ YAML gültig" : `Fehler: ${result.message}${result.line ? ` (${result.line}:${result.column})` : ""}`;
  button.dataset.line = result.line || "";
  button.title = button.textContent;
}

function jumpToConfigurationLine(rawLine) {
  const target = Number(rawLine);
  if (!target) return;
  const editor = elements["configuration-editor"];
  const lines = editor.value.split("\n");
  const offset = lines.slice(0, target - 1).reduce((sum, line) => sum + line.length + 1, 0);
  editor.focus();
  editor.setSelectionRange(offset, offset + (lines[target - 1]?.length || 0));
  editor.scrollTop = Math.max(0, (target - 4) * 21.45);
  syncConfigurationScroll();
}

function jumpToConfigurationError() {
  jumpToConfigurationLine(elements["configuration-validation"].dataset.line);
}

function scheduleConfigurationValidation() {
  clearTimeout(configurationValidationTimer);
  elements["configuration-validation"].className = "validation-status neutral";
  elements["configuration-validation"].textContent = "Prüfe …";
  configurationValidationTimer = setTimeout(async () => {
    try {
      const result = await api("api/validate", {
        method: "POST",
        body: JSON.stringify({ content: elements["configuration-editor"].value }),
      });
      showConfigurationValidation(result);
    } catch (error) { toast(error.message, "error"); }
  }, 350);
}

async function saveConfiguration() {
  if (!state.configuration || !state.configurationDirty) return;
  elements["configuration-save"].disabled = true;
  try {
    const result = await api("api/configuration", {
      method: "PUT",
      body: JSON.stringify({
        content: elements["configuration-editor"].value,
        version: state.configuration.version,
      }),
    });
    applyConfigurationResult(result);
    await refreshFiles();
    showConfigurationActionResult(result, "configuration.yaml wurde gespeichert und gesichert.");
    toastSaveResult(result, "configuration.yaml gespeichert.");
  } catch (error) {
    elements["configuration-save"].disabled = false;
    if (error.details?.line) showConfigurationValidation(error.details);
    setConfigurationNotice(error.message, "error");
    toast(error.message, "error");
  }
}

async function runHomeAssistantCheck() {
  elements["configuration-check"].disabled = true;
  try {
    const result = await api("api/configuration/check", { method: "POST", body: "{}" });
    renderHomeAssistantCheck(result);
    setConfigurationNotice(
      result.valid === true ? "Home Assistant bestätigt die Konfiguration." : result.message,
      result.valid === true ? "success" : result.valid === false ? "error" : "warning",
    );
  } catch (error) {
    setConfigurationNotice(error.message, "error");
    toast(error.message, "error");
  } finally {
    elements["configuration-check"].disabled = false;
  }
}

async function enablePackagesInConfiguration() {
  if (!state.configuration) return null;
  try {
    const result = await api("api/configuration/enable-packages", {
      method: "POST",
      body: JSON.stringify({
        content: elements["configuration-editor"].value,
        version: state.configuration.version,
      }),
    });
    applyConfigurationResult(result);
    await refreshFiles();
    showConfigurationActionResult(result, result.message);
    toast(result.message, "success");
    return result;
  } catch (error) {
    setConfigurationNotice(error.message, "error");
    toast(error.message, "error");
    return null;
  }
}

async function migrateConfiguration() {
  if (!state.configuration) return;
  const packageName = elements["migration-package-name"].value.trim();
  if (!/^[a-z0-9_]+$/.test(packageName)) {
    setConfigurationNotice("Der Package-Name darf nur Kleinbuchstaben, Ziffern und Unterstriche enthalten.", "error");
    return;
  }
  try {
    const preview = await api("api/configuration/migration-preview", {
      method: "POST",
      body: JSON.stringify({
        content: elements["configuration-editor"].value,
        packageName,
      }),
    });
    if (preview.targetExists) {
      throw new Error(`${preview.target} existiert bereits. Es wurde nichts verändert.`);
    }
    const componentList = preview.components.join(", ");
    const confirmed = confirm(
      `${preview.componentCount} Bereiche werden nach ${preview.target} verschoben:\n\n${componentList}\n\nDer homeassistant:-Block bleibt erhalten. Fortfahren?`,
    );
    if (!confirmed) return;

    const enabled = await enablePackagesInConfiguration();
    if (!enabled) return;
    const result = await api("api/configuration/migrate", {
      method: "POST",
      body: JSON.stringify({
        content: enabled.content,
        version: enabled.version,
        packageName,
      }),
    });
    applyConfigurationResult(result);
    await refreshFiles();
    showConfigurationActionResult(result, result.message);
    toast(result.message, "success");
  } catch (error) {
    setConfigurationNotice(error.message, "error");
    toast(error.message, "error");
  }
}

function historyQuery(path, extra = {}) {
  const params = new URLSearchParams({ scope: state.history.scope, path: path || "", ...extra });
  return params.toString();
}

async function selectHistoryEntry(entry, button) {
  document.querySelectorAll(".history-entry").forEach((item) => item.classList.toggle("active", item === button));
  state.history.selectedId = entry.id;
  elements["history-restore"].disabled = false;
  elements["history-summary"].textContent = `${entry.created.replace("T", " ")} · +${entry.additions} / -${entry.deletions}`;
  try {
    const result = await api(`api/backup/diff?${historyQuery(state.history.path, { id: entry.id })}`);
    const lines = result.diff ? result.diff.split("\n") : ["Keine Unterschiede zur aktuellen Fassung."];
    elements["diff-view"].innerHTML = lines.map((line) => {
      let css = "";
      if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) css = "header";
      else if (line.startsWith("+")) css = "added";
      else if (line.startsWith("-")) css = "removed";
      return `<span class="diff-line ${css}">${escapeHtml(line)}</span>`;
    }).join("");
    elements["diff-placeholder"].classList.add("hidden");
    elements["diff-view"].classList.remove("hidden");
    if (result.truncated) toast("Der Diff wurde nach 1.200 Zeilen gekürzt.");
  } catch (error) { toast(error.message, "error"); }
}

function renderHistory(history) {
  elements["history-path"].textContent = history.path;
  state.history.currentVersion = history.currentVersion;
  state.history.selectedId = "";
  elements["history-restore"].disabled = true;
  elements["history-summary"].textContent = `${history.entries.length} gespeicherte Versionen`;
  elements["diff-view"].classList.add("hidden");
  elements["diff-placeholder"].classList.remove("hidden");
  elements["diff-placeholder"].textContent = "Wähle links eine Version für den Vergleich.";
  if (!history.entries.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Noch keine Sicherungen für diese Datei.";
    elements["history-list"].replaceChildren(empty);
    return;
  }
  elements["history-list"].replaceChildren(...history.entries.map((entry) => {
    const button = document.createElement("button");
    button.className = "history-entry";
    button.innerHTML = `<strong>${escapeHtml(entry.created.replace("T", " "))}</strong><small>+${entry.additions} / -${entry.deletions} · ${entry.size} Bytes</small>`;
    button.addEventListener("click", () => selectHistoryEntry(entry, button));
    return button;
  }));
}

async function openHistory(scope) {
  if (scope === "package" && !state.selected) return;
  state.history.scope = scope;
  state.history.path = scope === "package" ? state.selected.path : "";
  try {
    const history = await api(`api/backups?${historyQuery(state.history.path)}`);
    renderHistory(history);
    elements["history-dialog"].showModal();
  } catch (error) { toast(error.message, "error"); }
}

async function restoreSelectedBackup() {
  if (!state.history.selectedId) return;
  if ((state.history.scope === "configuration" && state.configurationDirty) || (state.history.scope === "package" && state.dirty)) {
    toast("Speichere oder verwirf zuerst die aktuellen Änderungen.", "error");
    return;
  }
  if (!confirm(`Backup ${state.history.selectedId} wirklich wiederherstellen? Die aktuelle Fassung wird zuvor gesichert.`)) return;
  try {
    const result = await api("api/backup/restore", {
      method: "POST",
      body: JSON.stringify({
        scope: state.history.scope,
        path: state.history.path,
        id: state.history.selectedId,
        version: state.history.currentVersion,
      }),
    });
    elements["history-dialog"].close();
    if (state.history.scope === "configuration") {
      applyConfigurationResult(result);
      await refreshFiles();
      showConfigurationActionResult(result, result.message);
    } else {
      await refreshFiles();
      await openFile(result.path, true);
      renderFileHomeAssistantCheck(result.configurationCheck);
    }
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

function gitHistoryQuery(extra = {}) {
  const params = new URLSearchParams({
    scope: state.gitHistory.scope,
    path: state.gitHistory.path || "",
    ...extra,
  });
  return params.toString();
}

function renderGitDiff(result) {
  const lines = result.diff ? result.diff.split("\n") : ["Keine Unterschiede zur aktuellen Fassung."];
  elements["git-diff-view"].innerHTML = lines.map((line) => {
    let css = "";
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) css = "header";
    else if (line.startsWith("+")) css = "added";
    else if (line.startsWith("-")) css = "removed";
    return `<span class="diff-line ${css}">${escapeHtml(line)}</span>`;
  }).join("");
  elements["git-diff-placeholder"].classList.add("hidden");
  elements["git-diff-view"].classList.remove("hidden");
  if (result.truncated) toast("Der Git-Diff wurde nach 1.200 Zeilen gekürzt.");
}

async function selectGitHistoryEntry(entry, button) {
  elements["git-history-list"].querySelectorAll(".history-entry").forEach((item) => {
    item.classList.toggle("active", item === button);
  });
  state.gitHistory.selectedCommit = entry.id;
  elements["git-history-restore"].disabled = false;
  elements["git-history-summary"].textContent = `${entry.shortId} · ${entry.subject}`;
  try {
    const result = await api(`api/git/diff?${gitHistoryQuery({ commit: entry.id })}`);
    renderGitDiff(result);
  } catch (error) { toast(error.message, "error"); }
}

function renderGitHistory(history) {
  elements["git-history-path"].textContent = history.path;
  state.gitHistory.currentVersion = history.currentVersion;
  state.gitHistory.selectedCommit = "";
  elements["git-history-restore"].disabled = true;
  elements["git-diff-view"].classList.add("hidden");
  elements["git-diff-placeholder"].classList.remove("hidden");
  elements["git-diff-placeholder"].textContent = "Wähle links einen Commit für den Vergleich.";
  elements["git-history-summary"].textContent = history.available
    ? `${history.entries.length} Git-Commits`
    : history.message || "Git ist nicht verfügbar.";
  if (!history.entries.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = history.available ? "Noch keine Git-Commits für diese Datei." : history.message;
    elements["git-history-list"].replaceChildren(empty);
    return;
  }
  elements["git-history-list"].replaceChildren(...history.entries.map((entry) => {
    const button = document.createElement("button");
    button.className = "history-entry";
    const created = entry.created.replace("T", " ").slice(0, 19);
    button.innerHTML = `<strong>${escapeHtml(entry.subject)}</strong><small>${escapeHtml(created)} · ${escapeHtml(entry.shortId)} · ${escapeHtml(entry.author)}</small>`;
    button.addEventListener("click", () => selectGitHistoryEntry(entry, button));
    return button;
  }));
}

async function openGitHistory(scope) {
  if (scope === "package" && !state.selected) return;
  state.gitHistory.scope = scope;
  state.gitHistory.path = scope === "package" ? state.selected.path : "";
  try {
    const history = await api(`api/git/history?${gitHistoryQuery()}`);
    renderGitHistory(history);
    elements["git-dialog"].showModal();
  } catch (error) { toast(error.message, "error"); }
}

async function restoreSelectedGitCommit() {
  if (!state.gitHistory.selectedCommit) return;
  if ((state.gitHistory.scope === "configuration" && state.configurationDirty) || (state.gitHistory.scope === "package" && state.dirty)) {
    toast("Speichere oder verwirf zuerst die aktuellen Änderungen.", "error");
    return;
  }
  const shortCommit = state.gitHistory.selectedCommit.slice(0, 8);
  if (!confirm(`Auf Git-Stand ${shortCommit} zurückgehen? Die aktuelle Fassung wird vorher als Backup und Git-Commit gesichert.`)) return;
  try {
    const result = await api("api/git/restore", {
      method: "POST",
      body: JSON.stringify({
        scope: state.gitHistory.scope,
        path: state.gitHistory.path,
        commit: state.gitHistory.selectedCommit,
        version: state.gitHistory.currentVersion,
      }),
    });
    elements["git-dialog"].close();
    if (state.gitHistory.scope === "configuration") {
      applyConfigurationResult(result);
      await refreshFiles();
      showConfigurationActionResult(result, result.message);
    } else {
      await refreshFiles();
      await openFile(result.path, true);
      renderFileHomeAssistantCheck(result.configurationCheck);
    }
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderPackageConflicts(result) {
  state.packageConflicts = result;
  const errors = result.counts?.error || 0;
  const warnings = result.counts?.warning || 0;
  const css = errors ? "invalid" : warnings ? "missing" : "configured";
  const icon = errors ? "×" : warnings ? "!" : "✓";
  const label = errors ? `${errors} Konflikte` : warnings ? `${warnings} Warnungen` : "Keine Konflikte";
  elements["package-conflicts-button"].className = `configuration-status ${css}`;
  elements["package-conflicts-button"].innerHTML = `<span class="configuration-status-icon" aria-hidden="true">${icon}</span><span><strong>Package-Konflikte</strong><small>${label}</small></span>`;
  elements["conflict-summary"].textContent = `${result.fileCount} Dateien geprüft · ${errors} Fehler · ${warnings} Warnungen · Modus: ${result.mode}`;
  if (!result.findings.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Keine Konflikte nach den geprüften Package-Merge-Regeln gefunden.";
    elements["conflict-list"].replaceChildren(empty);
    return;
  }
  elements["conflict-list"].replaceChildren(...result.findings.map((finding) => {
    const item = document.createElement("div");
    item.className = `conflict-item ${finding.severity}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title)}</strong><small>${escapeHtml(finding.message)}</small><small class="conflict-files">${escapeHtml((finding.files || []).join(" · "))}</small></div>`;
    return item;
  }));
}

async function loadPackageConflicts() {
  const result = await api("api/package-conflicts");
  renderPackageConflicts(result);
  return result;
}

async function openPackageConflicts() {
  try {
    await loadPackageConflicts();
    elements["conflict-dialog"].showModal();
  } catch (error) { toast(error.message, "error"); }
}

function renderRemoteStatus(remote) {
  const configured = remote.configured;
  elements["remote-url"].value = remote.url || "";
  elements["remote-branch"].value = remote.branch || "main";
  elements["remote-username"].value = remote.username || "";
  elements["remote-token"].value = "";
  elements["remote-token"].placeholder = remote.tokenConfigured ? "Token ist gespeichert" : "Personal Access Token";
  elements["remote-clear-token"].checked = false;
  elements["remote-auto-push"].checked = remote.autoPush !== false;
  const syncDetails = configured
    ? `${remote.ahead || 0} voraus · ${remote.behind || 0} zurück${remote.dirty ? " · lokale Änderungen" : ""}`
    : "Noch nicht konfiguriert";
  elements["remote-status"].textContent = remote.message || syncDetails;
  elements["remote-badge"].textContent = configured ? `${(remote.provider || "git").toUpperCase()} · ${remote.branch}` : "Lokal";
  elements["remote-resolution"].classList.toggle("hidden", !remote.diverged);
  ["remote-fetch", "remote-pull", "remote-push", "remote-sync", "remote-remove", "remote-merge", "remote-force-push"].forEach((id) => {
    elements[id].disabled = !configured;
  });
}

function renderDashboard(result) {
  state.dashboard = result;
  const scoreClass = result.score < 60 ? "error" : result.score < 85 ? "warning" : "";
  elements["quality-score"].className = `quality-score ${scoreClass}`;
  elements["quality-score"].innerHTML = `<strong>${result.score}</strong><span>Qualität</span>`;
  const stats = [
    [result.summary.files, "Package-Dateien"],
    [result.summary.scripts, "Scripts"],
    [result.summary.unusedScripts, "Möglicherweise ungenutzt"],
    [result.summary.errors, "Fehler"],
    [result.summary.warnings, "Warnungen"],
    [result.summary.backups, "Backups"],
  ];
  elements["quality-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${value}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  if (!result.findings.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Keine Qualitätsprobleme gefunden.";
    elements["dashboard-findings"].replaceChildren(empty);
  } else {
    elements["dashboard-findings"].replaceChildren(...result.findings.map((finding) => {
      const item = document.createElement("div");
      item.className = `dashboard-finding ${finding.severity}`;
      item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title)}</strong><small>${escapeHtml(finding.message)}</small><small>${escapeHtml((finding.files || []).join(" · "))}</small></div>`;
      return item;
    }));
  }
  renderRemoteStatus(result.git.remote);
}

async function loadDashboard() {
  elements["dashboard-refresh"].disabled = true;
  try {
    const result = await api("api/dashboard");
    renderDashboard(result);
    return result;
  } catch (error) {
    toast(error.message, "error");
    return null;
  } finally {
    elements["dashboard-refresh"].disabled = false;
  }
}

async function openDashboard() {
  elements["objects-dialog"].classList.add("hidden");
  elements["dashboard-dialog"].classList.remove("hidden");
  elements["dashboard-button"].classList.add("active");
  elements["objects-button"].classList.remove("active");
  await Promise.all([loadDashboard(), loadBranches()]);
}

function openScriptManager() {
  elements["dashboard-dialog"].classList.add("hidden");
  elements["objects-dialog"].classList.add("hidden");
  elements["dashboard-button"].classList.remove("active");
  elements["objects-button"].classList.remove("active");
}

function renderBranches(result) {
  state.branches = result;
  elements["branch-current"].textContent = result.current || "Nicht verfügbar";
  elements["branch-status"].textContent = result.available
    ? `${result.branches.length} lokale Branches · aktiv: ${result.current}`
    : result.message || "Git ist nicht verfügbar.";
  const previous = elements["branch-select"].value;
  const selectable = (result.branches || []).filter((branch) => !branch.current);
  elements["branch-select"].replaceChildren(...selectable.map((branch) => {
    const option = document.createElement("option");
    option.value = branch.name;
    option.textContent = `${branch.name} · ${branch.shortCommit}`;
    return option;
  }));
  if (selectable.some((branch) => branch.name === previous)) elements["branch-select"].value = previous;
  const disabled = !result.available || !selectable.length;
  elements["branch-select"].disabled = disabled;
  elements["branch-switch"].disabled = disabled;
  elements["branch-compare"].disabled = disabled;
}

async function loadBranches() {
  const result = await api("api/git/branches");
  renderBranches(result);
  return result;
}

async function createBranch() {
  if (state.dirty || state.configurationDirty || state.resource.dirty) {
    toast("Speichere zuerst alle geöffneten Änderungen.", "error");
    return;
  }
  const branch = elements["branch-new-name"].value.trim();
  if (!branch) return;
  try {
    const result = await api("api/git/branches/create", {
      method: "POST", body: JSON.stringify({ branch }),
    });
    elements["branch-new-name"].value = "";
    state.branchPreview = null;
    elements["branch-merge"].disabled = true;
    renderBranches(result);
    await refreshFiles();
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function switchBranch() {
  if (state.dirty || state.configurationDirty || state.resource.dirty) {
    toast("Speichere zuerst alle geöffneten Änderungen.", "error");
    return;
  }
  const branch = elements["branch-select"].value;
  if (!branch || !confirm(`Zum Branch ${branch} wechseln?`)) return;
  try {
    const result = await api("api/git/branches/switch", {
      method: "POST", body: JSON.stringify({ branch }),
    });
    state.branchPreview = null;
    elements["branch-merge"].disabled = true;
    elements["branch-diff"].classList.add("hidden");
    renderBranches(result);
    await refreshFiles();
    if (state.selected) await openFile(state.selected.path, true);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function compareBranch() {
  const branch = elements["branch-select"].value;
  if (!branch) return;
  try {
    const preview = await api("api/git/branches/compare", {
      method: "POST", body: JSON.stringify({ branch }),
    });
    state.branchPreview = preview;
    elements["branch-summary"].textContent = `${preview.files.length} Dateien · ${preview.ahead} nur lokal · ${preview.behind} nur in ${branch}${preview.truncated ? " · Diff gekürzt" : ""}`;
    elements["branch-diff"].textContent = preview.diff || preview.stat || "Keine verwalteten YAML-Unterschiede.";
    elements["branch-diff"].classList.remove("hidden");
    elements["branch-merge"].disabled = preview.behind === 0;
  } catch (error) { toast(error.message, "error"); }
}

async function mergeBranch() {
  if (state.dirty || state.configurationDirty || state.resource.dirty) {
    toast("Speichere zuerst alle geöffneten Änderungen.", "error");
    return;
  }
  const preview = state.branchPreview;
  if (!preview || !confirm(`Branch ${preview.branch} in ${preview.current} zusammenführen?`)) return;
  elements["branch-merge"].disabled = true;
  try {
    const result = await api("api/git/branches/merge", {
      method: "POST",
      body: JSON.stringify({ branch: preview.branch, stateVersion: preview.stateVersion }),
    });
    state.branchPreview = null;
    renderBranches(result);
    elements["branch-summary"].textContent = result.message;
    elements["branch-diff"].classList.add("hidden");
    await refreshFiles();
    if (state.selected) await openFile(state.selected.path, true);
    toast(result.message, "success");
  } catch (error) {
    elements["branch-merge"].disabled = false;
    toast(error.message, "error");
  }
}

async function saveRemoteConfiguration() {
  elements["remote-save"].disabled = true;
  try {
    const remote = await api("api/git/remote", {
      method: "PUT",
      body: JSON.stringify({
        url: elements["remote-url"].value,
        branch: elements["remote-branch"].value,
        username: elements["remote-username"].value,
        token: elements["remote-token"].value,
        clearToken: elements["remote-clear-token"].checked,
        autoPush: elements["remote-auto-push"].checked,
      }),
    });
    renderRemoteStatus(remote);
    toast("Git Remote gespeichert", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { elements["remote-save"].disabled = false; }
}

async function synchronizeRemote(action) {
  if (state.dirty || state.configurationDirty) {
    toast("Speichere oder verwirf zuerst die offenen Änderungen.", "error");
    return;
  }
  const descriptions = {
    fetch: "Remote-Status abrufen?",
    pull: "Remote-Änderungen übernehmen? Verwaltete Dateien können aktualisiert werden.",
    push: "Lokale Git-Historie an das Remote übertragen? Das Repository sollte privat sein.",
    sync: "Sicher synchronisieren? Dabei können verwaltete Dateien empfangen und sensible Konfigurationsdaten übertragen werden.",
    merge: "Lokale und Remote-Historie verbinden und das Ergebnis pushen? Remote-README- und Lizenzdateien bleiben erhalten.",
    "force-push": "Remote-Historie wirklich durch den lokalen Stand ersetzen? Vorhandene Remote-Commits gehen dabei verloren.",
  };
  if (!confirm(descriptions[action])) return;
  const button = elements[`remote-${action}`];
  button.disabled = true;
  try {
    const result = await api("api/git/remote/sync", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    renderRemoteStatus(result);
    await refreshFiles();
    if (result.configurationCheck?.valid === false) {
      toast(`Synchronisiert, aber Home Assistant meldet: ${result.configurationCheck.message}`, "error");
    } else {
      toast(result.message, "success");
    }
  } catch (error) {
    if (error.details?.resolutionOptions) {
      elements["remote-resolution"].classList.remove("hidden");
      elements["remote-status"].textContent = `${error.message} ${error.details.ahead} voraus · ${error.details.behind} zurück`;
    }
    toast(error.message, "error");
  }
  finally { button.disabled = false; }
}

async function removeRemoteConfiguration() {
  if (!confirm("Git Remote und das gespeicherte Token aus der App entfernen? Das lokale Repository bleibt erhalten.")) return;
  try {
    const result = await api("api/git/remote", { method: "DELETE", body: "{}" });
    renderRemoteStatus(result);
    toast("Git Remote entfernt", "success");
  } catch (error) { toast(error.message, "error"); }
}

function fillExportCategories() {
  elements["export-category"].replaceChildren(...state.categories.map((category) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    return option;
  }));
  elements["export-category"].disabled = elements["export-scope"].value !== "category";
}

function resetImportPreview() {
  state.importArchive = "";
  state.importPreview = null;
  elements["import-apply"].disabled = true;
  elements["import-summary"].className = "import-summary";
  elements["import-summary"].textContent = "Noch kein Archiv geprüft.";
  elements["import-preview-list"].replaceChildren();
}

function openTransferDialog() {
  fillExportCategories();
  elements["import-file"].value = "";
  resetImportPreview();
  elements["transfer-dialog"].showModal();
}

function startPackageExport() {
  const scope = elements["export-scope"].value;
  if (scope === "file" && !state.selected) {
    toast("Öffne zuerst eine Package-Datei.", "error");
    return;
  }
  const params = new URLSearchParams({
    scope,
    path: scope === "file" ? state.selected.path : "",
    category: scope === "category" ? elements["export-category"].value : "",
  });
  const link = document.createElement("a");
  link.href = `api/export?${params}`;
  link.click();
}

function readArchive(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result).split(",", 2)[1] || ""));
    reader.addEventListener("error", () => reject(new Error("Das ZIP-Archiv konnte nicht gelesen werden.")));
    reader.readAsDataURL(file);
  });
}

function renderImportPreview(result) {
  state.importPreview = result;
  const conflictErrors = result.conflicts.counts?.error || 0;
  const conflictWarnings = result.conflicts.counts?.warning || 0;
  elements["import-summary"].className = `import-summary ${result.valid ? "valid" : "invalid"}`;
  elements["import-summary"].textContent = result.valid
    ? `${result.files.length} Dateien geprüft · ${result.existingCount} vorhanden · ${conflictErrors} Konflikte · ${conflictWarnings} Warnungen`
    : result.errors.join(" · ");
  const fileItems = result.files.map((file) => {
    const item = document.createElement("div");
    item.className = "import-preview-item";
    item.innerHTML = `<span>${escapeHtml(file.path)}</span><span>${file.exists ? "vorhanden" : "neu"} · ${file.size} Bytes</span>`;
    return item;
  });
  const conflictItems = result.conflicts.findings.slice(0, 30).map((finding) => {
    const item = document.createElement("div");
    item.className = "import-preview-item";
    item.innerHTML = `<span>${escapeHtml(finding.title)}</span><span>${escapeHtml(finding.severity)}</span>`;
    return item;
  });
  elements["import-preview-list"].replaceChildren(...fileItems, ...conflictItems);
  elements["import-apply"].disabled = !result.valid;
}

async function previewPackageImport() {
  const file = elements["import-file"].files[0];
  if (!file) {
    toast("Wähle zuerst ein ZIP-Archiv.", "error");
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    toast("Das ZIP-Archiv ist größer als 10 MiB.", "error");
    return;
  }
  elements["import-preview"].disabled = true;
  try {
    state.importArchive = await readArchive(file);
    const result = await api("api/import/preview", {
      method: "POST",
      body: JSON.stringify({ archive: state.importArchive }),
    });
    renderImportPreview(result);
  } catch (error) { toast(error.message, "error"); }
  finally { elements["import-preview"].disabled = false; }
}

async function applyPackageImport() {
  if (!state.importPreview?.valid || !state.importArchive) return;
  const errors = state.importPreview.conflicts.counts?.error || 0;
  const warning = errors ? ` Die Vorschau enthält ${errors} Package-Konflikte.` : "";
  if (!confirm(`Geprüften ZIP-Import anwenden?${warning} Bestehende Dateien werden gemäß Strategie behandelt.`)) return;
  elements["import-apply"].disabled = true;
  try {
    const result = await api("api/import/apply", {
      method: "POST",
      body: JSON.stringify({
        archive: state.importArchive,
        strategy: elements["import-strategy"].value,
        archiveVersion: state.importPreview.archiveVersion,
        destinationVersion: state.importPreview.destinationVersion,
      }),
    });
    await refreshFiles();
    elements["import-summary"].className = "import-summary valid";
    elements["import-summary"].textContent = `${result.message} ${result.skipped.length} Dateien wurden übersprungen.`;
    toast(result.message, "success");
  } catch (error) {
    elements["import-apply"].disabled = false;
    toast(error.message, "error");
  }
}

function renderHaObjects() {
  const result = state.haObjects;
  if (!result) return;
  const term = elements["object-search"].value.trim().toLocaleLowerCase("de");
  const domain = elements["object-domain"].value;
  const visible = result.objects.filter((item) => {
    const haystack = `${item.alias} ${item.id} ${item.entityId} ${item.path}`.toLocaleLowerCase("de");
    return (!domain || item.domain === domain) && (!term || haystack.includes(term));
  });
  const labels = { automation: "Automation", script: "Script", scene: "Szene" };
  elements["objects-summary"].className = `import-summary ${result.invalidFiles.length ? "invalid" : "valid"}`;
  elements["objects-summary"].textContent = `${result.summary.automation} Automationen · ${result.summary.script} Scripts · ${result.summary.scene} Szenen · ${result.summary.references} Bezüge`;
  elements["object-list"].replaceChildren(...visible.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "object-item";
    const outgoing = result.references.filter((reference) => reference.sourceObject === item.key);
    const targets = outgoing.slice(0, 4).map((reference) => reference.target).join(" · ");
    button.innerHTML = `<span class="object-primary"><span class="object-item-header"><strong>${escapeHtml(item.alias)}</strong><span class="object-kind">${labels[item.domain]}</span></span><small>${escapeHtml(item.entityId)}</small></span><span class="object-location"><strong>${escapeHtml(item.path)}</strong><small>Zeile ${item.line}</small></span><span class="object-references">${targets ? escapeHtml(targets) : "Keine erkannten Bezüge"}</span><span class="object-counts">${item.incoming} eingehend · ${item.outgoing} ausgehend</span>`;
    button.addEventListener("click", () => openHaObject(item));
    return button;
  }));
}

async function loadHaObjects() {
  elements["objects-summary"].className = "import-summary";
  elements["objects-summary"].textContent = "Home-Assistant-Objekte werden analysiert …";
  state.haObjects = await api("api/ha-objects");
  renderHaObjects();
}

async function openObjectsDialog() {
  elements["dashboard-dialog"].classList.add("hidden");
  elements["objects-dialog"].classList.remove("hidden");
  elements["dashboard-button"].classList.remove("active");
  elements["objects-button"].classList.add("active");
  try { await loadHaObjects(); } catch (error) { toast(error.message, "error"); }
}

async function openHaObject(item) {
  openScriptManager();
  if (item.editor === "package") {
    const path = item.path.replace(/^packages\//, "");
    await openFile(path);
    if (state.selected?.path === path) jumpToLine(item.line);
  } else if (item.editor === "configuration") {
    await openConfigurationEditor();
    jumpToConfigurationLine(item.line);
  } else {
    await openResourceEditor(item.path, item.line);
  }
}

function syncResourceScroll() {
  elements["resource-highlighting"].scrollTop = elements["resource-editor"].scrollTop;
  elements["resource-highlighting"].scrollLeft = elements["resource-editor"].scrollLeft;
  elements["resource-line-numbers"].scrollTop = elements["resource-editor"].scrollTop;
}

function updateResourceRendering() {
  const value = elements["resource-editor"].value;
  elements["resource-highlighting"].firstElementChild.innerHTML = value.split("\n").map(highlightLine).join("\n") + "\n";
  elements["resource-line-numbers"].textContent = Array.from({ length: Math.max(1, value.split("\n").length) }, (_, index) => index + 1).join("\n");
  const before = value.slice(0, elements["resource-editor"].selectionStart).split("\n");
  elements["resource-cursor"].textContent = `Zeile ${before.length}, Spalte ${before.at(-1).length + 1}`;
  syncResourceScroll();
}

function setResourceDirty() {
  state.resource.dirty = elements["resource-editor"].value !== state.resource.content;
  elements["resource-save"].disabled = !state.resource.dirty;
}

function jumpToResourceLine(line) {
  const target = Number(line);
  if (!target) return;
  const lines = elements["resource-editor"].value.split("\n");
  const offset = lines.slice(0, target - 1).reduce((sum, value) => sum + value.length + 1, 0);
  elements["resource-editor"].focus();
  elements["resource-editor"].setSelectionRange(offset, offset + (lines[target - 1]?.length || 0));
  elements["resource-editor"].scrollTop = Math.max(0, (target - 4) * 21.45);
  syncResourceScroll();
}

function scheduleResourceValidation() {
  clearTimeout(resourceValidationTimer);
  resourceValidationTimer = setTimeout(async () => {
    try {
      const result = await api("api/validate", {
        method: "POST", body: JSON.stringify({ content: elements["resource-editor"].value }),
      });
      elements["resource-validation"].className = `validation-status ${result.valid ? "valid" : "invalid"}`;
      elements["resource-validation"].textContent = result.valid ? "✓ YAML gültig" : `Fehler: ${result.message}`;
      elements["resource-validation"].dataset.line = result.line || "";
    } catch (error) { toast(error.message, "error"); }
  }, 400);
}

async function openResourceEditor(path, line = 0) {
  try {
    const resource = await api(`api/resource?path=${encodeURIComponent(path)}`);
    state.resource = { ...resource, dirty: false };
    elements["resource-title"].textContent = path.split("/").at(-1);
    elements["resource-path"].textContent = path;
    elements["resource-editor"].value = resource.content;
    elements["resource-save"].disabled = true;
    elements["resource-dialog"].showModal();
    updateResourceRendering();
    scheduleResourceValidation();
    if (line) jumpToResourceLine(line);
  } catch (error) { toast(error.message, "error"); }
}

function closeResourceEditor() {
  if (state.resource.dirty && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
  state.resource.dirty = false;
  elements["resource-dialog"].close();
}

async function saveResource() {
  if (!state.resource.dirty) return;
  elements["resource-save"].disabled = true;
  try {
    const result = await api("api/resource", {
      method: "PUT",
      body: JSON.stringify({
        path: state.resource.path,
        content: elements["resource-editor"].value,
        version: state.resource.version,
      }),
    });
    state.resource = { ...result, dirty: false };
    elements["resource-save"].disabled = true;
    await loadHaObjects();
    toastSaveResult(result, "HA-Ressource gespeichert.");
  } catch (error) {
    elements["resource-save"].disabled = false;
    toast(error.message, "error");
  }
}

function resetSearchPreview() {
  state.searchPreview = null;
  elements["replace-apply"].disabled = true;
  elements["replace-summary"].className = "import-summary";
  elements["replace-summary"].textContent = "Die Eingaben wurden noch nicht geprüft.";
  elements["replace-file-list"].replaceChildren();
}

function openSearchReplaceDialog() {
  resetSearchPreview();
  elements["search-replace-dialog"].showModal();
}

async function previewSearchReplace() {
  try {
    const preview = await api("api/search-replace/preview", {
      method: "POST",
      body: JSON.stringify({
        search: elements["replace-search"].value,
        replacement: elements["replace-value"].value,
        caseSensitive: elements["replace-case-sensitive"].checked,
      }),
    });
    state.searchPreview = preview;
    elements["replace-summary"].className = `import-summary ${preview.matches ? "valid" : "invalid"}`;
    elements["replace-summary"].textContent = `${preview.matches} Treffer in ${preview.files.length} Dateien.`;
    elements["replace-file-list"].replaceChildren(...preview.files.map((file) => {
      const item = document.createElement("div");
      item.className = "import-preview-item";
      item.innerHTML = `<strong>${escapeHtml(file.path)}</strong><span>${file.matches} Treffer · Zeilen ${file.lines.join(", ")}</span>`;
      return item;
    }));
    elements["replace-apply"].disabled = preview.matches === 0;
  } catch (error) { toast(error.message, "error"); }
}

async function applySearchReplace() {
  if (state.dirty || state.configurationDirty || state.resource.dirty) {
    toast("Speichere zuerst alle geöffneten Änderungen.", "error");
    return;
  }
  const preview = state.searchPreview;
  if (!preview || !confirm(`${preview.matches} Ersetzungen in ${preview.files.length} Dateien anwenden?`)) return;
  elements["replace-apply"].disabled = true;
  try {
    const result = await api("api/search-replace/apply", {
      method: "POST",
      body: JSON.stringify({
        search: preview.search,
        replacement: preview.replacement,
        caseSensitive: preview.caseSensitive,
        stateVersion: preview.stateVersion,
      }),
    });
    state.searchPreview = null;
    elements["replace-summary"].className = "import-summary valid";
    elements["replace-summary"].textContent = result.message;
    await refreshFiles();
    if (state.selected) await openFile(state.selected.path, true);
    toast(result.message, "success");
  } catch (error) {
    elements["replace-apply"].disabled = false;
    toast(error.message, "error");
  }
}

async function refreshFiles() {
  const data = await api("api/files");
  state.files = data.files;
  state.categories = data.categories;
  state.tags = data.tags || [];
  elements["root-path"].textContent = data.root;
  renderConfigurationStatus(data.configuration);
  fillCategories(state.selected?.category);
  renderCategories();
  renderTags();
  renderFiles();
  loadPackageConflicts().catch((error) => toast(error.message, "error"));
}

async function openFile(path, force = false) {
  if (!force && state.dirty && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
  try {
    const file = await api(`api/file?path=${encodeURIComponent(path)}`);
    openScriptManager();
    state.selected = file;
    state.originalContent = file.content;
    state.originalCategory = file.category;
    state.originalTags = parseTags(file.tags);
    elements.editor.value = file.content;
    elements["document-name"].textContent = path.split("/").at(-1);
    elements["document-path"].textContent = path;
    fillCategories(file.category);
    elements["tag-input"].value = state.originalTags.join(", ");
    renderFileHomeAssistantCheck(null);
    elements["empty-state"].classList.add("hidden");
    elements["editor-content"].classList.remove("hidden");
    setDirty();
    updateEditorRendering();
    scheduleValidation();
    loadDependencies().catch((error) => toast(error.message, "error"));
    renderFiles();
    elements.sidebar.classList.remove("open");
  } catch (error) { toast(error.message, "error"); }
}

async function saveCurrent() {
  if (!state.selected || !state.dirty) return;
  elements["save-button"].disabled = true;
  try {
    const file = await api("api/file", {
      method: "PUT",
      body: JSON.stringify({
        path: state.selected.path, content: elements.editor.value,
        version: state.selected.version, category: elements["category-select"].value,
        tags: parseTags(elements["tag-input"].value),
      }),
    });
    state.selected = file;
    state.originalContent = file.content;
    state.originalCategory = file.category;
    state.originalTags = parseTags(file.tags);
    setDirty();
    renderFileHomeAssistantCheck(file.configurationCheck);
    await refreshFiles();
    await loadDependencies();
    toastSaveResult(file, "Datei gespeichert.");
  } catch (error) {
    elements["save-button"].disabled = false;
    if (error.details?.line) showValidation(error.details);
    toast(error.message, "error");
  }
}

function showValidation(result) {
  const button = elements["validation-status"];
  button.className = `validation-status ${result.valid ? "valid" : "invalid"}`;
  button.textContent = result.valid ? "✓ YAML gültig" : `Fehler: ${result.message}${result.line ? ` (${result.line}:${result.column})` : ""}`;
  button.dataset.line = result.line || "";
  button.title = button.textContent;
}

function renderAnalysis(result) {
  const counts = result.counts || { error: 0, warning: 0, tip: 0 };
  const summaryClass = counts.error ? "error" : counts.warning ? "warning" : "clean";
  const details = `${counts.error} Fehler · ${counts.warning} Warnungen · ${counts.tip} Tipps`;
  elements["analysis-summary"].className = `analysis-summary ${summaryClass}`;
  elements["analysis-summary"].innerHTML = `<strong>Script-Prüfung: ${result.score}/100</strong><span>${details}</span>`;

  if (!result.findings?.length) {
    const clean = document.createElement("div");
    clean.className = "analysis-finding tip";
    clean.innerHTML = '<span class="finding-dot"></span><div><strong>Keine Auffälligkeiten</strong><small>Syntax und geprüfte Script-Struktur sehen gut aus.</small></div>';
    elements["analysis-list"].replaceChildren(clean);
    return;
  }
  elements["analysis-list"].replaceChildren(...result.findings.map((finding) => {
    const item = document.createElement(finding.line ? "button" : "div");
    item.className = `analysis-finding ${finding.severity}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title)}</strong><small>${escapeHtml(finding.message)}${finding.line ? ` · Zeile ${finding.line}` : ""}</small></div>`;
    if (finding.line) item.addEventListener("click", () => jumpToLine(finding.line));
    return item;
  }));
}

function dependencyLocation(path, line) {
  return `${path}${line ? ` · Zeile ${line}` : ""}`;
}

async function navigateDependency(path, line) {
  if (state.selected?.path !== path) {
    await openFile(path);
    if (state.selected?.path !== path) return;
  }
  jumpToLine(line);
}

function dependencySection(title, children, emptyMessage) {
  const section = document.createElement("section");
  section.className = "dependency-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  if (children.length) section.append(...children);
  else {
    const empty = document.createElement("div");
    empty.className = "dependency-empty";
    empty.textContent = emptyMessage;
    section.append(empty);
  }
  return section;
}

function dependencyReferenceItem(reference, graph, incoming = false) {
  const item = document.createElement("div");
  item.className = "dependency-item";
  item.tabIndex = 0;
  item.setAttribute("role", "button");
  const label = document.createElement("span");
  const name = document.createElement("strong");
  name.textContent = incoming ? reference.source : reference.target;
  const location = document.createElement("small");
  location.textContent = dependencyLocation(reference.path, reference.line);
  label.append(name, location);
  item.append(label);
  item.addEventListener("click", () => navigateDependency(reference.path, reference.line));
  item.addEventListener("keydown", (event) => {
    if (event.target === item && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      navigateDependency(reference.path, reference.line);
    }
  });

  if (!incoming && reference.type === "script" && reference.resolved) {
    const definition = graph.scripts.find((script) => script.entityId === reference.target);
    if (definition) {
      const actions = document.createElement("span");
      actions.className = "dependency-actions";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency-action";
      button.textContent = "Definition";
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        navigateDependency(definition.path, definition.line);
      });
      actions.append(button);
      item.append(actions);
    }
  }
  return item;
}

async function renameScriptDefinition(script) {
  if (state.dirty) {
    toast("Speichere zuerst die aktuellen Änderungen.", "error");
    return;
  }
  const newId = prompt(`Neue ID für ${script.entityId}`, script.id);
  if (!newId || newId === script.id) return;
  try {
    const preview = await api("api/script/rename-preview", {
      method: "POST",
      body: JSON.stringify({ path: script.path, oldId: script.id, newId }),
    });
    const files = preview.files.map((file) => `${file.path} (${file.changes})`).join("\n");
    if (!confirm(`${preview.changeCount} Änderungen in ${preview.files.length} Datei(en):\n\n${files}\n\nUmbenennung anwenden?`)) return;
    const result = await api("api/script/rename", {
      method: "POST",
      body: JSON.stringify({
        path: script.path,
        oldId: script.id,
        newId,
        stateVersion: preview.stateVersion,
      }),
    });
    state.dirty = false;
    await refreshFiles();
    await openFile(script.path, true);
    renderFileHomeAssistantCheck(result.configurationCheck);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderDependencies(result) {
  state.dependencies = result;
  const focus = result.focus || { scripts: [], outgoing: [], incoming: [] };
  const summary = result.summary || { scripts: 0, references: 0, unresolvedScripts: 0 };
  elements["dependency-summary"].className = `analysis-summary ${summary.unresolvedScripts ? "warning" : "clean"}`;
  elements["dependency-summary"].innerHTML = `<strong>${focus.scripts.length} Scripts in dieser Datei</strong><span>${focus.outgoing.length} ausgehende · ${focus.incoming.length} eingehende Bezüge</span>`;

  const definitions = focus.scripts.map((script) => {
    const item = document.createElement("div");
    item.className = "dependency-item";
    const label = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = script.entityId;
    const details = document.createElement("small");
    details.textContent = `${script.alias} · Zeile ${script.line}`;
    label.append(name, details);
    const actions = document.createElement("span");
    actions.className = "dependency-actions";
    const goTo = document.createElement("button");
    goTo.type = "button";
    goTo.className = "dependency-action";
    goTo.textContent = "Öffnen";
    goTo.addEventListener("click", () => jumpToLine(script.line));
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "dependency-action";
    rename.textContent = "Umbenennen";
    rename.addEventListener("click", () => renameScriptDefinition(script));
    actions.append(goTo, rename);
    item.append(label, actions);
    return item;
  });
  const outgoing = focus.outgoing.map((reference) => dependencyReferenceItem(reference, result));
  const incoming = focus.incoming.map((reference) => dependencyReferenceItem(reference, result, true));
  elements["dependency-list"].replaceChildren(
    dependencySection("Definitionen", definitions, "Keine Script-Definition in dieser Datei."),
    dependencySection("Verwendet", outgoing, "Diese Scripts verwenden keine erkannten Entitäten oder Scripts."),
    dependencySection("Verwendet von", incoming, "Keine Package-Scripts verweisen auf diese Scripts."),
  );
}

async function loadDependencies() {
  if (!state.selected) return;
  elements["dependency-summary"].className = "analysis-summary checking";
  elements["dependency-summary"].innerHTML = "<strong>Script-Abhängigkeiten</strong><span>Analyse läuft …</span>";
  const result = await api(`api/dependencies?path=${encodeURIComponent(state.selected.path)}`);
  if (state.selected?.path === result.focus?.path) renderDependencies(result);
}

function scheduleValidation() {
  clearTimeout(validationTimer);
  elements["validation-status"].className = "validation-status neutral";
  elements["validation-status"].textContent = "Prüfe …";
  elements["analysis-summary"].className = "analysis-summary checking";
  elements["analysis-summary"].innerHTML = "<strong>Script-Prüfung</strong><span>Analyse läuft …</span>";
  validationTimer = setTimeout(async () => {
    try {
      const result = await api("api/analyze", {
        method: "POST",
        body: JSON.stringify({ content: elements.editor.value, path: state.selected?.path || "" }),
      });
      showValidation(result.validation);
      renderAnalysis(result);
    } catch (error) { toast(error.message, "error"); }
  }, 450);
}

function jumpToLine(line) {
  const target = Number(line);
  if (!target) return;
  const lines = elements.editor.value.split("\n");
  const offset = lines.slice(0, target - 1).reduce((sum, line) => sum + line.length + 1, 0);
  elements.editor.focus();
  elements.editor.setSelectionRange(offset, offset + (lines[target - 1]?.length || 0));
  elements.editor.scrollTop = Math.max(0, (target - 4) * 21.45);
  syncScroll();
}

function jumpToValidationError() {
  jumpToLine(elements["validation-status"].dataset.line);
}

function jumpToFileHomeAssistantError() {
  jumpToLine(elements["file-ha-check"].dataset.line);
}

function currentIndent() {
  const start = elements.editor.value.lastIndexOf("\n", elements.editor.selectionStart - 1) + 1;
  return elements.editor.value.slice(start, elements.editor.selectionStart).match(/^\s*/)?.[0] || "";
}

function insertText(text) {
  if (!state.selected) return;
  const editor = elements.editor;
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const indent = currentIndent();
  const adapted = text.split("\n").map((line, index) => index ? indent + line : line).join("\n");
  const prefix = start > 0 && editor.value[start - 1] !== "\n" ? "\n" + indent : "";
  editor.setRangeText(prefix + adapted, start, end, "end");
  editor.focus();
  editor.dispatchEvent(new Event("input"));
}

function renderSnippets() {
  elements["snippet-list"].replaceChildren(...snippets.map((snippet) => {
    const button = document.createElement("button");
    button.className = "snippet";
    button.innerHTML = `<span class="snippet-symbol">${escapeHtml(snippet.symbol)}</span><div><strong>${escapeHtml(snippet.name)}</strong><small>${escapeHtml(snippet.description)}</small></div>`;
    button.addEventListener("click", () => insertText(snippet.text));
    return button;
  }));
}

function renderHelperResults(type) {
  if (!state.helpers) return;
  const isEntity = type === "entity";
  const term = elements[`${type}-search`].value.trim().toLocaleLowerCase("de");
  const source = isEntity ? state.helpers.entities : state.helpers.services;
  const filtered = source.filter((item) => JSON.stringify(item).toLocaleLowerCase("de").includes(term)).slice(0, 300);
  elements[`${type}-list`].replaceChildren(...filtered.map((item) => {
    const button = document.createElement("button");
    button.className = "helper-result";
    if (isEntity) {
      button.innerHTML = `<strong>${escapeHtml(item.entity_id)}</strong><span>${escapeHtml(item.name)} · ${escapeHtml(String(item.state))}</span>`;
      button.addEventListener("click", () => insertText(item.entity_id));
    } else {
      button.innerHTML = `<strong>${escapeHtml(item)}</strong>`;
      button.addEventListener("click", () => insertText(`- action: ${item}\n  target:\n    entity_id: `));
    }
    return button;
  }));
}

async function loadHelpers() {
  try {
    state.helpers = await api("api/helpers");
    renderHelperResults("entity");
    renderHelperResults("service");
  } catch {
    elements["api-notice"].classList.remove("hidden");
  }
}

function openNewDialog() {
  elements["new-form"].reset();
  elements["new-dialog"].showModal();
  setTimeout(() => elements["new-path"].focus(), 0);
}

async function createFile(event) {
  event.preventDefault();
  const submitter = event.submitter;
  if (submitter?.value === "cancel") { elements["new-dialog"].close(); return; }
  if (!elements["new-form"].reportValidity()) return;
  const path = elements["new-path"].value.trim();
  const scriptId = elements["new-script-id"].value.trim().replace(/[^a-zA-Z0-9_]/g, "_");
  try {
    const file = await api("api/files", {
      method: "POST",
      body: JSON.stringify({
        path,
        content: NEW_TEMPLATE(scriptId),
        category: elements["new-category"].value || DEFAULT_CATEGORY,
        tags: parseTags(elements["new-tags"].value),
      }),
    });
    elements["new-dialog"].close();
    await refreshFiles();
    await openFile(file.path, true);
    renderFileHomeAssistantCheck(file.configurationCheck);
    toast("Skriptdatei angelegt", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function duplicateCurrent() {
  if (!state.selected) return;
  const extension = state.selected.path.endsWith(".yml") ? ".yml" : ".yaml";
  const suggested = state.selected.path.slice(0, -extension.length) + "_kopie" + extension;
  const path = prompt("Pfad der Kopie", suggested);
  if (!path) return;
  try {
    const file = await api("api/files", {
      method: "POST",
      body: JSON.stringify({
        path,
        content: elements.editor.value,
        category: elements["category-select"].value,
        tags: parseTags(elements["tag-input"].value),
      }),
    });
    await refreshFiles();
    await openFile(file.path, true);
    renderFileHomeAssistantCheck(file.configurationCheck);
    toast("Datei dupliziert", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function renameCurrent() {
  if (!state.selected) return;
  if (state.dirty) {
    toast("Bitte speichere die Änderungen vor dem Umbenennen.", "error");
    return;
  }
  const path = prompt("Neuer Dateipfad innerhalb von packages", state.selected.path);
  if (!path || path === state.selected.path) return;
  try {
    const file = await api("api/rename", {
      method: "POST",
      body: JSON.stringify({ path: state.selected.path, newPath: path, version: state.selected.version }),
    });
    await refreshFiles();
    await openFile(file.path, true);
    toast("Datei umbenannt", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function deleteCurrent() {
  if (!state.selected || !confirm(`${state.selected.path} löschen? Die Datei wird in den Papierkorb verschoben.`)) return;
  try {
    await api("api/file", { method: "DELETE", body: JSON.stringify({ path: state.selected.path, version: state.selected.version }) });
    state.selected = null; state.dirty = false;
    elements["editor-content"].classList.add("hidden");
    elements["empty-state"].classList.remove("hidden");
    elements["analysis-summary"].className = "analysis-summary checking";
    elements["analysis-summary"].innerHTML = "<strong>Script-Prüfung</strong><span>Öffne eine Datei, um Hinweise zu sehen.</span>";
    elements["analysis-list"].replaceChildren();
    await refreshFiles();
    toast("Datei in den Papierkorb verschoben", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function reloadScripts() {
  try {
    const result = await api("api/reload", { method: "POST", body: "{}" });
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

elements.editor.addEventListener("input", () => { updateEditorRendering(); setDirty(); scheduleValidation(); });
elements.editor.addEventListener("scroll", syncScroll);
elements.editor.addEventListener("click", updateCursor);
elements.editor.addEventListener("keyup", updateCursor);
elements.editor.addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    elements.editor.setRangeText("  ", elements.editor.selectionStart, elements.editor.selectionEnd, "end");
    elements.editor.dispatchEvent(new Event("input"));
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveCurrent(); }
});
elements["category-select"].addEventListener("change", () => {
  if (elements["category-select"].value === NEW_CATEGORY) {
    const category = prompt("Name der neuen Kategorie");
    if (category?.trim()) {
      state.categories.push(category.trim());
      fillCategories(category.trim());
    } else fillCategories(state.originalCategory);
  }
  setDirty();
});
elements["tag-input"].addEventListener("input", setDirty);
elements["file-search"].addEventListener("input", renderFiles);
elements["dashboard-button"].addEventListener("click", openDashboard);
elements["dashboard-close"].addEventListener("click", openScriptManager);
elements["dashboard-refresh"].addEventListener("click", loadDashboard);
elements["branch-create"].addEventListener("click", createBranch);
elements["branch-switch"].addEventListener("click", switchBranch);
elements["branch-compare"].addEventListener("click", compareBranch);
elements["branch-merge"].addEventListener("click", mergeBranch);
elements["branch-select"].addEventListener("change", () => {
  state.branchPreview = null;
  elements["branch-merge"].disabled = true;
  elements["branch-diff"].classList.add("hidden");
  elements["branch-summary"].textContent = "Noch kein Branch-Vergleich ausgeführt.";
});
elements["remote-save"].addEventListener("click", saveRemoteConfiguration);
elements["remote-fetch"].addEventListener("click", () => synchronizeRemote("fetch"));
elements["remote-pull"].addEventListener("click", () => synchronizeRemote("pull"));
elements["remote-push"].addEventListener("click", () => synchronizeRemote("push"));
elements["remote-sync"].addEventListener("click", () => synchronizeRemote("sync"));
elements["remote-merge"].addEventListener("click", () => synchronizeRemote("merge"));
elements["remote-force-push"].addEventListener("click", () => synchronizeRemote("force-push"));
elements["remote-remove"].addEventListener("click", removeRemoteConfiguration);
elements["transfer-button"].addEventListener("click", openTransferDialog);
elements["transfer-close"].addEventListener("click", () => elements["transfer-dialog"].close());
elements["transfer-dialog"].addEventListener("cancel", () => elements["transfer-dialog"].close());
elements["objects-button"].addEventListener("click", openObjectsDialog);
elements["objects-close"].addEventListener("click", openScriptManager);
elements["objects-refresh"].addEventListener("click", loadHaObjects);
elements["object-search"].addEventListener("input", renderHaObjects);
elements["object-domain"].addEventListener("change", renderHaObjects);
elements["resource-close"].addEventListener("click", closeResourceEditor);
elements["resource-save"].addEventListener("click", saveResource);
elements["resource-dialog"].addEventListener("cancel", (event) => {
  event.preventDefault();
  closeResourceEditor();
});
elements["resource-editor"].addEventListener("input", () => {
  updateResourceRendering();
  setResourceDirty();
  scheduleResourceValidation();
});
elements["resource-editor"].addEventListener("scroll", syncResourceScroll);
elements["resource-editor"].addEventListener("click", updateResourceRendering);
elements["resource-editor"].addEventListener("keyup", updateResourceRendering);
elements["resource-editor"].addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    elements["resource-editor"].setRangeText("  ", elements["resource-editor"].selectionStart, elements["resource-editor"].selectionEnd, "end");
    elements["resource-editor"].dispatchEvent(new Event("input"));
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveResource();
  }
});
elements["resource-validation"].addEventListener("click", () => jumpToResourceLine(elements["resource-validation"].dataset.line));
elements["search-replace-button"].addEventListener("click", openSearchReplaceDialog);
elements["search-replace-close"].addEventListener("click", () => elements["search-replace-dialog"].close());
elements["search-replace-dialog"].addEventListener("cancel", () => elements["search-replace-dialog"].close());
elements["replace-search"].addEventListener("input", resetSearchPreview);
elements["replace-value"].addEventListener("input", resetSearchPreview);
elements["replace-case-sensitive"].addEventListener("change", resetSearchPreview);
elements["replace-preview"].addEventListener("click", previewSearchReplace);
elements["replace-apply"].addEventListener("click", applySearchReplace);
elements["export-scope"].addEventListener("change", fillExportCategories);
elements["export-start"].addEventListener("click", startPackageExport);
elements["import-file"].addEventListener("change", resetImportPreview);
elements["import-preview"].addEventListener("click", previewPackageImport);
elements["import-apply"].addEventListener("click", applyPackageImport);
elements["configuration-status"].addEventListener("click", openConfigurationEditor);
elements["configuration-button"].addEventListener("click", openConfigurationEditor);
elements["configuration-close"].addEventListener("click", closeConfigurationEditor);
elements["configuration-save"].addEventListener("click", saveConfiguration);
elements["configuration-enable-packages"].addEventListener("click", enablePackagesInConfiguration);
elements["configuration-migrate"].addEventListener("click", migrateConfiguration);
elements["configuration-check"].addEventListener("click", runHomeAssistantCheck);
elements["configuration-history"].addEventListener("click", () => openHistory("configuration"));
elements["configuration-git-history"].addEventListener("click", () => openGitHistory("configuration"));
elements["configuration-validation"].addEventListener("click", jumpToConfigurationError);
elements["home-assistant-check"].addEventListener("click", () => {
  jumpToConfigurationLine(elements["home-assistant-check"].dataset.line);
});
elements["configuration-editor"].addEventListener("input", () => {
  updateConfigurationRendering();
  setConfigurationDirty();
  scheduleConfigurationValidation();
});
elements["configuration-editor"].addEventListener("scroll", syncConfigurationScroll);
elements["configuration-editor"].addEventListener("click", updateConfigurationCursor);
elements["configuration-editor"].addEventListener("keyup", updateConfigurationCursor);
elements["configuration-editor"].addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    event.preventDefault();
    const editor = elements["configuration-editor"];
    editor.setRangeText("  ", editor.selectionStart, editor.selectionEnd, "end");
    editor.dispatchEvent(new Event("input"));
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveConfiguration();
  }
});
elements["configuration-dialog"].addEventListener("cancel", (event) => {
  event.preventDefault();
  closeConfigurationEditor();
});
elements["history-button"].addEventListener("click", () => openHistory("package"));
elements["history-close"].addEventListener("click", () => elements["history-dialog"].close());
elements["history-restore"].addEventListener("click", restoreSelectedBackup);
elements["history-dialog"].addEventListener("cancel", () => elements["history-dialog"].close());
elements["git-history-button"].addEventListener("click", () => openGitHistory("package"));
elements["git-history-close"].addEventListener("click", () => elements["git-dialog"].close());
elements["git-history-restore"].addEventListener("click", restoreSelectedGitCommit);
elements["git-dialog"].addEventListener("cancel", () => elements["git-dialog"].close());
elements["package-conflicts-button"].addEventListener("click", openPackageConflicts);
elements["conflict-close"].addEventListener("click", () => elements["conflict-dialog"].close());
elements["conflict-dialog"].addEventListener("cancel", () => elements["conflict-dialog"].close());
elements["entity-search"].addEventListener("input", () => renderHelperResults("entity"));
elements["service-search"].addEventListener("input", () => renderHelperResults("service"));
elements["save-button"].addEventListener("click", saveCurrent);
elements["new-button"].addEventListener("click", openNewDialog);
elements["empty-new-button"].addEventListener("click", openNewDialog);
elements["new-form"].addEventListener("submit", createFile);
elements["new-path"].addEventListener("input", () => {
  const name = elements["new-path"].value.split("/").at(-1).replace(/\.ya?ml$/i, "").replace(/[^a-zA-Z0-9_]/g, "_");
  elements["new-script-id"].value = name.toLowerCase();
});
elements["duplicate-button"].addEventListener("click", duplicateCurrent);
elements["rename-button"].addEventListener("click", renameCurrent);
elements["delete-button"].addEventListener("click", deleteCurrent);
elements["reload-button"].addEventListener("click", reloadScripts);
elements["validation-status"].addEventListener("click", jumpToValidationError);
elements["file-ha-check"].addEventListener("click", jumpToFileHomeAssistantError);
elements["sidebar-toggle"].addEventListener("click", () => elements.sidebar.classList.add("open"));
elements["sidebar-close"].addEventListener("click", () => elements.sidebar.classList.remove("open"));
elements["helpers-toggle"].addEventListener("click", () => elements.helpers.classList.add("open"));
elements["helpers-close"].addEventListener("click", () => elements.helpers.classList.remove("open"));
document.querySelectorAll(".helper-tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".helper-tab").forEach((item) => {
    item.classList.toggle("active", item === tab);
    item.setAttribute("aria-selected", String(item === tab));
  });
  document.querySelectorAll(".helper-view").forEach((view) => view.classList.add("hidden"));
  document.getElementById(`tab-${tab.dataset.tab}`).classList.remove("hidden");
}));
window.addEventListener("beforeunload", (event) => {
  if (state.dirty || state.configurationDirty || state.resource.dirty) event.preventDefault();
});

renderSnippets();
Promise.all([refreshFiles(), loadHelpers(), loadDashboard(), loadBranches()]).catch((error) => toast(error.message, "error"));
