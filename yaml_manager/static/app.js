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
  history: { scope: "", path: "", currentVersion: "", selectedId: "", diffResult: null },
  gitHistory: { scope: "", path: "", currentVersion: "", selectedCommit: "", diffResult: null },
  dashboard: null,
  dashboardShowSuppressed: false,
  reviewChanges: [],
  reviewPreview: null,
  dependencies: null,
  branches: null,
  branchPreview: null,
  blueprints: null,
  selectedBlueprint: null,
  documentation: null,
  documentationTab: "overview",
  security: null,
  lint: null,
  graph: null,
  compatibility: null,
  secrets: null,
  refactorPreview: null,
  preflight: null,
  entityHealth: null,
  database: null,
  backups: null,
  snapshotPreview: null,
  flow: null,
  traces: null,
  settings: null,
  trash: null,
  completion: { open: false, items: [], index: 0, start: 0, end: 0 },
  haObjects: null,
  resource: { path: "", content: "", version: "", dirty: false },
  searchPreview: null,
  importArchive: "",
  importPreview: null,
  impactResolver: null,
};

const elements = Object.fromEntries([
  "workspace", "sidebar", "sidebar-toggle", "sidebar-close", "sidebar-tools", "sidebar-tools-current", "file-search", "configuration-status", "configuration-status-dot", "package-conflicts-status-dot", "filter-summary", "categories", "tags", "file-list", "file-count", "root-path",
  "empty-state", "empty-open-files-button", "empty-new-button", "editor-content", "document-name", "document-path", "dirty-dot", "category-select", "tag-input",
  "rename-button", "duplicate-button", "delete-button", "editor", "highlighting", "line-numbers", "completion-popover", "validation-status", "file-ha-check", "cursor-status",
  "save-button", "open-files-button", "new-button", "reload-button", "helpers", "helpers-toggle", "helpers-close", "snippet-list", "analysis-summary", "analysis-list", "api-notice",
  "dependency-summary", "dependency-list", "flow-summary", "flow-diagram", "outline-summary", "outline-list",
  "entity-search", "entity-list", "service-search", "service-list", "new-dialog", "new-form", "new-path", "new-script-id",
  "new-category", "new-tags", "category-options", "create-button", "file-browser-page", "file-browser-close", "file-browser-new", "toast-region",
  "configuration-button", "configuration-dialog", "configuration-close", "configuration-editor", "configuration-highlighting",
  "configuration-line-numbers", "configuration-validation", "configuration-cursor", "configuration-save",
  "configuration-enable-packages", "configuration-migrate", "migration-package-name", "configuration-notice",
  "configuration-check", "configuration-history", "configuration-git-history", "home-assistant-check", "history-button", "git-history-button",
  "history-dialog", "history-close", "history-path", "history-list", "diff-placeholder", "diff-view", "diff-changed-only", "history-summary", "history-restore",
  "git-dialog", "git-history-close", "git-history-path", "git-history-list", "git-diff-placeholder", "git-diff-view", "git-diff-changed-only", "git-history-summary", "git-history-restore",
  "package-conflicts-button", "conflict-dialog", "conflict-close", "conflict-summary", "conflict-list",
  "dashboard-button", "dashboard-dialog", "dashboard-close", "dashboard-refresh", "dashboard-show-suppressed", "quality-score", "quality-stats", "dashboard-findings",
  "health-badge", "health-grid",
  "review-button", "review-page", "review-close", "review-add-current", "review-clear", "review-preview", "review-apply", "review-summary", "review-list", "review-diff",
  "lint-button", "lint-page", "lint-close", "lint-refresh", "lint-save", "lint-summary", "lint-stats", "lint-list",
  "lint-require-alias", "lint-require-script-mode", "lint-require-automation-id", "lint-script-pattern", "lint-entity-pattern", "lint-allowed-domains", "lint-forbidden-plaintext", "lint-required-tags",
  "graph-button", "graph-page", "graph-close", "graph-refresh", "graph-search", "graph-type", "graph-summary", "graph-nodes", "graph-edges",
  "compatibility-button", "compatibility-page", "compatibility-close", "compatibility-refresh", "compatibility-summary", "compatibility-stats", "compatibility-list",
  "git-page-button", "git-page", "git-page-close",
  "remote-status", "remote-badge", "remote-url", "remote-branch", "remote-username", "remote-token", "remote-auto-push", "remote-clear-token", "remote-save", "remote-fetch", "remote-pull", "remote-push", "remote-sync", "remote-remove", "remote-resolution", "remote-merge", "remote-force-push",
  "transfer-button", "transfer-dialog", "transfer-close", "export-scope", "export-category", "export-start", "import-file", "import-strategy", "import-preview", "import-apply", "import-summary", "import-preview-list",
  "settings-button", "settings-dialog", "settings-close", "settings-save", "settings-reload", "settings-backup-retention", "settings-backup-days", "settings-backup-size", "settings-trash-days", "settings-trash-size", "settings-import-size", "settings-expanded-size", "settings-import-files", "settings-theme", "settings-after-save", "settings-branch-prefix", "settings-unused-scripts",
  "trash-button", "trash-dialog", "trash-close", "trash-refresh", "trash-purge-all", "trash-summary", "trash-list",
  "package-files-button",
  "objects-button", "objects-dialog", "objects-close", "objects-refresh", "object-search", "object-domain", "objects-summary", "object-list",
  "blueprints-button", "blueprints-page", "blueprints-close", "blueprints-refresh", "blueprints-summary", "blueprint-search", "blueprint-domain", "blueprint-list",
  "blueprint-selected-title", "blueprint-selected-path", "blueprint-selected-domain", "blueprint-package-path", "blueprint-instance-id", "blueprint-instance-alias", "blueprint-inputs", "blueprint-instantiate",
  "blueprint-import-path", "blueprint-import-content", "blueprint-import", "blueprint-from-domain", "blueprint-from-name", "blueprint-from-path", "blueprint-from-content", "blueprint-from-create",
  "documentation-button", "documentation-page", "documentation-close", "documentation-refresh", "documentation-save", "documentation-summary", "documentation-search", "documentation-html", "documentation-preview",
  "security-button", "security-page", "security-close", "security-refresh", "security-summary", "security-stats", "security-list",
  "refactor-button", "refactor-page", "refactor-close", "refactor-kind", "refactor-old", "refactor-new", "refactor-preview", "refactor-apply", "refactor-summary", "refactor-list",
  "secrets-button", "secrets-page", "secrets-close", "secrets-refresh", "secrets-summary", "secret-name", "secret-value", "secret-save", "secret-convert-path", "secret-convert-line", "secret-convert-key", "secret-convert-name", "secret-convert-value", "secret-convert", "secrets-list",
  "preflight-button", "preflight-page", "preflight-close", "preflight-run", "preflight-summary", "preflight-stats", "preflight-list",
  "entity-health-button", "entity-health-page", "entity-health-close", "entity-health-refresh", "entity-health-summary", "entity-health-stats", "entity-health-filter", "entity-health-list",
  "database-button", "database-page", "database-close", "database-refresh", "database-summary", "database-stats", "database-tables-summary", "database-table-list", "database-entities-summary", "database-entity-filter", "database-entity-list",
  "database-compare-summary", "database-compare-filter", "database-compare-list", "database-statistics-summary", "database-statistics-filter", "database-statistics-list", "database-query-summary", "database-query-limit", "database-query-run", "database-query", "database-query-result",
  "backups-button", "backups-page", "backups-close", "backups-refresh", "backups-summary", "backups-stats", "backup-snapshot-create", "backup-database-create", "backup-list-summary", "backup-filter", "backup-list", "backup-database-summary", "backup-database-list", "backup-integrity-summary", "backup-integrity-list", "backup-restore-summary", "backup-restore-apply", "backup-restore-list",
  "traces-button", "traces-page", "traces-close", "traces-refresh", "traces-summary", "trace-search", "trace-domain", "trace-clear-detail", "trace-run-list", "trace-list", "trace-detail-summary", "trace-detail",
  "resource-dialog", "resource-close", "resource-title", "resource-path", "resource-save", "resource-editor", "resource-highlighting", "resource-line-numbers", "resource-validation", "resource-cursor",
  "template-input", "template-render", "template-result", "template-entities",
  "impact-dialog", "impact-summary", "impact-body", "impact-risk", "impact-cancel", "impact-back", "impact-confirm",
  "search-replace-button", "search-replace-dialog", "search-replace-close", "replace-search", "replace-value", "replace-case-sensitive", "replace-preview", "replace-apply", "replace-summary", "replace-file-list",
  "branch-status", "branch-current", "branch-new-name", "branch-create", "branch-select", "branch-switch", "branch-compare", "branch-merge", "branch-summary", "branch-diff",
].map((id) => [id, document.getElementById(id)]));

let validationTimer;
let flowTimer;
let configurationValidationTimer;
let resourceValidationTimer;

const sidebarToolLabels = {
  "dashboard-button": "Dashboard",
  "package-files-button": "Package-Dateien",
  "review-button": "Review",
  "git-page-button": "Git",
  "objects-button": "HA-Objekte",
  "entity-health-button": "Entity-Health",
  "database-button": "Datenbank",
  "backups-button": "Backups",
  "graph-button": "Graph",
  "lint-button": "Lint",
  "compatibility-button": "Kompatibilität",
  "refactor-button": "Refactor",
  "secrets-button": "Secrets",
  "preflight-button": "Preflight",
  "blueprints-button": "Blueprints",
  "documentation-button": "Doku",
  "security-button": "Sicherheit",
  "traces-button": "Traces",
};

function updateSidebarToolSummary() {
  const activeId = Object.keys(sidebarToolLabels).find((id) => elements[id]?.classList.contains("active"));
  elements["sidebar-tools-current"].textContent = activeId ? sidebarToolLabels[activeId] : "Dateieditor";
  elements["sidebar-tools"].classList.toggle("has-active-tool", Boolean(activeId));
}

function collapseSidebarTools() {
  if (window.matchMedia("(max-width: 700px)").matches) {
    elements["sidebar-tools"].removeAttribute("open");
    elements.sidebar.classList.remove("open");
  }
  requestAnimationFrame(updateSidebarToolSummary);
}

function openFileBrowser() {
  closePages();
  renderCategories();
  renderTags();
  renderFiles();
  elements["file-browser-page"].classList.remove("hidden");
  elements["package-files-button"].classList.add("active");
  setTimeout(() => elements["file-search"].focus(), 0);
  updateSidebarToolSummary();
}

function closeFileBrowser() {
  openScriptManager();
}

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
  renderYamlOutline();
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

