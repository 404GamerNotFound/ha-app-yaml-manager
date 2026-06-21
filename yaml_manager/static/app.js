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
  files: [], categories: [], selectedCategory: "Alle", selected: null,
  originalContent: "", originalCategory: "", dirty: false, helpers: null,
};

const elements = Object.fromEntries([
  "sidebar", "sidebar-toggle", "sidebar-close", "file-search", "configuration-status", "categories", "file-list", "file-count", "root-path",
  "empty-state", "empty-new-button", "editor-content", "document-name", "document-path", "dirty-dot", "category-select",
  "duplicate-button", "delete-button", "editor", "highlighting", "line-numbers", "validation-status", "cursor-status",
  "save-button", "new-button", "reload-button", "helpers", "helpers-toggle", "helpers-close", "snippet-list", "api-notice",
  "entity-search", "entity-list", "service-search", "service-list", "new-dialog", "new-form", "new-path", "new-script-id",
  "new-category", "category-options", "create-button", "toast-region",
].map((id) => [id, document.getElementById(id)]));

let validationTimer;

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
  state.dirty = elements.editor.value !== state.originalContent || elements["category-select"].value !== state.originalCategory;
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

function fileMatches(file) {
  const term = elements["file-search"].value.trim().toLocaleLowerCase("de");
  const inCategory = state.selectedCategory === "Alle" || file.category === state.selectedCategory;
  return inCategory && (!term || `${file.path} ${file.category}`.toLocaleLowerCase("de").includes(term));
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
    button.innerHTML = `<span class="file-icon">YML</span><span class="file-label"><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.path)}</span></span>`;
    button.title = file.path;
    button.addEventListener("click", () => openFile(file.path));
    return button;
  }));
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

async function refreshFiles() {
  const data = await api("api/files");
  state.files = data.files;
  state.categories = data.categories;
  elements["root-path"].textContent = data.root;
  renderConfigurationStatus(data.configuration);
  fillCategories(state.selected?.category);
  renderCategories();
  renderFiles();
}

async function openFile(path, force = false) {
  if (!force && state.dirty && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
  try {
    const file = await api(`api/file?path=${encodeURIComponent(path)}`);
    state.selected = file;
    state.originalContent = file.content;
    state.originalCategory = file.category;
    elements.editor.value = file.content;
    elements["document-name"].textContent = path.split("/").at(-1);
    elements["document-path"].textContent = path;
    fillCategories(file.category);
    elements["empty-state"].classList.add("hidden");
    elements["editor-content"].classList.remove("hidden");
    setDirty();
    updateEditorRendering();
    scheduleValidation();
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
      }),
    });
    state.selected = file;
    state.originalContent = file.content;
    state.originalCategory = file.category;
    setDirty();
    await refreshFiles();
    toast("Datei gespeichert", "success");
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

function scheduleValidation() {
  clearTimeout(validationTimer);
  elements["validation-status"].className = "validation-status neutral";
  elements["validation-status"].textContent = "Prüfe …";
  validationTimer = setTimeout(async () => {
    try {
      showValidation(await api("api/validate", { method: "POST", body: JSON.stringify({ content: elements.editor.value }) }));
    } catch (error) { toast(error.message, "error"); }
  }, 450);
}

function jumpToValidationError() {
  const target = Number(elements["validation-status"].dataset.line);
  if (!target) return;
  const lines = elements.editor.value.split("\n");
  const offset = lines.slice(0, target - 1).reduce((sum, line) => sum + line.length + 1, 0);
  elements.editor.focus();
  elements.editor.setSelectionRange(offset, offset + (lines[target - 1]?.length || 0));
  elements.editor.scrollTop = Math.max(0, (target - 4) * 21.45);
  syncScroll();
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
      body: JSON.stringify({ path, content: NEW_TEMPLATE(scriptId), category: elements["new-category"].value || DEFAULT_CATEGORY }),
    });
    elements["new-dialog"].close();
    await refreshFiles();
    await openFile(file.path, true);
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
      body: JSON.stringify({ path, content: elements.editor.value, category: elements["category-select"].value }),
    });
    await refreshFiles();
    await openFile(file.path, true);
    toast("Datei dupliziert", "success");
  } catch (error) { toast(error.message, "error"); }
}

async function deleteCurrent() {
  if (!state.selected || !confirm(`${state.selected.path} löschen? Die Datei wird in den Papierkorb verschoben.`)) return;
  try {
    await api("api/file", { method: "DELETE", body: JSON.stringify({ path: state.selected.path, version: state.selected.version }) });
    state.selected = null; state.dirty = false;
    elements["editor-content"].classList.add("hidden");
    elements["empty-state"].classList.remove("hidden");
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
elements["file-search"].addEventListener("input", renderFiles);
elements["configuration-status"].addEventListener("click", () => {
  const status = elements["configuration-status"];
  const suffix = status.dataset.expected ? ` Erwarteter Eintrag: ${status.dataset.expected.replaceAll("\n", " ")}` : "";
  toast(`${status.dataset.message}${suffix}`, status.classList.contains("configured") ? "success" : "error");
});
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
elements["delete-button"].addEventListener("click", deleteCurrent);
elements["reload-button"].addEventListener("click", reloadScripts);
elements["validation-status"].addEventListener("click", jumpToValidationError);
elements["sidebar-toggle"].addEventListener("click", () => elements.sidebar.classList.add("open"));
elements["sidebar-close"].addEventListener("click", () => elements.sidebar.classList.remove("open"));
elements["helpers-toggle"].addEventListener("click", () => elements.helpers.classList.add("open"));
elements["helpers-close"].addEventListener("click", () => elements.helpers.classList.remove("open"));
document.querySelectorAll(".helper-tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".helper-tab").forEach((item) => item.classList.toggle("active", item === tab));
  document.querySelectorAll(".helper-view").forEach((view) => view.classList.add("hidden"));
  document.getElementById(`tab-${tab.dataset.tab}`).classList.remove("hidden");
}));
window.addEventListener("beforeunload", (event) => { if (state.dirty) event.preventDefault(); });

renderSnippets();
Promise.all([refreshFiles(), loadHelpers()]).catch((error) => toast(error.message, "error"));
