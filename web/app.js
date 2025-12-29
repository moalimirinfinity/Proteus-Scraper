const state = {
  selectors: [],
  mode: "field",
  lastSelector: "",
  previewHtml: "",
  authToken: "",
  csrfToken: "",
};

const dom = {
  status: document.getElementById("status-pill"),
  previewUrl: document.getElementById("preview-url"),
  previewEngine: document.getElementById("preview-engine"),
  previewFrame: document.getElementById("preview-frame"),
  previewHint: document.getElementById("preview-hint"),
  modeField: document.getElementById("mode-field"),
  modeItem: document.getElementById("mode-item"),
  selectedSelector: document.getElementById("selected-selector"),
  schemaId: document.getElementById("schema-id"),
  groupName: document.getElementById("group-name"),
  itemSelector: document.getElementById("item-selector"),
  fieldName: document.getElementById("field-name"),
  fieldSelector: document.getElementById("field-selector"),
  fieldAttribute: document.getElementById("field-attribute"),
  dataType: document.getElementById("data-type"),
  fieldRequired: document.getElementById("field-required"),
  selectorList: document.getElementById("selector-list"),
  previewJson: document.getElementById("preview-json"),
  previewScreenshot: document.getElementById("preview-screenshot"),
  artifactLinks: document.getElementById("artifact-links"),
  quarantineSchema: document.getElementById("quarantine-schema"),
  quarantineList: document.getElementById("quarantine-list"),
  authToken: document.getElementById("auth-token"),
  authStatus: document.getElementById("auth-status"),
  authSave: document.getElementById("auth-save"),
  authClear: document.getElementById("auth-clear"),
};

document.getElementById("load-preview").addEventListener("click", loadPreviewHtml);
document.getElementById("run-preview").addEventListener("click", runPreviewJob);
document.getElementById("add-selector").addEventListener("click", addSelector);
document.getElementById("save-schema").addEventListener("click", saveSchema);
document.getElementById("load-quarantine").addEventListener("click", loadQuarantine);
dom.authSave.addEventListener("click", saveAuthToken);
dom.authClear.addEventListener("click", clearAuthToken);

dom.modeField.addEventListener("click", () => setMode("field"));
dom.modeItem.addEventListener("click", () => setMode("item"));

hydrateAuth();

function setStatus(text, tone = "Idle") {
  dom.status.textContent = `${tone}: ${text}`;
}

function setAuthStatus(text, tone = "Idle") {
  dom.authStatus.textContent = `${tone}: ${text}`;
}

function setMode(mode) {
  state.mode = mode;
  dom.modeField.classList.toggle("active", mode === "field");
  dom.modeItem.classList.toggle("active", mode === "item");
}

function hydrateAuth() {
  state.authToken = localStorage.getItem("proteus_token") || "";
  state.csrfToken = localStorage.getItem("proteus_csrf") || generateToken();
  localStorage.setItem("proteus_csrf", state.csrfToken);
  dom.authToken.value = state.authToken;
  if (state.authToken) {
    setAuthStatus("Connected", "Ready");
    document.cookie = `proteus_token=${encodeURIComponent(state.authToken)}; Path=/; SameSite=Strict`;
  } else {
    setAuthStatus("Not connected", "Idle");
  }
  document.cookie = `proteus_csrf=${state.csrfToken}; Path=/; SameSite=Strict`;
}

function saveAuthToken() {
  const token = dom.authToken.value.trim();
  if (!token) {
    return setAuthStatus("Token required", "Input");
  }
  state.authToken = token;
  localStorage.setItem("proteus_token", token);
  document.cookie = `proteus_token=${encodeURIComponent(token)}; Path=/; SameSite=Strict`;
  setAuthStatus("Connected", "Ready");
}

function clearAuthToken() {
  state.authToken = "";
  localStorage.removeItem("proteus_token");
  dom.authToken.value = "";
  document.cookie = "proteus_token=; Path=/; Max-Age=0";
  setAuthStatus("Cleared", "Idle");
}

function apiFetch(path, options = {}) {
  if (!state.authToken) {
    setAuthStatus("Token required", "Input");
    throw new Error("auth_required");
  }
  const headers = {
    ...(options.headers || {}),
    Authorization: `Bearer ${state.authToken}`,
    "X-Proteus-CSRF": state.csrfToken,
  };
  return fetch(path, { ...options, headers });
}