function yamlOutline(content) {
  return content.split("\n").flatMap((line, index) => {
    const match = line.match(/^(\s*)([A-Za-z0-9_.-]+|"[^"]+"|'[^']+')\s*:/);
    if (!match || line.trimStart().startsWith("#")) return [];
    const depth = Math.min(5, Math.floor(match[1].replace(/\t/g, "  ").length / 2));
    return [{ label: match[2].replace(/^["']|["']$/g, ""), line: index + 1, depth }];
  });
}

function renderYamlOutline() {
  if (!state.selected) return;
  const outline = yamlOutline(elements.editor.value).slice(0, 200);
  elements["outline-summary"].className = `analysis-summary ${outline.length ? "clean" : "checking"}`;
  elements["outline-summary"].innerHTML = `<strong>YAML-Struktur</strong><span>${outline.length ? `${outline.length} Blöcke erkannt` : "Keine YAML-Schlüssel erkannt"}</span>`;
  if (!outline.length) {
    const empty = document.createElement("div");
    empty.className = "dependency-empty";
    empty.textContent = "Keine anspringbaren YAML-Blöcke gefunden.";
    elements["outline-list"].replaceChildren(empty);
    return;
  }
  elements["outline-list"].replaceChildren(...outline.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "outline-item";
    button.style.setProperty("--depth", item.depth);
    button.innerHTML = `<span class="outline-indent"></span><span class="outline-label">${escapeHtml(item.label)}</span><span class="outline-line">${item.line}</span>`;
    button.addEventListener("click", () => jumpToLine(item.line));
    return button;
  }));
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

function applyTheme(theme = "system") {
  if (theme === "light" || theme === "dark") {
    document.documentElement.dataset.theme = theme;
  } else {
    delete document.documentElement.dataset.theme;
  }
}

function applySettings(settings) {
  state.settings = settings;
  applyTheme(settings.theme);
  if (!elements["branch-new-name"].value && settings.defaultBranchPrefix) {
    elements["branch-new-name"].placeholder = `${settings.defaultBranchPrefix}meine-aenderung`;
  }
}

async function loadSettings() {
  const settings = await api("api/settings");
  applySettings(settings);
  return settings;
}

function bytesLabel(value) {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MiB`;
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${size} B`;
}

function renderHealth(health) {
  if (!health) return;
  const checks = [
    {
      title: "Home Assistant",
      detail: health.homeAssistant.lastCheck
        ? `${health.homeAssistant.lastCheck.status} · ${health.homeAssistant.lastCheck.checkedAt || ""}`
        : health.homeAssistant.tokenConfigured ? "Noch keine Prüfung ausgeführt" : "Lokal ohne Supervisor-Token",
      status: health.homeAssistant.lastCheck?.valid === false ? "error" : health.homeAssistant.tokenConfigured ? "ok" : "warn",
    },
    {
      title: "Backups",
      detail: `${health.storage.backups.directories} Stände · ${health.storage.databaseBackups?.directories || 0} DB · ${bytesLabel((health.storage.backups.size || 0) + (health.storage.databaseBackups?.size || 0))}`,
      status: "ok",
    },
    {
      title: "Papierkorb",
      detail: `${health.storage.trash.entries} Dateien · ${bytesLabel(health.storage.trash.size)}`,
      status: health.storage.trash.entries ? "warn" : "ok",
    },
    {
      title: "Importlimits",
      detail: `${health.settings.maxImportFiles} Dateien · ZIP ${health.settings.maxImportSizeMiB} MiB`,
      status: "ok",
    },
    {
      title: "Packages",
      detail: health.paths.packages,
      status: "ok",
    },
    {
      title: "Daten",
      detail: health.paths.data,
      status: "ok",
    },
  ];
  elements["health-badge"].textContent = checks.some((item) => item.status === "error")
    ? "Prüfen"
    : checks.some((item) => item.status === "warn")
      ? "Hinweise"
      : "OK";
  elements["health-grid"].replaceChildren(...checks.map((check) => {
    const card = document.createElement("div");
    card.className = `health-card ${check.status}`;
    card.innerHTML = `<strong>${escapeHtml(check.title)}</strong><span>${escapeHtml(check.detail)}</span>`;
    card.title = check.detail;
    return card;
  }));
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
  updateFilterSummary();
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
  updateFilterSummary();
}

function updateFilterSummary() {
  const active = [];
  if (state.selectedCategory !== "Alle") active.push(state.selectedCategory);
  if (state.selectedTag) active.push(`#${state.selectedTag}`);
  elements["filter-summary"].textContent = active.length ? active.join(" · ") : "Alle Dateien";
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
    button.addEventListener("click", async () => {
      openScriptManager();
      await openFile(file.path);
    });
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
  elements["configuration-status-dot"].className = `status-dot ${status.status}`;
  elements["configuration-status-dot"].title = label;
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
    if (state.settings?.afterSave === "dashboard") {
      closeConfigurationEditor();
      await openDashboard();
    }
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

function parseUnifiedDiff(diff) {
  const rows = [];
  const lines = diff ? diff.split("\n") : [];
  let oldLine = 0;
  let newLine = 0;
  let pendingRemoved = [];
  let pendingAdded = [];

  function flushChange() {
    const count = Math.max(pendingRemoved.length, pendingAdded.length);
    for (let index = 0; index < count; index += 1) {
      const removed = pendingRemoved[index];
      const added = pendingAdded[index];
      rows.push({
        type: removed && added ? "changed" : removed ? "removed" : "added",
        oldLine: removed?.line || "",
        oldText: removed?.text || "",
        newLine: added?.line || "",
        newText: added?.text || "",
      });
    }
    pendingRemoved = [];
    pendingAdded = [];
  }

  for (const line of lines) {
    if (line.startsWith("---") || line.startsWith("+++")) continue;
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
    if (hunk) {
      flushChange();
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      rows.push({ type: "hunk", label: `@@ -${hunk[1]} +${hunk[2]} @@${hunk[3] || ""}` });
      continue;
    }
    if (line.startsWith("-")) {
      pendingRemoved.push({ line: oldLine, text: line.slice(1) });
      oldLine += 1;
      continue;
    }
    if (line.startsWith("+")) {
      pendingAdded.push({ line: newLine, text: line.slice(1) });
      newLine += 1;
      continue;
    }
    flushChange();
    const text = line.startsWith(" ") ? line.slice(1) : line;
    rows.push({ type: "context", oldLine, oldText: text, newLine, newText: text });
    oldLine += 1;
    newLine += 1;
  }
  flushChange();
  return rows;
}

function renderSideBySideDiff(target, placeholder, result, changedOnly = false) {
  const rows = parseUnifiedDiff(result.diff);
  const visibleRows = changedOnly
    ? rows.filter((row) => row.type !== "context")
    : rows;
  if (!visibleRows.length) {
    target.innerHTML = '<div class="diff-empty">Keine Unterschiede zur aktuellen Fassung.</div>';
  } else {
    const body = visibleRows.map((row) => {
      if (row.type === "hunk") {
        return `<tr class="diff-row hunk"><td colspan="4">${escapeHtml(row.label)}</td></tr>`;
      }
      return `<tr class="diff-row ${row.type}"><td class="line-no">${row.oldLine || ""}</td><td class="text-cell old-text">${escapeHtml(row.oldText || "")}</td><td class="line-no">${row.newLine || ""}</td><td class="text-cell new-text">${escapeHtml(row.newText || "")}</td></tr>`;
    }).join("");
    target.innerHTML = `<table class="diff-table"><colgroup><col class="line-col"><col class="text-col"><col class="line-col"><col class="text-col"></colgroup><tbody>${body}</tbody></table>`;
  }
  placeholder.classList.add("hidden");
  target.classList.remove("hidden");
}

async function selectHistoryEntry(entry, button) {
  document.querySelectorAll(".history-entry").forEach((item) => item.classList.toggle("active", item === button));
  state.history.selectedId = entry.id;
  elements["history-restore"].disabled = false;
  elements["history-summary"].textContent = `${entry.created.replace("T", " ")} · +${entry.additions} / -${entry.deletions}`;
  try {
    const result = await api(`api/backup/diff?${historyQuery(state.history.path, { id: entry.id })}`);
    state.history.diffResult = result;
    renderSideBySideDiff(
      elements["diff-view"],
      elements["diff-placeholder"],
      result,
      elements["diff-changed-only"].checked,
    );
    if (result.truncated) toast("Der Diff wurde nach 1.200 Zeilen gekürzt.");
  } catch (error) { toast(error.message, "error"); }
}

function renderHistory(history) {
  elements["history-path"].textContent = history.path;
  state.history.currentVersion = history.currentVersion;
  state.history.selectedId = "";
  state.history.diffResult = null;
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
  state.gitHistory.diffResult = result;
  renderSideBySideDiff(
    elements["git-diff-view"],
    elements["git-diff-placeholder"],
    result,
    elements["git-diff-changed-only"].checked,
  );
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
  state.gitHistory.diffResult = null;
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
  elements["package-conflicts-status-dot"].className = `status-dot ${css}`;
  elements["package-conflicts-status-dot"].title = label;
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

function dashboardFindingActionButton(label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "dependency-action dashboard-action";
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

async function setDashboardFindingStatus(finding, status) {
  await api("api/dashboard/finding", {
    method: "POST",
    body: JSON.stringify({ key: finding.key, status, finding }),
  });
  toast(status === "irrelevant" ? "Hinweis als gegenstandslos markiert." : "Hinweis ausgeblendet.", "success");
  await loadDashboard();
}

async function restoreDashboardFinding(finding) {
  await api("api/dashboard/finding", {
    method: "DELETE",
    body: JSON.stringify({ key: finding.key }),
  });
  toast("Hinweis wird wieder angezeigt.", "success");
  await loadDashboard();
}

function dashboardFindingElement(finding, suppressedView) {
  const item = document.createElement("div");
  item.className = `dashboard-finding ${finding.severity} ${suppressedView ? "suppressed" : ""}`;
  const files = `${(finding.files || []).join(" · ")}${finding.line ? ` · Zeile ${finding.line}` : ""}`;
  const status = suppressedView
    ? `<small><span class="finding-status">${escapeHtml(finding.suppressionLabel || "ausgeblendet")}</span>${finding.suppressedAt ? ` · ${escapeHtml(finding.suppressedAt)}` : ""}</small>`
    : "";
  item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title)}</strong><small>${escapeHtml(finding.message)}</small><small>${escapeHtml(files)}</small>${status}</div><div class="dashboard-finding-actions"></div>`;
  const actions = item.querySelector(".dashboard-finding-actions");
  if (finding.action) {
    actions.append(dashboardFindingActionButton(finding.action.label || "Öffnen", () => runDashboardAction(finding.action)));
  }
  if (finding.key && suppressedView) {
    actions.append(dashboardFindingActionButton("Wieder anzeigen", () => restoreDashboardFinding(finding).catch((error) => toast(error.message, "error"))));
  } else if (finding.key) {
    actions.append(dashboardFindingActionButton("Ausblenden", () => setDashboardFindingStatus(finding, "hidden").catch((error) => toast(error.message, "error"))));
    actions.append(dashboardFindingActionButton("Gegenstandslos", () => setDashboardFindingStatus(finding, "irrelevant").catch((error) => toast(error.message, "error"))));
  }
  return item;
}

function renderDashboard(result) {
  if (!result) return;
  state.dashboard = result;
  const scoreClass = result.score < 60 ? "error" : result.score < 85 ? "warning" : "";
  elements["quality-score"].className = `quality-score ${scoreClass}`;
  elements["quality-score"].innerHTML = `<strong>${result.score}</strong><span>Qualität</span>`;
  const stats = [
    [result.summary.files, "Package-Dateien"],
    [result.summary.automations || 0, "Automationen"],
    [result.summary.scripts, "Scripts"],
    [result.summary.scenes || 0, "Szenen"],
    [result.summary.references || 0, "Bezüge"],
    [result.summary.blueprints || 0, "Blueprints"],
    [result.summary.security || 0, "Security-Hinweise"],
    [result.summary.lint || 0, "Lint-Hinweise"],
    [result.summary.compatibility || 0, "Kompatibilität"],
    [result.summary.entityHealth || 0, "Entity-Health"],
    [result.summary.traces || 0, "Traces"],
    [result.summary.unusedScripts, "Möglicherweise ungenutzt"],
    [result.summary.suppressedFindings || 0, "Ausgeblendet"],
    [result.summary.errors, "Fehler"],
    [result.summary.warnings, "Warnungen"],
    [result.summary.backups, "Backups"],
  ];
  elements["quality-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${value}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  elements["dashboard-show-suppressed"].checked = state.dashboardShowSuppressed;
  const findings = state.dashboardShowSuppressed ? (result.suppressedFindings || []) : (result.findings || []);
  if (!findings.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = state.dashboardShowSuppressed ? "Keine ausgeblendeten Hinweise." : "Keine Qualitätsprobleme gefunden.";
    elements["dashboard-findings"].replaceChildren(empty);
  } else {
    elements["dashboard-findings"].replaceChildren(...findings.map((finding) => dashboardFindingElement(finding, state.dashboardShowSuppressed)));
  }
  renderHealth(result.health);
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

function reviewRequestBody() {
  return {
    changes: state.reviewChanges.map((change) => ({
      path: change.path,
      content: change.content,
      category: change.category,
      tags: change.tags,
    })),
  };
}

function renderReviewBundle() {
  state.reviewPreview = null;
  elements["review-apply"].disabled = true;
  elements["review-diff"].textContent = "Noch keine Vorschau erstellt.";
  if (!state.reviewChanges.length) {
    elements["review-summary"].textContent = "Noch keine Änderung im Paket.";
    elements["review-list"].replaceChildren(emptyBlock("Aktuelle Datei vormerken, um ein Review-Paket zu starten."));
    return;
  }
  elements["review-summary"].textContent = `${state.reviewChanges.length} Dateien vorgemerkt.`;
  elements["review-list"].replaceChildren(...state.reviewChanges.map((change, index) => {
    const item = document.createElement("div");
    item.className = "import-preview-item";
    item.innerHTML = `<strong>${escapeHtml(change.path)}</strong><span>${change.content.length} Zeichen · ${escapeHtml(change.category || DEFAULT_CATEGORY)}</span>`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dependency-action dashboard-action";
    button.textContent = "Entfernen";
    button.addEventListener("click", () => {
      state.reviewChanges.splice(index, 1);
      renderReviewBundle();
    });
    item.append(button);
    return item;
  }));
}

function addCurrentToReview() {
  if (!state.selected) {
    toast("Keine Package-Datei geöffnet.", "error");
    return;
  }
  const change = {
    path: `packages/${state.selected.path}`,
    content: elements.editor.value,
    category: elements["category-select"].value === NEW_CATEGORY ? state.originalCategory : elements["category-select"].value,
    tags: parseTags(elements["tag-input"].value),
  };
  const existing = state.reviewChanges.findIndex((item) => item.path === change.path);
  if (existing >= 0) state.reviewChanges[existing] = change;
  else state.reviewChanges.push(change);
  renderReviewBundle();
  toast(`${state.selected.path} wurde vorgemerkt.`, "success");
}

function renderReviewPreview(result) {
  state.reviewPreview = result;
  elements["review-summary"].textContent = `${result.summary.changes} Änderungen · ${result.summary.additions} hinzugefügt · ${result.summary.deletions} entfernt · Status ${result.status}`;
  elements["review-apply"].disabled = !result.ready;
  elements["review-list"].replaceChildren(...result.files.map((file) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${file.validation?.valid === false ? "error" : file.action === "create" ? "tip" : "warning"}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(file.path)}</strong><small>${escapeHtml(file.action)} · +${file.additions} / -${file.deletions}</small><small>${escapeHtml(file.validation?.message || "")}</small></div>`;
    return item;
  }));
  const checks = result.checks || {};
  const lint = checks.lint?.counts || {};
  const compat = checks.compatibility?.counts || {};
  const conflicts = checks.conflicts?.counts || {};
  const header = [
    `Blocker: ${result.blockers}`,
    `Warnungen: ${result.warnings}`,
    `Konflikte: ${conflicts.error || 0}/${conflicts.warning || 0}`,
    `Lint: ${lint.error || 0}/${lint.warning || 0}`,
    `Kompatibilität: ${compat.error || 0}/${compat.warning || 0}`,
  ].join(" · ");
  elements["review-diff"].textContent = `${header}\n\n${result.files.map((file) => file.diff || `# ${file.path}: keine Textänderung`).join("\n\n")}`;
}

async function previewReview() {
  if (!state.reviewChanges.length) {
    toast("Das Änderungspaket ist leer.", "error");
    return;
  }
  elements["review-preview"].disabled = true;
  try {
    const result = await api("api/review/preview", {
      method: "POST",
      body: JSON.stringify(reviewRequestBody()),
    });
    renderReviewPreview(result);
  } catch (error) { toast(error.message, "error"); }
  finally { elements["review-preview"].disabled = false; }
}

async function applyReview() {
  const preview = state.reviewPreview;
  if (!preview || !preview.ready) return;
  if (!confirm(`${preview.summary.changes} Dateien als Review-Paket anwenden?`)) return;
  elements["review-apply"].disabled = true;
  try {
    const result = await api("api/review/apply", {
      method: "POST",
      body: JSON.stringify({ ...reviewRequestBody(), stateVersion: preview.stateVersion }),
    });
    state.reviewChanges = [];
    state.reviewPreview = null;
    await refreshFiles();
    if (state.selected) await openFile(state.selected.path, true);
    renderReviewBundle();
    toast(result.message, "success");
  } catch (error) {
    elements["review-apply"].disabled = false;
    toast(error.message, "error");
  }
}

function openReviewPage() {
  closePages();
  elements["review-page"].classList.remove("hidden");
  elements["review-button"].classList.add("active");
  renderReviewBundle();
}

function commaList(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function lintRulesFromForm() {
  return {
    requireAlias: elements["lint-require-alias"].checked,
    requireScriptMode: elements["lint-require-script-mode"].checked,
    requireAutomationId: elements["lint-require-automation-id"].checked,
    scriptIdPattern: elements["lint-script-pattern"].value.trim(),
    entityIdPattern: elements["lint-entity-pattern"].value.trim(),
    allowedEntityDomains: commaList(elements["lint-allowed-domains"].value),
    forbiddenPlaintext: commaList(elements["lint-forbidden-plaintext"].value),
    requiredTags: commaList(elements["lint-required-tags"].value),
  };
}

function fillLintRules(rules = {}) {
  elements["lint-require-alias"].checked = rules.requireAlias !== false;
  elements["lint-require-script-mode"].checked = rules.requireScriptMode !== false;
  elements["lint-require-automation-id"].checked = rules.requireAutomationId !== false;
  elements["lint-script-pattern"].value = rules.scriptIdPattern || "^[a-z0-9_]+$";
  elements["lint-entity-pattern"].value = rules.entityIdPattern || "^[a-z0-9_]+\\.[a-z0-9_]+$";
  elements["lint-allowed-domains"].value = (rules.allowedEntityDomains || []).join(", ");
  elements["lint-forbidden-plaintext"].value = (rules.forbiddenPlaintext || []).join(", ");
  elements["lint-required-tags"].value = (rules.requiredTags || []).join(", ");
}

function renderFindingList(target, findings, emptyMessage) {
  if (!findings?.length) {
    target.replaceChildren(emptyBlock(emptyMessage));
    return;
  }
  target.replaceChildren(...findings.map((finding) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${finding.severity}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title)}</strong><small>${escapeHtml(finding.message)}</small><small>${escapeHtml((finding.files || []).join(" · "))}${finding.line ? ` · Zeile ${finding.line}` : ""}</small></div>`;
    if (finding.files?.[0]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency-action dashboard-action";
      button.textContent = "Öffnen";
      button.addEventListener("click", () => openManagedPath(finding.files[0], finding.line));
      item.append(button);
    }
    return item;
  }));
}

function renderLint(result) {
  state.lint = result;
  fillLintRules(result.rules || {});
  elements["lint-summary"].textContent = `${result.summary.files} Dateien · ${result.counts.warning} Warnungen · ${result.counts.tip} Tipps`;
  const stats = [
    [result.counts.error || 0, "Fehler"],
    [result.counts.warning || 0, "Warnungen"],
    [result.counts.tip || 0, "Tipps"],
    [(result.rules?.allowedEntityDomains || []).length || "Alle", "Domains"],
  ];
  elements["lint-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  renderFindingList(elements["lint-list"], result.findings, "Keine Lint-Hinweise gefunden.");
}

async function loadLint() {
  const result = await api("api/lint");
  renderLint(result);
  return result;
}

async function saveLintRules() {
  try {
    const settings = await api("api/settings", {
      method: "PUT",
      body: JSON.stringify({ lintRules: lintRulesFromForm() }),
    });
    state.settings = settings;
    toast("Lint-Regeln gespeichert.", "success");
    await loadLint();
  } catch (error) { toast(error.message, "error"); }
}

async function openLintPage() {
  closePages();
  elements["lint-page"].classList.remove("hidden");
  elements["lint-button"].classList.add("active");
  try { await loadLint(); } catch (error) { toast(error.message, "error"); }
}

function renderGraph(result) {
  state.graph = result;
  const term = elements["graph-search"].value.trim().toLocaleLowerCase("de");
  const type = elements["graph-type"].value;
  const nodes = (result.nodes || []).filter((node) => {
    if (type && node.type !== type) return false;
    const haystack = `${node.label} ${node.key} ${node.path || ""} ${node.entityId || ""}`.toLocaleLowerCase("de");
    return !term || haystack.includes(term);
  }).slice(0, 300);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = (result.edges || []).filter((edge) => (!term && !type) || nodeIds.has(edge.source) || nodeIds.has(edge.target)).slice(0, 300);
  elements["graph-summary"].textContent = `${result.summary.nodes} Knoten · ${result.summary.edges} Beziehungen`;
  elements["graph-nodes"].replaceChildren(...(nodes.length ? nodes.map((node) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "dashboard-finding tip graph-item";
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(node.label)}</strong><small>${escapeHtml(node.type)}${node.domain ? ` · ${escapeHtml(node.domain)}` : ""}</small><small>${escapeHtml(node.path || node.key)}</small></div>`;
    if (node.path) item.addEventListener("click", () => openManagedPath(node.path, node.line));
    return item;
  }) : [emptyBlock("Keine Knoten für den Filter gefunden.")]));
  elements["graph-edges"].replaceChildren(...(edges.length ? edges.map((edge) => {
    const source = result.nodes.find((node) => node.id === edge.source);
    const target = result.nodes.find((node) => node.id === edge.target);
    const item = document.createElement("button");
    item.type = "button";
    item.className = "dashboard-finding warning graph-item";
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(source?.label || edge.source)} → ${escapeHtml(target?.label || edge.target)}</strong><small>${escapeHtml(edge.relation)}</small><small>${escapeHtml(edge.path || "")}${edge.line ? ` · Zeile ${edge.line}` : ""}</small></div>`;
    if (edge.path) item.addEventListener("click", () => openManagedPath(edge.path, edge.line));
    return item;
  }) : [emptyBlock("Keine Beziehungen für den Filter gefunden.")]));
}

async function loadGraph() {
  const result = await api("api/graph");
  renderGraph(result);
  return result;
}

async function openGraphPage() {
  closePages();
  elements["graph-page"].classList.remove("hidden");
  elements["graph-button"].classList.add("active");
  try { await loadGraph(); } catch (error) { toast(error.message, "error"); }
}

function renderCompatibility(result) {
  state.compatibility = result;
  const ha = result.homeAssistant || {};
  elements["compatibility-summary"].textContent = ha.available ? `Home Assistant ${ha.version || ""} · ${result.counts.warning} Warnungen · ${result.counts.tip} Tipps` : `${ha.message || "HA-Version nicht verfügbar"} · ${result.counts.warning} Warnungen`;
  const stats = [
    [ha.available ? ha.version || "Ja" : "Nein", "HA-Version"],
    [result.counts.error || 0, "Fehler"],
    [result.counts.warning || 0, "Warnungen"],
    [result.counts.tip || 0, "Tipps"],
  ];
  elements["compatibility-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  renderFindingList(elements["compatibility-list"], result.findings, "Keine Kompatibilitäts-Hinweise gefunden.");
}

async function loadCompatibility() {
  const result = await api("api/compatibility");
  renderCompatibility(result);
  return result;
}

async function openCompatibilityPage() {
  closePages();
  elements["compatibility-page"].classList.remove("hidden");
  elements["compatibility-button"].classList.add("active");
  try { await loadCompatibility(); } catch (error) { toast(error.message, "error"); }
}

function closePages() {
  ["dashboard-dialog", "file-browser-page", "review-page", "git-page", "objects-dialog", "blueprints-page", "documentation-page", "security-page", "entity-health-page", "database-page", "backups-page", "graph-page", "lint-page", "compatibility-page", "refactor-page", "secrets-page", "preflight-page", "traces-page"].forEach((id) => {
    elements[id].classList.add("hidden");
  });
  ["dashboard-button", "package-files-button", "review-button", "git-page-button", "objects-button", "blueprints-button", "documentation-button", "security-button", "entity-health-button", "database-button", "backups-button", "graph-button", "lint-button", "compatibility-button", "refactor-button", "secrets-button", "preflight-button", "traces-button"].forEach((id) => {
    elements[id].classList.remove("active");
  });
  requestAnimationFrame(updateSidebarToolSummary);
}

async function openDashboard() {
  closePages();
  elements["dashboard-dialog"].classList.remove("hidden");
  elements["dashboard-button"].classList.add("active");
  await loadDashboard();
}

function openScriptManager() {
  closePages();
}

async function loadRemoteStatus() {
  const remote = await api("api/git/remote");
  renderRemoteStatus(remote);
  return remote;
}

async function openGitPage() {
  closePages();
  elements["git-page"].classList.remove("hidden");
  elements["git-page-button"].classList.add("active");
  try {
    await Promise.all([loadBranches(), loadRemoteStatus()]);
  } catch (error) { toast(error.message, "error"); }
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
  if (["push", "sync", "merge", "force-push"].includes(action)) {
    try {
      const warning = await api("api/security/push-warning");
      if (!warning.ok) {
        const examples = (warning.findings || [])
          .slice(0, 3)
          .map((item) => `• ${item.title}${item.files?.[0] ? ` (${item.files[0]}${item.line ? `:${item.line}` : ""})` : ""}`)
          .join("\n");
        const message = `Die Sicherheitsprüfung meldet ${warning.count} kritische Hinweise vor dem Git-Push.\n\n${examples}\n\nTrotzdem fortfahren?`;
        if (!confirm(message)) {
          toast("Git-Aktion wegen Sicherheitsprüfung abgebrochen.", "error");
          return;
        }
      }
    } catch (error) {
      if (!confirm(`Sicherheitsprüfung konnte nicht ausgeführt werden: ${error.message}\n\nGit-Aktion trotzdem fortsetzen?`)) return;
    }
  }
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

function fillSettings(settings = state.settings) {
  if (!settings) return;
  elements["settings-backup-retention"].value = settings.backupRetention;
  elements["settings-backup-days"].value = settings.backupRetentionDays;
  elements["settings-backup-size"].value = settings.backupMaxSizeMiB;
  elements["settings-trash-days"].value = settings.trashRetentionDays;
  elements["settings-trash-size"].value = settings.trashMaxSizeMiB;
  elements["settings-import-size"].value = settings.maxImportSizeMiB;
  elements["settings-expanded-size"].value = settings.maxExpandedImportSizeMiB;
  elements["settings-import-files"].value = settings.maxImportFiles;
  elements["settings-theme"].value = settings.theme;
  elements["settings-after-save"].value = settings.afterSave;
  elements["settings-branch-prefix"].value = settings.defaultBranchPrefix;
  elements["settings-unused-scripts"].checked = settings.showUnusedScripts;
}

async function openSettingsDialog() {
  try {
    const settings = await loadSettings();
    fillSettings(settings);
    elements["settings-dialog"].showModal();
  } catch (error) { toast(error.message, "error"); }
}

async function saveSettings() {
  elements["settings-save"].disabled = true;
  try {
    const settings = await api("api/settings", {
      method: "PUT",
      body: JSON.stringify({
        backupRetention: elements["settings-backup-retention"].value,
        backupRetentionDays: elements["settings-backup-days"].value,
        backupMaxSizeMiB: elements["settings-backup-size"].value,
        trashRetentionDays: elements["settings-trash-days"].value,
        trashMaxSizeMiB: elements["settings-trash-size"].value,
        maxImportSizeMiB: elements["settings-import-size"].value,
        maxExpandedImportSizeMiB: elements["settings-expanded-size"].value,
        maxImportFiles: elements["settings-import-files"].value,
        theme: elements["settings-theme"].value,
        afterSave: elements["settings-after-save"].value,
        defaultBranchPrefix: elements["settings-branch-prefix"].value,
        showUnusedScripts: elements["settings-unused-scripts"].checked,
      }),
    });
    applySettings(settings);
    fillSettings(settings);
    await loadDashboard();
    toast("Einstellungen gespeichert", "success");
  } catch (error) { toast(error.message, "error"); }
  finally { elements["settings-save"].disabled = false; }
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
  const maxSize = (state.settings?.maxImportSizeMiB || 10) * 1024 * 1024;
  if (file.size > maxSize) {
    toast(`Das ZIP-Archiv ist größer als ${state.settings?.maxImportSizeMiB || 10} MiB.`, "error");
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

function renderTrash(result) {
  state.trash = result;
  const retention = result.retention
    ? ` · ${result.retention.days || "∞"} Tage · ${result.retention.maxSizeMiB || "∞"} MiB`
    : "";
  const cleanup = result.cleanup?.removedEntries
    ? ` · ${result.cleanup.removedEntries} automatisch entfernt`
    : "";
  elements["trash-summary"].textContent = result.count
    ? `${result.count} gelöschte Datei(en) im Papierkorb${retention}${cleanup}`
    : `Der Papierkorb ist leer.${cleanup}`;
  elements["trash-purge-all"].disabled = !result.count;
  if (!result.entries.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Keine gelöschten Dateien vorhanden.";
    elements["trash-list"].replaceChildren(empty);
    return;
  }
  elements["trash-list"].replaceChildren(...result.entries.map((entry) => {
    const item = document.createElement("div");
    item.className = "trash-item";
    const details = document.createElement("div");
    details.innerHTML = `<strong>${escapeHtml(entry.path)}</strong><small>${escapeHtml(entry.deleted.replace("T", " "))} · ${entry.size} Bytes · ${escapeHtml(entry.category || DEFAULT_CATEGORY)}</small>`;
    const stateLabel = document.createElement("div");
    stateLabel.innerHTML = `<small>${entry.exists ? "Pfad ist belegt" : "Pfad ist frei"}</small><small>${escapeHtml((entry.tags || []).map((tag) => `#${tag}`).join(" "))}</small>`;
    const actions = document.createElement("div");
    actions.className = "trash-actions";
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "button secondary";
    restore.textContent = "Wiederherstellen";
    restore.addEventListener("click", () => restoreTrashEntry(entry));
    const purge = document.createElement("button");
    purge.type = "button";
    purge.className = "button warning";
    purge.textContent = "Löschen";
    purge.addEventListener("click", () => purgeTrashEntry(entry));
    actions.append(restore, purge);
    item.append(details, stateLabel, actions);
    return item;
  }));
}

async function loadTrash() {
  const result = await api("api/trash");
  renderTrash(result);
  return result;
}

async function openTrashDialog() {
  try {
    await loadTrash();
    elements["trash-dialog"].showModal();
  } catch (error) { toast(error.message, "error"); }
}

async function restoreTrashEntry(entry) {
  let version = null;
  let overwrite = false;
  if (entry.exists) {
    if (!confirm(`${entry.path} existiert bereits. Vorhandene Datei überschreiben?`)) return;
    try {
      const current = await api(`api/file?path=${encodeURIComponent(entry.path)}`);
      version = current.version;
      overwrite = true;
    } catch (error) {
      toast(error.message, "error");
      return;
    }
  }
  try {
    const result = await api("api/trash/restore", {
      method: "POST",
      body: JSON.stringify({ id: entry.id, path: entry.path, overwrite, version }),
    });
    await refreshFiles();
    await loadTrash();
    elements["trash-dialog"].close();
    await openFile(result.path, true);
    renderFileHomeAssistantCheck(result.configurationCheck);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function purgeTrashEntry(entry) {
  if (!confirm(`${entry.path} endgültig aus dem Papierkorb löschen?`)) return;
  try {
    const result = await api("api/trash", {
      method: "DELETE",
      body: JSON.stringify({ id: entry.id, path: entry.path }),
    });
    renderTrash(result);
    toast("Papierkorb-Eintrag gelöscht", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function purgeAllTrash() {
  if (!state.trash?.count || !confirm("Papierkorb vollständig leeren? Diese Dateien können danach nicht über die App wiederhergestellt werden.")) return;
  try {
    const result = await api("api/trash", { method: "DELETE", body: "{}" });
    renderTrash(result);
    await loadDashboard();
    toast("Papierkorb geleert", "success");
  } catch (error) { toast(error.message, "error"); }
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
  closePages();
  elements["objects-dialog"].classList.remove("hidden");
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

async function openManagedPath(path, line = 0) {
  const target = String(path || "");
  if (!target) return;
  if (target.startsWith("packages/")) {
    const packagePath = target.replace(/^packages\//, "");
    await openFile(packagePath);
    if (line) jumpToLine(line);
  } else if (target === "configuration.yaml" || target === "/config/configuration.yaml") {
    await openConfigurationEditor();
    if (line) jumpToConfigurationLine(line);
  } else if (target.endsWith(".yaml") || target.endsWith(".yml")) {
    await openResourceEditor(target.replace(/^\/config\//, ""), line);
  }
}

async function runDashboardAction(action) {
  if (!action) return;
  if (action.type === "conflicts") {
    await openPackageConflicts();
  } else if (action.type === "blueprints") {
    await openBlueprintsPage();
  } else if (action.type === "security") {
    await openSecurityPage();
  } else if (action.type === "entity-health") {
    await openEntityHealthPage();
  } else if (action.type === "lint") {
    await openLintPage();
  } else if (action.type === "compatibility") {
    await openCompatibilityPage();
  } else if (action.type === "graph") {
    await openGraphPage();
  } else if (action.type === "traces") {
    await openTracesPage();
  } else if (action.type === "open-managed") {
    await openManagedPath(action.path, action.line);
  }
}

function slug(value) {
  return String(value || "").toLocaleLowerCase("de").replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "blueprint";
}

function blueprintDefaultInputs(blueprint) {
  return (blueprint.inputs || []).map((input) => {
    let value = input.default;
    if (value === undefined || value === null) value = "";
    if (typeof value === "object") value = JSON.stringify(value);
    return `${input.name}: ${value}`;
  }).join("\n");
}

function selectBlueprint(blueprint) {
  state.selectedBlueprint = blueprint;
  elements["blueprint-selected-title"].textContent = blueprint.name;
  elements["blueprint-selected-path"].textContent = blueprint.path;
  elements["blueprint-selected-domain"].textContent = blueprint.domain;
  const id = slug(blueprint.name);
  elements["blueprint-instance-id"].value = id;
  elements["blueprint-instance-alias"].value = blueprint.name;
  elements["blueprint-package-path"].value = `blueprints/${id}.yaml`;
  elements["blueprint-inputs"].value = blueprintDefaultInputs(blueprint);
  elements["blueprint-instantiate"].disabled = !["automation", "script"].includes(blueprint.domain);
  renderBlueprints();
}

function renderBlueprints() {
  const result = state.blueprints;
  if (!result) return;
  const term = elements["blueprint-search"].value.trim().toLocaleLowerCase("de");
  const domain = elements["blueprint-domain"].value;
  const visible = result.blueprints.filter((item) => {
    const haystack = `${item.name} ${item.description} ${item.path}`.toLocaleLowerCase("de");
    return (!domain || item.domain === domain) && (!term || haystack.includes(term));
  });
  elements["blueprints-summary"].textContent = `${result.summary.total} Blueprints · ${result.summary.automation} Automation · ${result.summary.script} Script · ${result.summary.invalid} ungültig`;
  elements["blueprint-list"].replaceChildren(...visible.map((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `blueprint-item${state.selectedBlueprint?.path === item.path ? " active" : ""}`;
    button.innerHTML = `<span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.path)}</small></span><span class="object-kind">${escapeHtml(item.domain)}</span><small>${item.inputCount} Eingaben</small>`;
    button.addEventListener("click", () => selectBlueprint(item));
    return button;
  }));
  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "Keine Blueprints gefunden.";
    elements["blueprint-list"].replaceChildren(empty);
  }
}

async function loadBlueprints() {
  elements["blueprints-summary"].textContent = "Blueprints werden geladen …";
  state.blueprints = await api("api/blueprints");
  if (state.selectedBlueprint) {
    state.selectedBlueprint = state.blueprints.blueprints.find((item) => item.path === state.selectedBlueprint.path) || null;
  }
  renderBlueprints();
}

async function openBlueprintsPage() {
  closePages();
  elements["blueprints-page"].classList.remove("hidden");
  elements["blueprints-button"].classList.add("active");
  if (state.selected && !elements["blueprint-from-content"].value) {
    elements["blueprint-from-content"].value = elements.editor.value;
    elements["blueprint-from-name"].value = state.selected.name || state.selected.path.split("/").at(-1).replace(/\.ya?ml$/i, "");
  }
  try { await loadBlueprints(); } catch (error) { toast(error.message, "error"); }
}

async function instantiateSelectedBlueprint() {
  const blueprint = state.selectedBlueprint;
  if (!blueprint) return;
  try {
    const result = await api("api/blueprints/instantiate", {
      method: "POST",
      body: JSON.stringify({
        blueprintPath: blueprint.path,
        packagePath: elements["blueprint-package-path"].value,
        objectId: elements["blueprint-instance-id"].value,
        alias: elements["blueprint-instance-alias"].value,
        inputsText: elements["blueprint-inputs"].value,
      }),
    });
    await refreshFiles();
    await openFile(result.path, true);
    renderFileHomeAssistantCheck(result.configurationCheck);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function importBlueprint() {
  try {
    const blueprint = await api("api/blueprints/import", {
      method: "POST",
      body: JSON.stringify({
        path: elements["blueprint-import-path"].value,
        content: elements["blueprint-import-content"].value,
      }),
    });
    elements["blueprint-import-content"].value = "";
    await loadBlueprints();
    selectBlueprint(blueprint);
    toast("Blueprint importiert", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function createBlueprintFromYaml() {
  try {
    const blueprint = await api("api/blueprints/from-yaml", {
      method: "POST",
      body: JSON.stringify({
        domain: elements["blueprint-from-domain"].value,
        name: elements["blueprint-from-name"].value,
        path: elements["blueprint-from-path"].value,
        content: elements["blueprint-from-content"].value,
      }),
    });
    await loadBlueprints();
    selectBlueprint(blueprint);
    toast("Blueprint erzeugt", "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderDocumentation(result) {
  state.documentation = result;
  const summary = result.summary || {};
  elements["documentation-summary"].textContent = `${summary.files || 0} Dateien · ${summary.automations || 0} Automationen · ${summary.scripts || 0} Scripts · ${summary.entities || 0} Entitäten`;
  elements["documentation-preview"].textContent = result.content || "";
  renderDocumentationHtml();
}

function documentationMatches(value) {
  const term = elements["documentation-search"].value.trim().toLocaleLowerCase("de");
  return !term || JSON.stringify(value).toLocaleLowerCase("de").includes(term);
}

function docsCard(title, detail, meta = "") {
  const item = document.createElement("div");
  item.className = "documentation-card";
  item.innerHTML = `<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span>${meta ? `<small>${escapeHtml(meta)}</small>` : ""}`;
  return item;
}

function renderDocumentationHtml() {
  const result = state.documentation;
  if (!result) return;
  const data = result.data || {};
  document.querySelectorAll(".documentation-tab").forEach((tab) => {
    const active = tab.dataset.docTab === state.documentationTab;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  elements["documentation-preview"].classList.toggle("hidden", state.documentationTab !== "markdown");
  elements["documentation-html"].classList.toggle("hidden", state.documentationTab === "markdown");
  if (state.documentationTab === "markdown") return;
  const container = elements["documentation-html"];
  if (state.documentationTab === "overview") {
    const files = (data.files || []).filter(documentationMatches);
    const objects = (data.objects || []).filter(documentationMatches);
    container.replaceChildren(
      docsCard("Package-Dateien", String(result.summary.files || 0), "Gefiltert: " + files.length),
      docsCard("HA-Objekte", `${result.summary.automations || 0} Automationen · ${result.summary.scripts || 0} Scripts · ${result.summary.scenes || 0} Szenen`, "Gefiltert: " + objects.length),
      docsCard("Bezüge", String(result.summary.references || 0), `${result.summary.entities || 0} Entitäten`),
      docsCard("Auffälligkeiten", `${result.summary.conflicts || 0} Fehler · ${result.summary.warnings || 0} Warnungen`, `${result.summary.commits || 0} Git-Commits`),
      documentationTable(["Typ", "Name", "Entity-ID", "Quelle"], objects.slice(0, 80).map((item) => [item.domain, item.alias, item.entityId, item.path])),
    );
  } else if (state.documentationTab === "graph") {
    const graph = (data.graph || []).filter(documentationMatches);
    container.replaceChildren(
      ...graph.slice(0, 160).map((edge) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = `graph-edge ${edge.resolved === false ? "warning" : ""}`;
        item.innerHTML = `<span>${escapeHtml(edge.source || "Quelle")}</span><strong>→</strong><span>${escapeHtml(edge.targetLabel || edge.target || "Ziel")}</span><small>${escapeHtml(edge.path || "")}${edge.line ? ` · Zeile ${edge.line}` : ""}</small>`;
        item.addEventListener("click", () => openManagedPath(edge.path, edge.line));
        return item;
      }),
    );
    if (!graph.length) container.replaceChildren(emptyBlock("Keine Graph-Bezüge gefunden."));
  } else if (state.documentationTab === "entities") {
    const entities = (data.entities || []).filter(documentationMatches);
    container.replaceChildren(documentationTable(["Entity-ID", "Domain", "Verwendungen"], entities.map((item) => [item.entityId, item.domain, item.count])));
  } else if (state.documentationTab === "changes") {
    const commits = (data.commits || []).filter(documentationMatches);
    const findings = (data.findings || []).filter(documentationMatches);
    container.replaceChildren(
      documentationTable(["Commit", "Zeitpunkt", "Nachricht"], commits.map((item) => [item.shortId, item.created, item.subject])),
      documentationTable(["Schwere", "Hinweis", "Dateien"], findings.map((item) => [item.severity, item.title, (item.files || []).join(" · ")])),
    );
  }
}

function documentationTable(headers, rows) {
  const wrapper = document.createElement("div");
  wrapper.className = "documentation-table-wrap";
  if (!rows.length) return emptyBlock("Keine Einträge für diesen Filter.");
  const table = document.createElement("table");
  table.className = "documentation-table";
  table.innerHTML = `<thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(String(cell ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody>`;
  wrapper.append(table);
  return wrapper;
}

function emptyBlock(message) {
  const empty = document.createElement("div");
  empty.className = "history-empty";
  empty.textContent = message;
  return empty;
}

async function loadDocumentation() {
  const result = await api("api/documentation");
  renderDocumentation(result);
  return result;
}

async function openDocumentationPage() {
  closePages();
  elements["documentation-page"].classList.remove("hidden");
  elements["documentation-button"].classList.add("active");
  try { await loadDocumentation(); } catch (error) { toast(error.message, "error"); }
}

async function saveDocumentation() {
  try {
    const result = await api("api/documentation/write", { method: "POST", body: "{}" });
    renderDocumentation(result);
    toast(`Dokumentation gespeichert: ${result.path}`, "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderSecurity(result) {
  state.security = result;
  const summary = result.summary || {};
  elements["security-summary"].textContent = `${summary.references || 0} !secret-Referenzen · ${summary.missing || 0} fehlend · ${summary.plaintext || 0} Klartext-Hinweise`;
  const stats = [
    [result.secretsFile?.exists ? "Ja" : "Nein", "secrets.yaml"],
    [result.secretsFile?.defined || 0, "Definierte Secrets"],
    [result.counts?.error || 0, "Fehler"],
    [result.counts?.warning || 0, "Warnungen"],
    [summary.unused || 0, "Möglicherweise ungenutzt"],
  ];
  elements["security-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  if (!result.findings?.length) {
    elements["security-list"].replaceChildren(emptyBlock("Keine Secret- oder Klartext-Hinweise gefunden."));
    return;
  }
  elements["security-list"].replaceChildren(...result.findings.map((finding) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${finding.severity}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title)}</strong><small>${escapeHtml(finding.message)}</small><small>${escapeHtml((finding.files || []).join(" · "))}${finding.line ? ` · Zeile ${finding.line}` : ""}</small></div>`;
    if (finding.files?.[0] && finding.files[0] !== "secrets.yaml") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency-action dashboard-action";
      button.textContent = "Öffnen";
      button.addEventListener("click", () => openManagedPath(finding.files[0], finding.line));
      item.append(button);
    }
    return item;
  }));
}

async function loadSecurity() {
  const result = await api("api/security");
  renderSecurity(result);
  return result;
}

async function openSecurityPage() {
  closePages();
  elements["security-page"].classList.remove("hidden");
  elements["security-button"].classList.add("active");
  try { await loadSecurity(); } catch (error) { toast(error.message, "error"); }
}

function renderRefactorPreview(result) {
  state.refactorPreview = result;
  elements["refactor-summary"].textContent = `${result.matches} Treffer in ${result.files.length} Dateien.`;
  elements["refactor-apply"].disabled = result.matches === 0;
  elements["refactor-list"].replaceChildren(...result.files.map((file) => {
    const item = document.createElement("div");
    item.className = "import-preview-item";
    const target = file.newPath ? ` → ${escapeHtml(file.newPath)}` : "";
    const lines = file.lines?.length ? ` · Zeilen ${file.lines.join(", ")}` : "";
    item.innerHTML = `<strong>${escapeHtml(file.path)}${target}</strong><span>${file.matches} Treffer${lines}</span>`;
    return item;
  }));
  if (!result.files.length) elements["refactor-list"].replaceChildren(emptyBlock("Keine Treffer gefunden."));
}

async function previewRefactor() {
  try {
    const result = await api("api/refactor/preview", {
      method: "POST",
      body: JSON.stringify({
        kind: elements["refactor-kind"].value,
        oldValue: elements["refactor-old"].value.trim(),
        newValue: elements["refactor-new"].value.trim(),
      }),
    });
    renderRefactorPreview(result);
  } catch (error) { toast(error.message, "error"); }
}