async function loadPreviewHtml() {
  const url = dom.previewUrl.value.trim();
  if (!url) return setStatus("Enter a URL", "Input");
  setStatus("Loading HTML", "Working");
  dom.previewHint.textContent = "";
  try {
    const payload = {
      url,
      engine: dom.previewEngine.value,
    };
    const res = await apiFetch("/preview/html", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const sandboxed = buildSandboxedHtml(data.html);
    state.previewHtml = sandboxed;
    dom.previewFrame.srcdoc = sandboxed;
    dom.previewHint.textContent = data.truncated
      ? "Preview HTML truncated for safety."
      : "HTML loaded.";
    dom.previewFrame.onload = () => wireIframe(dom.previewFrame);
    setStatus("HTML loaded", "Ready");
  } catch (err) {
    setStatus("Failed to load HTML", "Error");
  }
}

async function runPreviewJob() {
  const url = dom.previewUrl.value.trim();
  const schemaId = dom.schemaId.value.trim();
  if (!url || !schemaId) return setStatus("Enter URL and schema ID", "Input");
  setStatus("Running preview", "Working");
  try {
    const res = await apiFetch(`/schemas/${schemaId}/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, engine: dom.previewEngine.value }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    dom.previewJson.textContent = JSON.stringify(data.data || {}, null, 2);
    renderArtifacts(data.artifacts || []);
    setStatus("Preview complete", "Ready");
  } catch (err) {
    setStatus("Preview failed", "Error");
  }
}

function renderArtifacts(artifacts) {
  dom.previewScreenshot.src = "";
  dom.artifactLinks.innerHTML = "";
  artifacts.forEach((artifact) => {
    const link = document.createElement("a");
    link.href = `/artifacts/${artifact.id}`;
    link.textContent = artifact.type;
    link.target = "_blank";
    dom.artifactLinks.appendChild(link);
    if (artifact.type === "screenshot") {
      dom.previewScreenshot.src = link.href;
    }
  });
}

function addSelector() {
  const selector = dom.fieldSelector.value.trim();
  const field = dom.fieldName.value.trim();
  if (!selector || !field) return setStatus("Field + selector required", "Input");
  const entry = {
    schema_id: dom.schemaId.value.trim(),
    group_name: dom.groupName.value.trim() || null,
    item_selector: dom.itemSelector.value.trim() || null,
    field,
    selector,
    attribute: dom.fieldAttribute.value.trim() || null,
    data_type: dom.dataType.value,
    required: dom.fieldRequired.checked,
    active: true,
  };
  state.selectors.push(entry);
  renderSelectorList();
  dom.fieldName.value = "";
  dom.fieldSelector.value = "";
  dom.fieldAttribute.value = "";
  setStatus("Selector added", "Ready");
}

function renderSelectorList() {
  dom.selectorList.innerHTML = "";
  state.selectors.forEach((item, index) => {
    const row = document.createElement("div");
    row.className = "list-item";
    const info = document.createElement("div");
    info.innerHTML = `
      <div><strong>${item.field}</strong> ${item.group_name ? `(group: ${item.group_name})` : ""}</div>
      <code>${item.selector}</code>
      ${item.item_selector ? `<div class="tiny">item: ${item.item_selector}</div>` : ""}
      ${item.attribute ? `<div class="tiny">attr: ${item.attribute}</div>` : ""}
    `;
    const remove = document.createElement("button");
    remove.className = "ghost";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      state.selectors.splice(index, 1);
      renderSelectorList();
    });
    row.appendChild(info);
    row.appendChild(remove);
    dom.selectorList.appendChild(row);
  });
}

async function saveSchema() {
  const schemaId = dom.schemaId.value.trim();
  if (!schemaId) return setStatus("Schema ID required", "Input");
  if (state.selectors.length === 0) return setStatus("Add selectors first", "Input");
  setStatus("Saving schema", "Working");
  try {
    await apiFetch("/schemas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schema_id: schemaId, name: schemaId }),
    });
    for (const selector of state.selectors) {
      await apiFetch(`/schemas/${schemaId}/selectors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(selector),
      });
    }
    setStatus("Schema saved", "Ready");
  } catch (err) {
    setStatus("Save failed", "Error");
  }
}