async function applyRefactor() {
  const preview = state.refactorPreview;
  if (!preview || !confirm(`${preview.matches} Treffer in ${preview.files.length} Dateien ändern?`)) return;
  elements["refactor-apply"].disabled = true;
  try {
    const result = await api("api/refactor/apply", {
      method: "POST",
      body: JSON.stringify({
        kind: preview.kind,
        oldValue: preview.oldValue,
        newValue: preview.newValue,
        stateVersion: preview.stateVersion,
      }),
    });
    state.refactorPreview = null;
    await refreshFiles();
    if (state.selected) await openFile(state.selected.path, true);
    elements["refactor-summary"].textContent = result.message;
    elements["refactor-list"].replaceChildren();
    toast(result.message, "success");
  } catch (error) {
    elements["refactor-apply"].disabled = false;
    toast(error.message, "error");
  }
}

function openRefactorPage() {
  closePages();
  elements["refactor-page"].classList.remove("hidden");
  elements["refactor-button"].classList.add("active");
}

function renderSecrets(result) {
  state.secrets = result;
  elements["secrets-summary"].textContent = `${result.count || 0} Secrets · ${result.summary?.references || 0} Referenzen · ${result.summary?.missing || 0} fehlend`;
  if (!result.items?.length) {
    elements["secrets-list"].replaceChildren(emptyBlock("Keine Secrets angelegt."));
    return;
  }
  elements["secrets-list"].replaceChildren(...result.items.map((secret) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${secret.referenced ? "tip" : "warning"}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(secret.name)}</strong><small>${escapeHtml(secret.masked)} · ${secret.referenceCount} Referenzen</small></div>`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dependency-action dashboard-action";
    button.textContent = "Löschen";
    button.addEventListener("click", () => deleteSecret(secret.name));
    item.append(button);
    return item;
  }));
}

async function loadSecrets() {
  const result = await api("api/secrets");
  renderSecrets(result);
  return result;
}

async function openSecretsPage() {
  closePages();
  elements["secrets-page"].classList.remove("hidden");
  elements["secrets-button"].classList.add("active");
  try { await loadSecrets(); } catch (error) { toast(error.message, "error"); }
}

async function saveSecret() {
  try {
    const result = await api("api/secrets", {
      method: "POST",
      body: JSON.stringify({ name: elements["secret-name"].value.trim(), value: elements["secret-value"].value }),
    });
    elements["secret-value"].value = "";
    renderSecrets(result);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function deleteSecret(name) {
  if (!confirm(`Secret ${name} löschen? Bestehende !secret-Referenzen können danach brechen.`)) return;
  try {
    const result = await api("api/secrets", { method: "DELETE", body: JSON.stringify({ name }) });
    renderSecrets(result);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function convertSecret() {
  try {
    const result = await api("api/secrets/convert", {
      method: "POST",
      body: JSON.stringify({
        path: elements["secret-convert-path"].value.trim(),
        line: Number(elements["secret-convert-line"].value),
        key: elements["secret-convert-key"].value.trim(),
        name: elements["secret-convert-name"].value.trim(),
        value: elements["secret-convert-value"].value,
      }),
    });
    elements["secret-convert-value"].value = "";
    renderSecrets(result);
    await refreshFiles();
    if (state.selected) await openFile(state.selected.path, true);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
}

function renderPreflight(result) {
  state.preflight = result;
  elements["preflight-summary"].textContent = result.ready
    ? `Bereit · ${result.warnings} Warnungen`
    : `${result.blockers} Blocker · ${result.warnings} Warnungen`;
  const stats = [
    [result.blockers || 0, "Blocker"],
    [result.warnings || 0, "Warnungen"],
    [result.summary?.yamlErrors || 0, "YAML-Fehler"],
    [result.summary?.securityErrors || 0, "Security-Fehler"],
    [result.summary?.remoteConfigured ? "Ja" : "Nein", "Remote"],
  ];
  elements["preflight-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  elements["preflight-list"].replaceChildren(...(result.checks || []).map((check) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${check.status === "error" ? "error" : check.status === "warning" ? "warning" : "tip"}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(check.title)}</strong><small>${escapeHtml(check.message || "")}</small></div>`;
    return item;
  }));
}

async function loadPreflight() {
  elements["preflight-summary"].textContent = "Preflight läuft …";
  const result = await api("api/preflight");
  renderPreflight(result);
  return result;
}

async function openPreflightPage() {
  closePages();
  elements["preflight-page"].classList.remove("hidden");
  elements["preflight-button"].classList.add("active");
  try { await loadPreflight(); } catch (error) { toast(error.message, "error"); }
}

function renderEntityHealth(result) {
  if (!result) return;
  state.entityHealth = result;
  const summary = result.summary || {};
  elements["entity-health-summary"].textContent = result.available
    ? `${summary.referenced} referenziert · ${summary.unknown} unbekannt · ${summary.unavailable} unavailable · ${summary.disabled} deaktiviert`
    : result.message || "Home-Assistant-States sind lokal nicht verfügbar.";
  const stats = [
    [summary.referenced || 0, "Referenziert"],
    [summary.known || 0, "HA-States"],
    [summary.unknown || 0, "Unbekannt"],
    [summary.unavailable || 0, "Unavailable"],
    [summary.unused || 0, "Nicht genutzt"],
  ];
  elements["entity-health-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  const filter = elements["entity-health-filter"].value;
  const items = result[filter] || [];
  if (!items.length) {
    elements["entity-health-list"].replaceChildren(emptyBlock("Keine Entities in dieser Kategorie."));
    return;
  }
  elements["entity-health-list"].replaceChildren(...items.map((entity) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${filter === "unknown" || filter === "unavailable" ? "warning" : "tip"}`;
    const uses = entity.uses || [];
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(entity.entityId)}</strong><small>${escapeHtml(entity.name || entity.state || `${entity.count || 0} Verwendungen`)}</small><small>${escapeHtml(uses.slice(0, 3).map((use) => `${use.path || ""}${use.line ? `:${use.line}` : ""}`).join(" · "))}</small></div>`;
    if (uses[0]?.path) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency-action dashboard-action";
      button.textContent = "Öffnen";
      button.addEventListener("click", () => openManagedPath(uses[0].path, uses[0].line));
      item.append(button);
    }
    return item;
  }));
}

async function loadEntityHealth() {
  elements["entity-health-summary"].textContent = "Entity-Health wird geladen …";
  const result = await api("api/entity-health");
  renderEntityHealth(result);
  return result;
}

async function openEntityHealthPage() {
  closePages();
  elements["entity-health-page"].classList.remove("hidden");
  elements["entity-health-button"].classList.add("active");
  try { await loadEntityHealth(); } catch (error) { toast(error.message, "error"); }
}

function databaseEntityMessage(entity, filter) {
  if (filter === "attributeHeavy") {
    return `${bytesLabel(entity.attributeBytes)} Attribute · ${entity.changes || 0} Änderungen`;
  }
  if (filter === "badStateEntities") {
    return `${entity.lastState || "unknown"} · ${entity.badStates || 0}/${entity.changes || 0} kritische Zustände`;
  }
  return `${entity.changes || 0} Änderungen · ${bytesLabel(entity.attributeBytes)} Attribute`;
}

function renderDatabaseEntities(result) {
  const entities = result.entities || {};
  const summary = entities.summary || {};
  elements["database-entities-summary"].textContent = `${summary.entities || 0} Entities · ${summary.changes || 0} State-Änderungen · ${summary.badStateEntities || 0} auffällig`;
  const filter = elements["database-entity-filter"].value;
  const items = entities[filter] || [];
  if (!result.available) {
    elements["database-entity-list"].replaceChildren(emptyBlock(result.message || "Recorder-Datenbank nicht verfügbar."));
    return;
  }
  if (!items.length) {
    elements["database-entity-list"].replaceChildren(emptyBlock("Keine Entities in dieser Kategorie."));
    return;
  }
  elements["database-entity-list"].replaceChildren(...items.map((entity) => {
    const item = document.createElement("div");
    const noisy = filter === "noisy" && (entity.changes || 0) >= 1000;
    item.className = `dashboard-finding ${filter === "badStateEntities" || noisy ? "warning" : "tip"}`;
    const suggestion = noisy ? "recorder.exclude oder geringere Update-Frequenz prüfen" : `${entity.firstSeen || "?"} bis ${entity.lastSeen || "?"}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(entity.entityId || "")}</strong><small>${escapeHtml(databaseEntityMessage(entity, filter))}</small><small>${escapeHtml(suggestion)}</small></div>`;
    return item;
  }));
}