async function loadQuarantine() {
  const schemaId = dom.quarantineSchema.value.trim();
  if (!schemaId) return setStatus("Enter schema ID", "Input");
  setStatus("Loading candidates", "Working");
  try {
    const res = await apiFetch(`/schemas/${schemaId}/candidates`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    renderQuarantine(schemaId, data);
    setStatus("Candidates loaded", "Ready");
  } catch (err) {
    setStatus("Failed to load candidates", "Error");
  }
}

function renderQuarantine(schemaId, candidates) {
  dom.quarantineList.innerHTML = "";
  if (candidates.length === 0) {
    dom.quarantineList.innerHTML = "<div class=\"tiny\">No candidates.</div>";
    return;
  }
  candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "list-item";
    const info = document.createElement("div");
    info.innerHTML = `
      <div><strong>${candidate.field}</strong> ${candidate.group_name ? `(group: ${candidate.group_name})` : ""}</div>
      <code>${candidate.selector}</code>
      ${candidate.item_selector ? `<div class="tiny">item: ${candidate.item_selector}</div>` : ""}
      ${candidate.attribute ? `<div class="tiny">attr: ${candidate.attribute}</div>` : ""}
      <div class="tiny">success: ${candidate.success_count}</div>
    `;
    const actions = document.createElement("div");
    const promote = document.createElement("button");
    promote.className = "primary";
    promote.textContent = "Promote";
    promote.addEventListener("click", async () => {
      await apiFetch(`/schemas/${schemaId}/candidates/${candidate.id}/promote`, { method: "POST" });
      loadQuarantine();
    });
    const reject = document.createElement("button");
    reject.className = "ghost";
    reject.textContent = "Reject";
    reject.addEventListener("click", async () => {
      await apiFetch(`/schemas/${schemaId}/candidates/${candidate.id}`, { method: "DELETE" });
      loadQuarantine();
    });
    actions.appendChild(promote);
    actions.appendChild(reject);
    row.appendChild(info);
    row.appendChild(actions);
    dom.quarantineList.appendChild(row);
  });
}

function wireIframe(iframe) {
  const doc = iframe.contentDocument;
  if (!doc) return;
  const style = doc.createElement("style");
  style.textContent = `
    .proteus-hover { outline: 2px solid #1f7a6e !important; cursor: crosshair; }
  `;
  doc.head.appendChild(style);

  let current = null;
  doc.addEventListener("mouseover", (event) => {
    if (!event.target || event.target.nodeType !== 1) return;
    if (current) current.classList.remove("proteus-hover");
    current = event.target;
    current.classList.add("proteus-hover");
  });
  doc.addEventListener("mouseout", () => {
    if (current) current.classList.remove("proteus-hover");
    current = null;
  });
  doc.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const target = event.target;
    if (!target || target.nodeType !== 1) return;
    const selector = cssPath(target);
    state.lastSelector = selector;
    dom.selectedSelector.textContent = selector;
    if (state.mode === "item") {
      dom.itemSelector.value = selector;
    } else {
      dom.fieldSelector.value = selector;
    }
  });
}

function cssPath(el) {
  if (el.id) return `#${escapeCss(el.id)}`;
  const parts = [];
  while (el && el.nodeType === 1 && el.tagName.toLowerCase() !== "html") {
    let part = el.tagName.toLowerCase();
    const classes = Array.from(el.classList || []).filter(Boolean);
    if (classes.length) {
      part += "." + classes.slice(0, 2).map(escapeCss).join(".");
    }
    const siblings = Array.from(el.parentNode?.children || []).filter(
      (sib) => sib.tagName === el.tagName
    );
    if (siblings.length > 1) {
      const index = siblings.indexOf(el) + 1;
      part += `:nth-of-type(${index})`;
    }
    parts.unshift(part);
    if (el.tagName.toLowerCase() === "body") break;
    el = el.parentElement;
  }
  return parts.join(" > ");
}

function escapeCss(value) {
  if (window.CSS && CSS.escape) {
    return CSS.escape(value);
  }
  return value.replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);
}

function buildSandboxedHtml(html) {
  const stripped = stripScripts(html || "");
  const csp =
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:;";
  const meta = `<meta http-equiv="Content-Security-Policy" content="${csp}">`;
  if (/<head[^>]*>/i.test(stripped)) {
    return stripped.replace(/<head[^>]*>/i, (match) => `${match}${meta}`);
  }
  if (/<html[^>]*>/i.test(stripped)) {
    return stripped.replace(/<html[^>]*>/i, (match) => `${match}<head>${meta}</head>`);
  }
  return `<!doctype html><html><head>${meta}</head><body>${stripped}</body></html>`;
}

function stripScripts(html) {
  return html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "");
}

function generateToken() {
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes)
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}