function renderDatabaseCompare(result) {
  const compare = result.compare || {};
  const summary = compare.summary || {};
  elements["database-compare-summary"].textContent = `${summary.yamlEntities || 0} YAML-Entities · ${summary.databaseEntities || 0} DB-Entities · ${summary.yamlMissingInDatabase || 0} ohne DB-Historie`;
  const filter = elements["database-compare-filter"].value;
  const items = compare[filter] || [];
  if (!result.available && filter !== "yamlMissingInDatabase") {
    elements["database-compare-list"].replaceChildren(emptyBlock(result.message || "Recorder-Datenbank nicht verfügbar."));
    return;
  }
  if (!items.length) {
    elements["database-compare-list"].replaceChildren(emptyBlock("Keine Einträge in dieser Kategorie."));
    return;
  }
  elements["database-compare-list"].replaceChildren(...items.map((entity) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${filter === "databaseOnly" ? "tip" : "warning"}`;
    const uses = entity.uses || [];
    const detail = filter === "databaseOnly"
      ? "Nicht in verwaltetem YAML referenziert"
      : uses.slice(0, 3).map((use) => `${use.path || ""}${use.line ? `:${use.line}` : ""}`).join(" · ") || `${entity.lastState || entity.state || ""}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(entity.entityId || "")}</strong><small>${escapeHtml(detail)}</small></div>`;
    if (uses[0]?.path) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "dependency-action dashboard-action";
      button.textContent = "Öffnen";
      button.addEventListener("click", () => openManagedPath(uses[0].path, uses[0].line));
      item.append(button);
    }
    return item;
  }));
}

function renderDatabaseStatistics(result) {
  const statistics = result.statistics || {};
  const summary = statistics.summary || {};
  elements["database-statistics-summary"].textContent = `${summary.rows || 0} Statistikzeilen · ${summary.gaps || 0} Lücken · ${summary.jumps || 0} Sprung-Kandidaten`;
  const filter = elements["database-statistics-filter"].value;
  const items = statistics[filter] || [];
  if (!result.available) {
    elements["database-statistics-list"].replaceChildren(emptyBlock(result.message || "Recorder-Datenbank nicht verfügbar."));
    return;
  }
  if (!items.length) {
    elements["database-statistics-list"].replaceChildren(emptyBlock("Keine Statistik-Hinweise in dieser Kategorie."));
    return;
  }
  elements["database-statistics-list"].replaceChildren(...items.map((entry) => {
    const item = document.createElement("div");
    item.className = "dashboard-finding warning";
    const title = entry.statisticId || entry.statistic_id || "Statistik";
    const detail = filter === "gaps"
      ? `${entry.table} · ${entry.gaps} Lücken · größte Lücke ${entry.maxGapSeconds || 0}s`
      : filter === "jumps"
        ? `${entry.table} · größter Sprung ${entry.maxDelta}`
        : filter === "unitChanges"
          ? `${entry.units} verschiedene Einheiten`
          : `has_mean=${entry.has_mean} · has_sum=${entry.has_sum}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(String(title))}</strong><small>${escapeHtml(String(detail))}</small></div>`;
    return item;
  }));
}

function renderDatabaseTables(result) {
  const health = result.health || {};
  const tables = health.tables || [];
  const sizes = Object.fromEntries((health.largestTables || []).map((table) => [table.name, table.bytes]));
  elements["database-tables-summary"].textContent = `${tables.length} Tabellen · quick_check: ${health.quickCheck || "n/a"}`;
  if (!result.available) {
    elements["database-table-list"].replaceChildren(emptyBlock(result.message || "Recorder-Datenbank nicht verfügbar."));
    return;
  }
  elements["database-table-list"].replaceChildren(...tables.slice(0, 24).map((table) => {
    const item = document.createElement("div");
    item.className = "import-preview-item";
    const size = sizes[table.name] ? ` · ${bytesLabel(sizes[table.name])}` : "";
    item.innerHTML = `<strong>${escapeHtml(table.name)}</strong><span>${escapeHtml(String(table.rows || 0))} Zeilen${escapeHtml(size)}</span>`;
    return item;
  }));
}

function renderDatabase(result) {
  state.database = result;
  const health = result.health || {};
  const summary = health.summary || {};
  elements["database-summary"].textContent = result.available
    ? `${summary.tables || 0} Tabellen · ${summary.rows || 0} Zeilen · ${bytesLabel(summary.dbSize)}`
    : result.message || "Recorder-Datenbank nicht verfügbar.";
  const stats = [
    [summary.tables || 0, "Tabellen"],
    [summary.rows || 0, "Zeilen"],
    [bytesLabel(summary.dbSize), "DB-Größe"],
    [bytesLabel(summary.walSize), "WAL"],
    [health.quickCheck || "n/a", "quick_check"],
  ];
  elements["database-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  renderDatabaseTables(result);
  renderDatabaseEntities(result);
  renderDatabaseCompare(result);
  renderDatabaseStatistics(result);
}

async function loadDatabase() {
  elements["database-summary"].textContent = "Datenbankanalyse wird geladen …";
  const result = await api("api/database");
  renderDatabase(result);
  return result;
}

async function openDatabasePage() {
  closePages();
  elements["database-page"].classList.remove("hidden");
  elements["database-button"].classList.add("active");
  try { await loadDatabase(); } catch (error) { toast(error.message, "error"); }
}

function renderDatabaseQueryResult(result) {
  elements["database-query-summary"].textContent = `${result.rowCount || 0} Zeilen${result.truncated ? " · gekürzt" : ""}`;
  const columns = result.columns || [];
  const rows = result.rows || [];
  if (!columns.length) {
    elements["database-query-result"].replaceChildren(emptyBlock("Keine Spalten im Ergebnis."));
    return;
  }
  const table = document.createElement("table");
  table.className = "documentation-table database-result-table";
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>${columns.map((column) => `<th>${escapeHtml(String(column))}</th>`).join("")}</tr>`;
  const tbody = document.createElement("tbody");
  tbody.innerHTML = rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(String(row[column] ?? ""))}</td>`).join("")}</tr>`).join("");
  table.append(thead, tbody);
  const wrap = document.createElement("div");
  wrap.className = "documentation-table-wrap";
  wrap.append(table);
  elements["database-query-result"].replaceChildren(wrap);
}

async function runDatabaseQuery() {
  elements["database-query-run"].disabled = true;
  elements["database-query-summary"].textContent = "SQL läuft …";
  try {
    const result = await api("api/database/query", {
      method: "POST",
      body: JSON.stringify({
        sql: elements["database-query"].value,
        limit: elements["database-query-limit"].value,
      }),
    });
    renderDatabaseQueryResult(result);
  } catch (error) {
    elements["database-query-summary"].textContent = error.message;
    elements["database-query-result"].replaceChildren(emptyBlock(error.message));
    toast(error.message, "error");
  } finally {
    elements["database-query-run"].disabled = false;
  }
}

function renderBackupStats(result) {
  const summary = result.summary || {};
  elements["backups-summary"].textContent = `${summary.backups || 0} Backups · ${summary.snapshots || 0} Snapshots · ${summary.databaseBackups || 0} DB-Backups`;
  const stats = [
    [summary.fileBackups || 0, "Datei-Backups"],
    [summary.snapshots || 0, "Snapshots"],
    [summary.databaseBackups || 0, "DB-Backups"],
    [summary.pinned || 0, "Gepinnt"],
    [bytesLabel(summary.size || 0), "Speicher"],
  ];
  elements["backups-stats"].innerHTML = stats.map(([value, label]) => `<div class="quality-stat"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
}

function backupItemElement(backup) {
  const item = document.createElement("div");
  item.className = `dashboard-finding ${backup.type === "snapshot" ? "tip" : "warning"}`;
  const type = backup.type === "snapshot" ? "Snapshot" : "Datei";
  const source = backup.source?.relative || backup.summary?.files || "";
  item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(type)} ${escapeHtml(backup.id)}</strong><small>${escapeHtml(backup.created || "")} · ${bytesLabel(backup.size)} · ${backup.pinned ? "gepinnt" : "nicht gepinnt"}</small><small>${escapeHtml(String(source || ""))}</small></div>`;
  const actions = document.createElement("div");
  actions.className = "dashboard-finding-actions";
  if (backup.type === "snapshot") {
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "dependency-action dashboard-action";
    preview.textContent = "Prüfen";
    preview.addEventListener("click", () => previewSnapshotRestore(backup.id));
    actions.append(preview);
  }
  const pin = document.createElement("button");
  pin.type = "button";
  pin.className = "dependency-action dashboard-action";
  pin.textContent = backup.pinned ? "Lösen" : "Pinnen";
  pin.addEventListener("click", () => setBackupPin(backup.id, !backup.pinned));
  actions.append(pin);
  item.append(actions);
  return item;
}

function renderBackupList(result) {
  const filter = elements["backup-filter"].value;
  const items = (result.backups || []).filter((backup) => !filter || backup.type === filter);
  elements["backup-list-summary"].textContent = `${items.length} Einträge · Aufbewahrung ${result.retention?.count || 0} Stände`;
  if (!items.length) {
    elements["backup-list"].replaceChildren(emptyBlock("Keine Backups in dieser Kategorie."));
    return;
  }
  elements["backup-list"].replaceChildren(...items.map(backupItemElement));
}

function renderDatabaseBackupList(result) {
  const items = result.databaseBackups || [];
  elements["backup-database-summary"].textContent = `${items.length} konsistente SQLite-Backups`;
  if (!items.length) {
    elements["backup-database-list"].replaceChildren(emptyBlock("Noch keine Recorder-Datenbank-Backups."));
    return;
  }
  elements["backup-database-list"].replaceChildren(...items.map((backup) => {
    const item = document.createElement("div");
    item.className = "dashboard-finding tip";
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(backup.id)}</strong><small>${escapeHtml(backup.created || "")} · ${bytesLabel(backup.size)}</small><small>${escapeHtml(backup.source?.path || "")}</small></div>`;
    return item;
  }));
}

function renderBackupIntegrity(result) {
  const integrity = result.integrity || {};
  const summary = integrity.summary || {};
  elements["backup-integrity-summary"].textContent = `${summary.errors || 0} Fehler · ${summary.warnings || 0} Warnungen`;
  const findings = integrity.findings || [];
  if (!findings.length) {
    elements["backup-integrity-list"].replaceChildren(emptyBlock("Alle geprüften Backups sind plausibel."));
    return;
  }
  elements["backup-integrity-list"].replaceChildren(...findings.map((finding) => {
    const item = document.createElement("div");
    item.className = `dashboard-finding ${finding.severity || "warning"}`;
    item.innerHTML = `<span class="finding-dot"></span><div><strong>${escapeHtml(finding.title || finding.code || "Backup-Hinweis")}</strong><small>${escapeHtml(finding.message || "")}</small></div>`;
    return item;
  }));
}

function renderSnapshotPreview(preview) {
  state.snapshotPreview = preview;
  elements["backup-restore-apply"].disabled = !preview.valid;
  elements["backup-restore-summary"].textContent = preview.valid
    ? `${preview.summary.files} Dateien geprüft · ${preview.summary.warnings} Warnungen`
    : `${preview.summary.errors} Fehler · Restore blockiert`;
  const rows = [
    ...(preview.files || []).map((file) => ({ title: file.path, detail: `${file.exists ? "überschreibt" : "neu"} · ${bytesLabel(file.size)}`, severity: "tip" })),
    ...(preview.errors || []).map((error) => ({ title: error.path, detail: error.message, severity: "error" })),
    ...((preview.conflicts?.findings || []).map((finding) => ({ title: finding.title, detail: finding.message, severity: finding.severity }))),
  ];
  if (!rows.length) {
    elements["backup-restore-list"].replaceChildren(emptyBlock("Keine Dateien im Snapshot gefunden."));
    return;
  }
  elements["backup-restore-list"].replaceChildren(...rows.map((row) => {
    const item = document.createElement("div");
    item.className = "import-preview-item";
    item.innerHTML = `<strong>${escapeHtml(row.title || "")}</strong><span>${escapeHtml(row.detail || "")}</span>`;
    return item;
  }));
}

function renderBackups(result) {
  state.backups = result;
  renderBackupStats(result);
  renderBackupList(result);
  renderDatabaseBackupList(result);
  renderBackupIntegrity(result);
}

async function loadBackups() {
  elements["backups-summary"].textContent = "Backup-Center wird geladen …";
  const result = await api("api/backups/overview");
  renderBackups(result);
  return result;
}

async function openBackupsPage() {
  closePages();
  elements["backups-page"].classList.remove("hidden");
  elements["backups-button"].classList.add("active");
  try { await loadBackups(); } catch (error) { toast(error.message, "error"); }
}

async function setBackupPin(id, pinned) {
  try {
    const result = await api("api/backups/pin", {
      method: "POST",
      body: JSON.stringify({ id, pinned }),
    });
    renderBackups(result);
  } catch (error) { toast(error.message, "error"); }
}

async function createSnapshotBackup() {
  elements["backup-snapshot-create"].disabled = true;
  try {
    const result = await api("api/backups/snapshot", {
      method: "POST",
      body: JSON.stringify({ secretsMode: "masked" }),
    });
    renderBackups(result.overview);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
  finally { elements["backup-snapshot-create"].disabled = false; }
}

async function createRecorderBackup() {
  elements["backup-database-create"].disabled = true;
  try {
    const result = await api("api/backups/database", { method: "POST", body: "{}" });
    renderBackups(result.overview);
    toast(result.message, "success");
  } catch (error) { toast(error.message, "error"); }
  finally { elements["backup-database-create"].disabled = false; }
}

async function previewSnapshotRestore(id) {
  try {
    const preview = await api("api/backups/snapshot/restore-preview", {
      method: "POST",
      body: JSON.stringify({ id }),
    });
    renderSnapshotPreview(preview);
  } catch (error) { toast(error.message, "error"); }
}

async function restoreSnapshotBackup() {
  const preview = state.snapshotPreview;
  if (!preview || !preview.valid) return;
  if (!confirm(`Snapshot ${preview.id} mit ${preview.summary.files} Dateien wiederherstellen? Die aktuellen Dateien werden vorher gesichert.`)) return;
  elements["backup-restore-apply"].disabled = true;
  try {
    const result = await api("api/backups/snapshot/restore", {
      method: "POST",
      body: JSON.stringify({ id: preview.id, stateVersion: preview.stateVersion }),
    });
    state.snapshotPreview = null;
    renderBackups(result.overview);
    elements["backup-restore-list"].replaceChildren(emptyBlock(result.message));
    elements["backup-restore-summary"].textContent = result.message;
    await refreshFiles();
    toast(result.message, "success");
  } catch (error) {
    elements["backup-restore-apply"].disabled = false;
    toast(error.message, "error");
  }
}

function renderTraces(result) {
  if (!result) return;
  state.traces = result;
  if (!result.available) {
    elements["traces-summary"].textContent = result.message || "Trace-API ist nicht verfügbar.";
    elements["trace-run-list"].replaceChildren();
    elements["trace-list"].replaceChildren(emptyBlock(elements["traces-summary"].textContent));
    return;
  }
  const term = elements["trace-search"].value.trim().toLocaleLowerCase("de");
  const domain = elements["trace-domain"].value;
  const entries = (result.entries || []).filter((item) => {
    const haystack = `${item.alias} ${item.entityId} ${item.state} ${item.error} ${item.path}`.toLocaleLowerCase("de");
    return (!domain || item.domain === domain) && (!term || haystack.includes(term));
  });
  elements["traces-summary"].textContent = `${result.summary.objects} Objekte · ${result.summary.traces} Traces · ${result.summary.errors} Fehler`;
  elements["trace-run-list"].replaceChildren(...(result.objects || []).slice(0, 80).map((object) => {
    const item = document.createElement("div");
    item.className = "trace-run-item";
    item.innerHTML = `<span><strong>${escapeHtml(object.alias || object.entityId)}</strong><small>${escapeHtml(object.entityId)} · ${escapeHtml(object.path || "")}</small></span>`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dependency-action";
    button.textContent = "Testlauf";
    button.addEventListener("click", () => runHaObjectTest(object, button));
    item.append(button);
    return item;
  }));
  if (!entries.length) {
    elements["trace-list"].replaceChildren(emptyBlock("Keine Trace-Einträge gefunden."));
    return;
  }
  elements["trace-list"].replaceChildren(...entries.map((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `trace-item ${entry.error ? "error" : ""}`;
    button.innerHTML = `<span><strong>${escapeHtml(entry.alias || entry.entityId)}</strong><small>${escapeHtml(entry.entityId)} · ${escapeHtml(entry.timestamp || "ohne Zeit")}</small></span><span>${escapeHtml(entry.state || "Trace")}</span><small>${escapeHtml(entry.error || entry.lastStep || "")}</small>`;
    button.addEventListener("click", () => loadTraceDetail(entry));
    return button;
  }));
}

async function loadTraces() {
  elements["traces-summary"].textContent = "Traces werden geladen …";
  const result = await api("api/traces");
  renderTraces(result);
  return result;
}

async function openTracesPage() {
  closePages();
  elements["traces-page"].classList.remove("hidden");
  elements["traces-button"].classList.add("active");
  try { await loadTraces(); } catch (error) { toast(error.message, "error"); }
}

async function runHaObjectTest(object, button) {
  const originalLabel = button?.textContent || "Testlauf";
  if (button) {
    button.disabled = true;
    button.textContent = "Läuft…";
  }
  elements["trace-detail-summary"].textContent = `${object.entityId} wird gestartet …`;
  elements["trace-detail"].textContent = "";
  try {
    const result = await api("api/ha-object/run", {
      method: "POST",
      body: JSON.stringify({
        domain: object.domain,
        entityId: object.entityId,
        skipCondition: true,
      }),
    });
    toast(result.message, "success");
    let latest = null;
    for (let attempt = 0; attempt < 4 && !latest; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, attempt === 0 ? 700 : 1000));
      const traces = await loadTraces();
      latest = traces.entries?.find((entry) => entry.entityId === object.entityId);
    }
    if (latest) {
      await loadTraceDetail(latest);
    } else {
      elements["trace-detail-summary"].textContent = "Testlauf gestartet, aber noch kein neuer Trace gefunden.";
      elements["trace-detail"].textContent = JSON.stringify(result.traceHint || result, null, 2);
    }
  } catch (error) {
    elements["trace-detail-summary"].textContent = error.message;
    elements["trace-detail"].textContent = JSON.stringify(error.details || { error: error.message }, null, 2);
    toast(error.message, "error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }
}

async function loadTraceDetail(entry) {
  if (!entry.runId) {
    elements["trace-detail-summary"].textContent = "Dieser Trace hat keine Run-ID.";
    elements["trace-detail"].textContent = JSON.stringify(entry.summary || entry, null, 2);
    return;
  }
  try {
    const result = await api(`api/trace?domain=${encodeURIComponent(entry.domain)}&itemId=${encodeURIComponent(entry.itemId)}&runId=${encodeURIComponent(entry.runId)}`);
    elements["trace-detail-summary"].textContent = `${entry.entityId} · ${entry.runId}`;
    elements["trace-detail"].textContent = JSON.stringify(result.trace, null, 2);
  } catch (error) {
    elements["trace-detail-summary"].textContent = error.message;
    elements["trace-detail"].textContent = JSON.stringify(entry.summary || entry, null, 2);
  }
}

async function renderTemplate() {
  const template = elements["template-input"].value;
  elements["template-render"].disabled = true;
  elements["template-result"].className = "template-result";
  elements["template-result"].textContent = "Template wird gerendert …";
  try {
    const result = await api("api/template/render", {
      method: "POST",
      body: JSON.stringify({ template }),
    });
    elements["template-result"].className = `template-result ${result.success ? "valid" : "invalid"}`;
    elements["template-result"].textContent = result.success ? result.result : result.message;
    elements["template-entities"].replaceChildren(...(result.entities || []).map((entity) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tag-filter";
      button.textContent = entity;
      button.addEventListener("click", () => insertText(entity));
      return button;
    }));
  } catch (error) {
    elements["template-result"].className = "template-result invalid";
    elements["template-result"].textContent = error.message;
  } finally {
    elements["template-render"].disabled = false;
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
    if (state.settings?.afterSave === "dashboard") {
      closeResourceEditor();
      await openDashboard();
    }
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
    scheduleFlow();
    loadDependencies().catch((error) => toast(error.message, "error"));
    renderFiles();
    elements.sidebar.classList.remove("open");
  } catch (error) { toast(error.message, "error"); }
}

function impactCodes(values = []) {
  if (!values.length) return document.createTextNode("Keine");
  const fragment = document.createDocumentFragment();
  values.slice(0, 20).forEach((value) => {
    const code = document.createElement("code");
    code.textContent = value;
    fragment.append(code);
  });
  if (values.length > 20) fragment.append(document.createTextNode(` +${values.length - 20} weitere`));
  return fragment;
}

function impactSection(title, values) {
  const section = document.createElement("section");
  section.className = "impact-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const body = document.createElement("div");
  body.append(impactCodes(values));
  section.append(heading, body);
  return section;
}

function renderImpact(impact) {
  const summary = impact.summary || {};
  const cards = [
    [summary.addedEntities || 0, "Entities hinzu"],
    [summary.removedEntities || 0, "Entities weg"],
    [summary.addedScripts || 0, "Scripts hinzu"],
    [summary.removedScripts || 0, "Scripts weg"],
    [summary.incomingReferences || 0, "Eingehende Bezüge"],
    [summary.addedSecrets || 0, "Secrets hinzu"],
    [summary.addedBlueprints || 0, "Blueprints"],
    [summary.traceCandidates || 0, "Trace-Kandidaten"],
  ];
  const grid = document.createElement("div");
  grid.className = "impact-grid";
  grid.innerHTML = cards.map(([value, label]) => `<div class="impact-card"><strong>${escapeHtml(String(value))}</strong><span>${escapeHtml(label)}</span></div>`).join("");
  const findings = document.createElement("section");
  findings.className = "impact-section";
  findings.innerHTML = `<h3>Hinweise</h3>${impact.findings?.length ? impact.findings.map((item) => `<p><strong>${escapeHtml(item.title)}</strong><br><small>${escapeHtml(item.message)}</small></p>`).join("") : "<p><small>Keine riskanten Auswirkungen erkannt.</small></p>"}`;
  elements["impact-summary"].textContent = `${impact.path} · Risiko: ${impact.risk}`;
  elements["impact-risk"].textContent = impact.risk === "error" ? "Fehler vor dem Speichern prüfen" : impact.risk === "warning" ? "Warnungen prüfen" : "Impact geprüft";
  elements["impact-confirm"].textContent = impact.risk === "error" ? "Trotz Fehler speichern" : "Speichern";
  elements["impact-body"].replaceChildren(
    grid,
    findings,
    impactSection("Neue Entities", impact.entities?.added || []),
    impactSection("Entfernte Entities", impact.entities?.removed || []),
    impactSection("Unbekannte Entities", impact.entities?.unknown || []),
    impactSection("Betroffene Scripts/Traces", impact.traces || []),
    impactSection("Secrets", [...(impact.secrets?.added || []).map((item) => `+ ${item}`), ...(impact.secrets?.removed || []).map((item) => `- ${item}`)]),
    impactSection("Blueprints", [...(impact.blueprints?.added || []).map((item) => `+ ${item}`), ...(impact.blueprints?.removed || []).map((item) => `- ${item}`)]),
  );
}

function confirmImpact(impact) {
  renderImpact(impact);
  elements["impact-dialog"].showModal();
  return new Promise((resolve) => {
    state.impactResolver = resolve;
  });
}

function resolveImpact(confirmed) {
  if (state.impactResolver) state.impactResolver(confirmed);
  state.impactResolver = null;
  elements["impact-dialog"].close();
}

async function previewSaveImpact() {
  return api("api/impact", {
    method: "POST",
    body: JSON.stringify({
      path: state.selected.path,
      content: elements.editor.value,
      version: state.selected.version,
    }),
  });
}

async function saveCurrent() {
  if (!state.selected || !state.dirty) return;
  elements["save-button"].disabled = true;
  try {
    const impact = await previewSaveImpact();
    const confirmed = await confirmImpact(impact);
    if (!confirmed) {
      elements["save-button"].disabled = false;
      return;
    }
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
    scheduleFlow();
    toastSaveResult(file, "Datei gespeichert.");
    if (state.settings?.afterSave === "dashboard") await openDashboard();
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

function renderFlow(result) {
  state.flow = result;
  if (!result.valid) {
    elements["flow-summary"].className = "analysis-summary invalid";
    elements["flow-summary"].innerHTML = `<strong>Ablaufdiagramm</strong><span>${escapeHtml(result.message || "YAML ist ungültig.")}</span>`;
    elements["flow-diagram"].replaceChildren();
    return;
  }
  const summary = result.summary || { flows: 0, nodes: 0, edges: 0 };
  elements["flow-summary"].className = `analysis-summary ${summary.flows ? "clean" : "checking"}`;
  elements["flow-summary"].innerHTML = `<strong>${summary.flows} Abläufe</strong><span>${summary.nodes} Knoten · ${summary.edges} Verbindungen</span>`;
  if (!result.flows?.length) {
    elements["flow-diagram"].replaceChildren(emptyBlock("Keine Automation- oder Script-Abläufe erkannt."));
    return;
  }
  elements["flow-diagram"].replaceChildren(...result.flows.map((flow) => {
    const card = document.createElement("div");
    card.className = "flow-card";
    const title = document.createElement("strong");
    title.textContent = `${flow.domain}: ${flow.alias}`;
    card.append(title);
    for (const node of flow.nodes) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = `flow-node ${node.type} depth-${Math.min(Number(node.depth || 0), 4)}`;
      const indent = Math.min(Number(node.depth || 0), 4) * 14;
      item.style.marginLeft = `${indent}px`;
      item.style.width = `calc(100% - ${indent}px)`;
      item.innerHTML = `<strong>${escapeHtml(node.label || node.type)}</strong><small>${escapeHtml(node.detail || "")}${node.line ? ` · Zeile ${node.line}` : ""}</small>`;
      item.addEventListener("click", () => jumpToLine(node.line));
      card.append(item);
    }
    return card;
  }));
}

function scheduleFlow() {
  clearTimeout(flowTimer);
  elements["flow-summary"].className = "analysis-summary checking";
  elements["flow-summary"].innerHTML = "<strong>Ablaufdiagramm</strong><span>Analyse läuft …</span>";
  flowTimer = setTimeout(async () => {
    if (!state.selected) return;
    try {
      const result = await api("api/flow", {
        method: "POST",
        body: JSON.stringify({ content: elements.editor.value, path: state.selected.path }),
      });
      renderFlow(result);
    } catch (error) { toast(error.message, "error"); }
  }, 500);
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

function completionRange() {
  const editor = elements.editor;
  const before = editor.value.slice(0, editor.selectionStart);
  const match = before.match(/[A-Za-z0-9_.-]*$/);
  const token = match?.[0] || "";
  return { start: editor.selectionStart - token.length, end: editor.selectionStart, token };
}

function completionCandidates(token) {
  const term = token.toLocaleLowerCase("de");
  const items = [];
  if (state.helpers?.entities) {
    for (const entity of state.helpers.entities) {
      items.push({
        value: entity.entity_id,
        label: entity.entity_id,
        detail: entity.name || "Entität",
      });
    }
  }
  if (state.helpers?.services) {
    for (const service of state.helpers.services) {
      items.push({ value: service, label: service, detail: "Dienst" });
    }
  }
  for (const script of state.dependencies?.scripts || []) {
    items.push({ value: script.entityId, label: script.entityId, detail: script.alias || "Script" });
  }
  for (const snippet of snippets) {
    items.push({ value: snippet.text, label: snippet.name, detail: "Baustein" });
  }
  const filtered = items
    .filter((item) => !term || `${item.label} ${item.detail}`.toLocaleLowerCase("de").includes(term))
    .slice(0, 12);
  return filtered;
}

function renderCompletion() {
  const popover = elements["completion-popover"];
  if (!state.completion.open || !state.completion.items.length) {
    popover.classList.add("hidden");
    popover.replaceChildren();
    return;
  }
  popover.classList.remove("hidden");
  popover.replaceChildren(...state.completion.items.map((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `completion-item${index === state.completion.index ? " active" : ""}`;
    button.innerHTML = `<strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.detail)}</span>`;
    button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      acceptCompletion(index);
    });
    return button;
  }));
}

function openCompletion() {
  if (!state.selected) return;
  const range = completionRange();
  const items = completionCandidates(range.token);
  if (!items.length) {
    hideCompletion();
    toast("Keine passenden Vorschläge gefunden.", "error");
    return;
  }
  state.completion = { open: true, items, index: 0, start: range.start, end: range.end };
  renderCompletion();
}

function hideCompletion() {
  state.completion.open = false;
  renderCompletion();
}

function moveCompletion(delta) {
  if (!state.completion.open) return;
  const count = state.completion.items.length;
  state.completion.index = (state.completion.index + delta + count) % count;
  renderCompletion();
}

function acceptCompletion(index = state.completion.index) {
  if (!state.completion.open) return;
  const item = state.completion.items[index];
  if (!item) return;
  const editor = elements.editor;
  editor.setRangeText(item.value, state.completion.start, state.completion.end, "end");
  hideCompletion();
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
    elements["api-notice"].classList.toggle("hidden", state.helpers.available !== false);
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
    openScriptManager();
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

elements.editor.addEventListener("input", () => { hideCompletion(); updateEditorRendering(); setDirty(); scheduleValidation(); scheduleFlow(); });
elements.editor.addEventListener("scroll", syncScroll);
elements.editor.addEventListener("click", updateCursor);
elements.editor.addEventListener("keyup", updateCursor);
elements.editor.addEventListener("keydown", (event) => {
  if (state.completion.open) {
    if (event.key === "ArrowDown") { event.preventDefault(); moveCompletion(1); return; }
    if (event.key === "ArrowUp") { event.preventDefault(); moveCompletion(-1); return; }
    if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); acceptCompletion(); return; }
    if (event.key === "Escape") { event.preventDefault(); hideCompletion(); return; }
  }
  if ((event.ctrlKey || event.metaKey) && event.key === " ") {
    event.preventDefault();
    openCompletion();
    return;
  }
  if (event.key === "Tab") {
    event.preventDefault();
    elements.editor.setRangeText("  ", elements.editor.selectionStart, elements.editor.selectionEnd, "end");
    elements.editor.dispatchEvent(new Event("input"));
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); saveCurrent(); }
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    openSearchReplaceDialog();
  }
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
elements["open-files-button"].addEventListener("click", openFileBrowser);
elements["empty-open-files-button"].addEventListener("click", openFileBrowser);
elements["file-browser-close"].addEventListener("click", closeFileBrowser);
elements["file-browser-new"].addEventListener("click", () => {
  openNewDialog();
});
elements["package-files-button"].addEventListener("click", openFileBrowser);
elements["dashboard-button"].addEventListener("click", openDashboard);
elements["dashboard-close"].addEventListener("click", openFileBrowser);
elements["dashboard-refresh"].addEventListener("click", loadDashboard);
elements["dashboard-show-suppressed"].addEventListener("change", () => {
  state.dashboardShowSuppressed = elements["dashboard-show-suppressed"].checked;
  renderDashboard(state.dashboard);
});
elements["review-button"].addEventListener("click", openReviewPage);
elements["review-close"].addEventListener("click", openFileBrowser);
elements["review-add-current"].addEventListener("click", addCurrentToReview);
elements["review-clear"].addEventListener("click", () => {
  state.reviewChanges = [];
  renderReviewBundle();
});
elements["review-preview"].addEventListener("click", previewReview);
elements["review-apply"].addEventListener("click", applyReview);
elements["lint-button"].addEventListener("click", openLintPage);
elements["lint-close"].addEventListener("click", openFileBrowser);
elements["lint-refresh"].addEventListener("click", () => loadLint().catch((error) => toast(error.message, "error")));
elements["lint-save"].addEventListener("click", saveLintRules);
elements["graph-button"].addEventListener("click", openGraphPage);
elements["graph-close"].addEventListener("click", openFileBrowser);
elements["graph-refresh"].addEventListener("click", () => loadGraph().catch((error) => toast(error.message, "error")));
elements["graph-search"].addEventListener("input", () => state.graph && renderGraph(state.graph));
elements["graph-type"].addEventListener("change", () => state.graph && renderGraph(state.graph));
elements["compatibility-button"].addEventListener("click", openCompatibilityPage);
elements["compatibility-close"].addEventListener("click", openFileBrowser);
elements["compatibility-refresh"].addEventListener("click", () => loadCompatibility().catch((error) => toast(error.message, "error")));
elements["git-page-button"].addEventListener("click", openGitPage);
elements["git-page-close"].addEventListener("click", openFileBrowser);
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
elements["settings-button"].addEventListener("click", openSettingsDialog);
elements["settings-close"].addEventListener("click", () => elements["settings-dialog"].close());
elements["settings-dialog"].addEventListener("cancel", () => elements["settings-dialog"].close());
elements["settings-save"].addEventListener("click", saveSettings);
elements["settings-reload"].addEventListener("click", () => fillSettings());
elements["trash-button"].addEventListener("click", openTrashDialog);
elements["trash-close"].addEventListener("click", () => elements["trash-dialog"].close());
elements["trash-refresh"].addEventListener("click", () => loadTrash().catch((error) => toast(error.message, "error")));
elements["trash-purge-all"].addEventListener("click", purgeAllTrash);
elements["trash-dialog"].addEventListener("cancel", () => elements["trash-dialog"].close());
elements["transfer-button"].addEventListener("click", openTransferDialog);
elements["transfer-close"].addEventListener("click", () => elements["transfer-dialog"].close());
elements["transfer-dialog"].addEventListener("cancel", () => elements["transfer-dialog"].close());
elements["objects-button"].addEventListener("click", openObjectsDialog);
elements["objects-close"].addEventListener("click", openFileBrowser);
elements["objects-refresh"].addEventListener("click", loadHaObjects);
elements["object-search"].addEventListener("input", renderHaObjects);
elements["object-domain"].addEventListener("change", renderHaObjects);
elements["blueprints-button"].addEventListener("click", openBlueprintsPage);
elements["blueprints-close"].addEventListener("click", openFileBrowser);
elements["blueprints-refresh"].addEventListener("click", () => loadBlueprints().catch((error) => toast(error.message, "error")));
elements["blueprint-search"].addEventListener("input", renderBlueprints);
elements["blueprint-domain"].addEventListener("change", renderBlueprints);
elements["blueprint-instantiate"].addEventListener("click", instantiateSelectedBlueprint);
elements["blueprint-import"].addEventListener("click", importBlueprint);
elements["blueprint-from-create"].addEventListener("click", createBlueprintFromYaml);
elements["documentation-button"].addEventListener("click", openDocumentationPage);
elements["documentation-close"].addEventListener("click", openFileBrowser);
elements["documentation-refresh"].addEventListener("click", loadDocumentation);
elements["documentation-save"].addEventListener("click", saveDocumentation);
elements["documentation-search"].addEventListener("input", renderDocumentationHtml);
document.querySelectorAll(".documentation-tab").forEach((tab) => tab.addEventListener("click", () => {
  state.documentationTab = tab.dataset.docTab || "overview";
  renderDocumentationHtml();
}));
elements["security-button"].addEventListener("click", openSecurityPage);
elements["security-close"].addEventListener("click", openFileBrowser);
elements["security-refresh"].addEventListener("click", () => loadSecurity().catch((error) => toast(error.message, "error")));
elements["refactor-button"].addEventListener("click", openRefactorPage);
elements["refactor-close"].addEventListener("click", openFileBrowser);
elements["refactor-preview"].addEventListener("click", previewRefactor);
elements["refactor-apply"].addEventListener("click", applyRefactor);
elements["refactor-kind"].addEventListener("change", () => {
  const placeholders = {
    entity: ["light.alt", "light.neu"],
    helper_entity: ["input_boolean.alt", "input_boolean.neu"],
    scene: ["scene.abend_alt", "scene.abend_neu"],
    automation: ["automation.alt", "automation.neu"],
    device_id: ["device_alt", "device_neu"],
    area_id: ["kueche_alt", "kueche_neu"],
    package: ["licht/alt.yaml", "licht/neu.yaml"],
  };
  const [oldPlaceholder, newPlaceholder] = placeholders[elements["refactor-kind"].value] || placeholders.entity;
  elements["refactor-old"].placeholder = oldPlaceholder;
  elements["refactor-new"].placeholder = newPlaceholder;
  state.refactorPreview = null;
  elements["refactor-apply"].disabled = true;
});
elements["secrets-button"].addEventListener("click", openSecretsPage);
elements["secrets-close"].addEventListener("click", openFileBrowser);
elements["secrets-refresh"].addEventListener("click", () => loadSecrets().catch((error) => toast(error.message, "error")));
elements["secret-save"].addEventListener("click", saveSecret);
elements["secret-convert"].addEventListener("click", convertSecret);
elements["preflight-button"].addEventListener("click", openPreflightPage);
elements["preflight-close"].addEventListener("click", openFileBrowser);
elements["preflight-run"].addEventListener("click", () => loadPreflight().catch((error) => toast(error.message, "error")));
elements["entity-health-button"].addEventListener("click", openEntityHealthPage);
elements["entity-health-close"].addEventListener("click", openFileBrowser);
elements["entity-health-refresh"].addEventListener("click", () => loadEntityHealth().catch((error) => toast(error.message, "error")));
elements["entity-health-filter"].addEventListener("change", () => renderEntityHealth(state.entityHealth));
elements["database-button"].addEventListener("click", openDatabasePage);
elements["database-close"].addEventListener("click", openFileBrowser);
elements["database-refresh"].addEventListener("click", () => loadDatabase().catch((error) => toast(error.message, "error")));
elements["database-entity-filter"].addEventListener("change", () => state.database && renderDatabaseEntities(state.database));
elements["database-compare-filter"].addEventListener("change", () => state.database && renderDatabaseCompare(state.database));
elements["database-statistics-filter"].addEventListener("change", () => state.database && renderDatabaseStatistics(state.database));
elements["database-query-run"].addEventListener("click", runDatabaseQuery);
elements["backups-button"].addEventListener("click", openBackupsPage);
elements["backups-close"].addEventListener("click", openFileBrowser);
elements["backups-refresh"].addEventListener("click", () => loadBackups().catch((error) => toast(error.message, "error")));
elements["backup-filter"].addEventListener("change", () => state.backups && renderBackupList(state.backups));
elements["backup-snapshot-create"].addEventListener("click", createSnapshotBackup);
elements["backup-database-create"].addEventListener("click", createRecorderBackup);
elements["backup-restore-apply"].addEventListener("click", restoreSnapshotBackup);
elements["traces-button"].addEventListener("click", openTracesPage);
elements["traces-close"].addEventListener("click", openFileBrowser);
elements["traces-refresh"].addEventListener("click", () => loadTraces().catch((error) => toast(error.message, "error")));
elements["trace-search"].addEventListener("input", () => renderTraces(state.traces));
elements["trace-domain"].addEventListener("change", () => renderTraces(state.traces));
elements["trace-clear-detail"].addEventListener("click", () => {
  elements["trace-detail-summary"].textContent = "Wähle eine Ausführung aus.";
  elements["trace-detail"].textContent = "";
});
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
elements["diff-changed-only"].addEventListener("change", () => {
  if (state.history.diffResult) {
    renderSideBySideDiff(
      elements["diff-view"],
      elements["diff-placeholder"],
      state.history.diffResult,
      elements["diff-changed-only"].checked,
    );
  }
});
elements["history-dialog"].addEventListener("cancel", () => elements["history-dialog"].close());
elements["git-history-button"].addEventListener("click", () => openGitHistory("package"));
elements["git-history-close"].addEventListener("click", () => elements["git-dialog"].close());
elements["git-history-restore"].addEventListener("click", restoreSelectedGitCommit);
elements["git-diff-changed-only"].addEventListener("change", () => {
  if (state.gitHistory.diffResult) {
    renderSideBySideDiff(
      elements["git-diff-view"],
      elements["git-diff-placeholder"],
      state.gitHistory.diffResult,
      elements["git-diff-changed-only"].checked,
    );
  }
});
elements["git-dialog"].addEventListener("cancel", () => elements["git-dialog"].close());
elements["package-conflicts-button"].addEventListener("click", openPackageConflicts);
elements["conflict-close"].addEventListener("click", () => elements["conflict-dialog"].close());
elements["conflict-dialog"].addEventListener("cancel", () => elements["conflict-dialog"].close());
elements["entity-search"].addEventListener("input", () => renderHelperResults("entity"));
elements["service-search"].addEventListener("input", () => renderHelperResults("service"));
elements["template-render"].addEventListener("click", renderTemplate);
elements["template-input"].addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    renderTemplate();
  }
});
elements["impact-confirm"].addEventListener("click", () => resolveImpact(true));
elements["impact-back"].addEventListener("click", () => resolveImpact(false));
elements["impact-cancel"].addEventListener("click", () => resolveImpact(false));
elements["impact-dialog"].addEventListener("cancel", (event) => {
  event.preventDefault();
  resolveImpact(false);
});
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
document.querySelectorAll(".sidebar-primary-nav .sidebar-nav-item").forEach((button) => {
  button.addEventListener("click", collapseSidebarTools);
});
elements["helpers-toggle"].addEventListener("click", () => elements.helpers.classList.add("open"));
elements["helpers-close"].addEventListener("click", () => elements.helpers.classList.remove("open"));
document.querySelectorAll(".action-menu").forEach((menu) => menu.addEventListener("click", (event) => {
  if (event.target.closest(".action-menu-item")) menu.removeAttribute("open");
}));
document.addEventListener("click", (event) => {
  hideCompletion();
  document.querySelectorAll(".action-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === "f") {
    event.preventDefault();
    openSearchReplaceDialog();
  }
});
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
updateSidebarToolSummary();
Promise.all([loadSettings(), refreshFiles(), loadHelpers(), loadDashboard()]).catch((error) => toast(error.message, "error"));
