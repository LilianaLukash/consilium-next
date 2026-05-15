import { applyOAuthFromUrl, authFetch, fetchAuthMe, fetchBalance } from "./auth-client.js";

const AGENT_ORDER = ["diator", "visionary", "architect", "critic"];
const WAVE2_IDS = new Set(["architect", "critic"]);
let currentWave = 0;
const ROLE_LABELS = {
  diator: "Генератор идей",
  visionary: "Визионер",
  architect: "Архитектор",
  critic: "Критик",
  synthesis: "Синтез",
};

const ROLE_ICONS = {
  diator: "⚡",
  visionary: "◈",
  architect: "▣",
  critic: "◎",
};

const PHASE_LABELS = {
  independent: "Вклад",
  debate: "Дебат",
  review: "Пересмотр",
  synthesis: "Синтез",
  revision: "Правка",
};

let agentsMeta = [];
let allModels = [];
let councilConfig = { price_threshold: 10, preset: "balanced", models: {}, snapshots: {} };
let running = false;
let currentSessionId = null;

const $ = (id) => document.getElementById(id);

function setPhase(phase) {
  const order = ["idle", "independent", "debate", "review", "synthesis", "complete"];
  const ci = order.indexOf(phase === "error" || phase === "revision" ? "idle" : phase);
  document.querySelectorAll(".phase-pill").forEach((el) => {
    const p = el.dataset.phase;
    const pi = order.indexOf(p);
    el.classList.remove("active", "done");
    if (p === phase) el.classList.add("active");
    else if (pi >= 0 && pi < ci) el.classList.add("done");
  });
}

function showError(msg) {
  const b = $("errorBanner");
  if (b) { b.textContent = msg; b.classList.remove("hidden"); }
  const s = $("statusText");
  if (s) { s.textContent = "Ошибка"; s.classList.add("is-error"); }
}

function hideError() {
  $("errorBanner")?.classList.add("hidden");
  $("statusText")?.classList.remove("is-error");
}

async function parseApiError(res) {
  const data = await res.json().catch(() => ({}));
  const detail = data.detail;
  if (detail && typeof detail === "object") {
    if (detail.code === "AUTH_REQUIRED") {
      window.location.href = "/auth.html";
    }
    return detail.message || JSON.stringify(detail);
  }
  return detail || res.statusText;
}

function showPaymentToast() {
  const params = new URLSearchParams(window.location.search);
  const payment = params.get("payment");
  if (!payment) return;
  const toast = $("paymentToast");
  if (!toast) return;
  toast.textContent =
    payment === "success"
      ? "Оплата прошла. Баланс обновится через несколько секунд."
      : "Оплата отменена.";
  toast.classList.remove("hidden");
  params.delete("payment");
  const qs = params.toString();
  window.history.replaceState({}, "", qs ? `?${qs}` : window.location.pathname);
  setTimeout(() => toast.classList.add("hidden"), 8000);
}

async function updateAccountBar() {
  const me = await fetchAuthMe();
  const balEl = $("accountBalance");
  const guestEl = $("accountGuestHint");
  const authLink = $("authLink");
  const accountLink = $("accountLink");
  if (!me || !balEl) return;
  if (me.mode === "master") {
    balEl.textContent = "MASTER ∞";
    balEl.classList.remove("hidden");
    balEl.classList.add("unlimited");
    guestEl?.classList.add("hidden");
    accountLink?.classList.add("hidden");
    if (authLink) authLink.textContent = "Dev";
    return;
  }
  if (me.mode === "user" && me.user) {
    const bal = await fetchBalance();
    balEl.textContent = bal?.unlimited ? "∞" : `$${parseFloat(bal?.balance_usd || me.user.balance_usd || 0).toFixed(2)}`;
    balEl.classList.toggle("unlimited", !!bal?.unlimited);
    balEl.classList.remove("hidden");
    guestEl?.classList.add("hidden");
    accountLink?.classList.remove("hidden");
    if (authLink) {
      authLink.textContent = me.user.email?.split("@")[0] || "Профиль";
      authLink.href = "/account.html";
    }
    return;
  }
  accountLink?.classList.add("hidden");
  balEl.classList.add("hidden");
  if (guestEl && me.guest_free_runs != null) {
    const left = Math.max(0, me.guest_free_runs - (me.guest_runs || 0));
    guestEl.textContent = left > 0 ? `Проба: ${left} запуск` : "Нужен вход";
    guestEl.classList.remove("hidden");
  }
  if (authLink) {
    authLink.textContent = "Войти";
    authLink.href = "/auth.html";
  }
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function setStatusRunning(active) {
  const dot = $("statusDot");
  if (dot) {
    dot.classList.toggle("is-running", active);
    dot.classList.toggle("is-done", !active && !running);
  }
}

function finishRun() {
  running = false;
  $("runBtn").disabled = false;
  $("reviseBtn").disabled = false;
  setStatusRunning(false);
  const dot = $("statusDot");
  if (dot) dot.classList.add("is-done");
  document.querySelectorAll(".card.loading").forEach((el) => el.remove());
}

function getCouncilPayload() {
  return {
    price_threshold: parseFloat($("priceThreshold")?.value || "10"),
    preset: $("presetSelect")?.value || "balanced",
    models: { ...councilConfig.models },
    snapshots: { ...councilConfig.snapshots },
  };
}

/** Для GET /api/agents — без snapshots (иначе URL обрезается и выбор «не работает»). */
function getCouncilPayloadSlim() {
  const p = getCouncilPayload();
  return {
    price_threshold: p.price_threshold,
    preset: p.preset,
    models: p.models,
  };
}

async function loadModels() {
  const th = $("priceThreshold")?.value || "10";
  const res = await fetch(`/api/models?price_threshold=${th}`);
  const data = await res.json();
  allModels = data.models || [];
  renderRoleDropdowns();
}

function modelOptionLabel(m) {
  const tags = (m.tags || []).join(" ");
  return `${m.id} · in $${m.input_price_per_m} · out $${m.output_price_per_m} · ctx ${m.context_length} · ${tags}`;
}

function onRoleModelChange(sel) {
  const role = sel.dataset.role;
  if (!role) return;
  councilConfig.models[role] = sel.value;
  const m = allModels.find((x) => x.id === sel.value);
  if (m) councilConfig.snapshots[role] = m;
  else delete councilConfig.snapshots[role];
  const st = $("statusText");
  if (st) st.textContent = `${ROLE_LABELS[role] || role}: ${sel.value}`;
}

function bindRoleModelDelegates() {
  const root = $("roleModels");
  if (!root || root.dataset.bound === "1") return;
  root.dataset.bound = "1";
  root.addEventListener("change", (e) => {
    const sel = e.target;
    if (!sel.matches?.("select[data-role]")) return;
    onRoleModelChange(sel);
    loadAgents().catch(() => {});
  });
}

function renderRoleDropdowns() {
  const root = $("roleModels");
  if (!root) return;
  bindRoleModelDelegates();
  const roles = [...AGENT_ORDER, "synthesis"];
  root.innerHTML = roles
    .map((role) => {
      const opts = allModels
        .map(
          (m) =>
            `<option value="${escapeHtml(m.id)}" ${councilConfig.models[role] === m.id ? "selected" : ""}>${escapeHtml(modelOptionLabel(m))}</option>`
        )
        .join("");
      const cur = councilConfig.models[role] || "";
      const extra = cur && !allModels.find((m) => m.id === cur)
        ? `<option value="${escapeHtml(cur)}" selected>${escapeHtml(cur)} (текущая)</option>`
        : "";
      return `<label class="role-model-row"><span>${ROLE_LABELS[role]}</span><select data-role="${role}">${extra}${opts}</select></label>`;
    })
    .join("");
}

async function loadEnvCouncilDefaults() {
  const res = await fetch("/api/council/env-defaults");
  if (!res.ok) return;
  const data = await res.json();
  for (const [role, model] of Object.entries(data.models || {})) {
    if (model) councilConfig.models[role] = model;
  }
}

async function applyPreset() {
  const res = await authFetch("/api/council/preset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      preset: $("presetSelect").value,
      price_threshold: parseFloat($("priceThreshold").value),
    }),
  });
  const data = await res.json();
  councilConfig = data.council_config;
  await loadEnvCouncilDefaults();
  await loadAgents();
  renderRoleDropdowns();
}

async function autoStack() {
  const prompt = $("prompt").value.trim();
  const files = $("fileInput")?.files || [];
  let hasImages = false;
  for (const f of files) {
    if (/\.(png|jpe?g|webp|gif)$/i.test(f.name)) hasImages = true;
  }
  const res = await authFetch("/api/council/auto-select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      price_threshold: parseFloat($("priceThreshold").value),
      has_images: hasImages,
      has_files: files.length > 0,
    }),
  });
  const data = await res.json();
  councilConfig = data.council_config;
  await loadAgents();
  renderRoleDropdowns();
  $("statusText").textContent = "Стек моделей подобран автоматически";
}

async function loadAgents() {
  const cfg = encodeURIComponent(JSON.stringify(getCouncilPayloadSlim()));
  agentsMeta = await (await authFetch(`/api/agents?council=${cfg}`)).json();
  const order = Object.fromEntries(AGENT_ORDER.map((id, i) => [id, i]));
  agentsMeta.sort((a, b) => (order[a.id] ?? 99) - (order[b.id] ?? 99));
  renderAgentColumns();
}

const COL_WIDTH_KEY = "consilium-col-widths";
const SIDEBAR_COLLAPSED_KEY = "consilium-sidebar-collapsed";

function setSidebarCollapsed(collapsed) {
  const body = $("appBody");
  const openBtn = $("sidebarOpen");
  const topBtn = $("sidebarToggleTop");
  if (!body) return;
  body.classList.toggle("sidebar-collapsed", collapsed);
  localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  if (topBtn) {
    topBtn.setAttribute("aria-expanded", String(!collapsed));
    topBtn.textContent = collapsed ? "История" : "Скрыть";
  }
}

function initSidebar() {
  const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
  const collapsed = stored === null ? true : stored === "1";
  setSidebarCollapsed(collapsed);
  $("sidebarClose")?.addEventListener("click", () => setSidebarCollapsed(true));
  $("sidebarOpen")?.addEventListener("click", () => setSidebarCollapsed(false));
  $("sidebarToggleTop")?.addEventListener("click", () => {
    const body = $("appBody");
    setSidebarCollapsed(!body?.classList.contains("sidebar-collapsed"));
  });
}

function columnResizeId(col) {
  return col.dataset.agentId || (col.classList.contains("verdict-column") ? "verdict" : "col");
}

function initColumnResize() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(COL_WIDTH_KEY) || "{}");
  } catch {
    saved = {};
  }

  document.querySelectorAll(".board .column").forEach((col) => {
    const id = columnResizeId(col);
    if (saved[id]) col.style.width = `${saved[id]}px`;

    let handle = col.querySelector(".col-resize-handle");
    if (!handle) {
      handle = document.createElement("div");
      handle.className = "col-resize-handle";
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-label", "Изменить ширину колонки");
      col.appendChild(handle);
    }

    handle.onmousedown = (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = col.offsetWidth;
      document.body.classList.add("col-resizing");

      const onMove = (ev) => {
        const maxW = window.innerWidth * 0.92;
        const w = Math.min(maxW, Math.max(200, startW + (ev.clientX - startX)));
        col.style.width = `${w}px`;
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.classList.remove("col-resizing");
        saved[id] = col.offsetWidth;
        localStorage.setItem(COL_WIDTH_KEY, JSON.stringify(saved));
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    };
  });
}

function renderAgentColumns() {
  const root = $("agentColumns");
  if (!root) return;
  root.innerHTML = "";
  for (const a of agentsMeta) {
    const col = document.createElement("article");
    col.className = "column";
    col.dataset.agentId = a.id;
    col.style.setProperty("--agent-color", a.color);
    const icon = ROLE_ICONS[a.id] || "●";
    col.innerHTML = `
      <header class="column-header">
        <div class="column-title-row">
          <span class="role-icon" aria-hidden="true">${icon}</span>
          <div>
            <h3>${escapeHtml(a.name)}</h3>
            <p class="role">${escapeHtml(a.role)}</p>
          </div>
        </div>
        <p class="model">${escapeHtml(a.model)}</p>
      </header>
      <div class="column-body" id="col-${a.id}"></div>`;
    root.appendChild(col);
  }
  initColumnResize();
}

function parseContent(raw) {
  const sep = raw.indexOf("---");
  const cbPart = sep >= 0 ? raw.slice(0, sep).trim() : raw;
  const humanPart = sep >= 0 ? raw.slice(sep + 3).trim() : "";
  const cbHtml = cbPart
    .split("\n")
    .map((line) => {
      const t = line.trim();
      if (!t) return "";
      let cls = "";
      if (t.startsWith("!")) cls = "line-claim";
      else if (t.startsWith("?")) cls = "line-challenge";
      else if (t.startsWith("+")) cls = "line-improve";
      else if (t.startsWith("-")) cls = "line-risk";
      else if (t.startsWith("~")) cls = "line-vote";
      return cls ? `<span class="${cls}">${escapeHtml(t)}</span>` : escapeHtml(t);
    })
    .filter(Boolean)
    .join("\n");
  const showCb = cbPart.includes("!claim") || /^[!?+\-~@]/m.test(cbPart);
  return { cbHtml: showCb ? cbHtml : null, human: humanPart || (showCb ? "" : raw) };
}

function addCard(agentId, { phase, round, content, loading, error }) {
  const body = document.getElementById(`col-${agentId}`);
  if (!body) return;
  if (loading) {
    if (!body.querySelector(".card.loading")) {
      const c = document.createElement("article");
      c.className = "card loading";
      c.innerHTML = `<div class="card-meta">${phase}</div><div class="card-body">Думает…</div>`;
      body.appendChild(c);
    }
    return;
  }
  body.querySelectorAll(".card.loading").forEach((el) => el.remove());
  const card = document.createElement("article");
  card.className = error ? "card error-card" : "card";
  if (error) {
    card.innerHTML = `<div class="card-meta">Ошибка</div><div class="card-body">${escapeHtml(error)}</div>`;
  } else {
    const { cbHtml, human } = parseContent(content);
    const phaseLabel = PHASE_LABELS[phase] || phase;
    card.innerHTML = `<div class="card-meta">${phaseLabel}${round ? " · " + round : ""}</div>
      <div class="card-body">${cbHtml ? `<pre class="cb-block">${cbHtml}</pre>` : ""}
      ${human ? `<div class="human-block">${escapeHtml(human)}</div>` : escapeHtml(content)}</div>`;
  }
  body.appendChild(card);
}

function renderVerdict(text) {
  const body = $("verdictBody");
  if (body) body.innerHTML = `<div class="verdict-md">${escapeHtml(text)}</div>`;
}

function setWaveUI(wave) {
  currentWave = wave;
  document.querySelectorAll(".agents-columns .column").forEach((col) => {
    const id = col.dataset.agentId;
    if (WAVE2_IDS.has(id) && wave < 2) {
      col.classList.add("wave-locked");
    } else {
      col.classList.remove("wave-locked");
    }
  });
}

function handleEvent(type, d) {
  if (d.session_id) currentSessionId = d.session_id;
  if (type === "wave" && d.wave) {
    setWaveUI(d.wave);
    if (d.label) $("statusText").textContent = d.label;
  }
  if (type === "status" && d.message) $("statusText").textContent = d.message;
  if (type === "phase" && d.phase && d.phase !== "error") setPhase(d.phase);
  if (type === "agent_start" && d.agent_id) {
    addCard(d.agent_id, { phase: d.phase, round: d.round, loading: true });
  }
  if (type === "agent_message" && d.agent_id && d.content) {
    addCard(d.agent_id, { phase: d.phase, round: d.round, content: d.content });
  }
  if (type === "agent_error" && d.agent_id) {
    addCard(d.agent_id, { phase: d.phase, round: d.round, error: d.message });
  }
  if (type === "verdict" && d.content) {
    renderVerdict(d.content);
    $("reviseBox")?.classList.remove("hidden");
    $("compareVerdictsBtn")?.classList.remove("hidden");
    setPhase("complete");
  }
  if (type === "error") { showError(d.message); setPhase("idle"); }
  if (type === "done") {
    if (d.error) showError(d.error);
    else if (d.final_verdict) {
      renderVerdict(d.final_verdict);
      $("reviseBox")?.classList.remove("hidden");
      $("compareVerdictsBtn")?.classList.remove("hidden");
      setPhase("complete");
    }
    if (d.session_id) currentSessionId = d.session_id;
    finishRun();
    loadSessionsList();
  }
}

async function consumeSSE(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const block of parts) {
      if (!block.trim()) continue;
      let eventType = "message";
      let dataLine = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) eventType = line.slice(7).trim();
        if (line.startsWith("data: ")) dataLine = line.slice(6);
      }
      if (!dataLine) continue;
      try {
        const p = JSON.parse(dataLine);
        handleEvent(eventType, p.data || p);
      } catch { /* skip */ }
    }
  }
}

async function runCouncil({ revise = false } = {}) {
  if (running) return;
  hideError();
  running = true;
  setStatusRunning(true);
  $("runBtn").disabled = true;
  $("reviseBtn").disabled = true;

  if (!revise) {
    $("verdictBody").innerHTML = '<p class="verdict-placeholder">Формируем вывод…</p>';
    await loadAgents();
    document.querySelectorAll('[id^="col-"]').forEach((el) => (el.innerHTML = ""));
    setWaveUI(0);
    setPhase("independent");
  }

  let res;
  try {
    if (revise) {
      const comment = $("userComment").value.trim();
      if (comment.length < 5) { showError("Комментарий — мин. 5 символов"); finishRun(); return; }
      res = await authFetch(`/api/sessions/${currentSessionId}/revise/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment, max_debate_rounds: parseInt($("maxRounds").value, 10) || 1 }),
      });
    } else {
      const prompt = $("prompt").value.trim();
      if (prompt.length < 10) { showError("Мин. 10 символов в задаче"); finishRun(); return; }
      const fd = new FormData();
      fd.append("prompt", prompt);
      fd.append("max_debate_rounds", $("maxRounds").value);
      fd.append("council_config", JSON.stringify(getCouncilPayload()));
      const files = $("fileInput").files;
      for (const f of files) fd.append("files", f);
      res = await authFetch("/api/run/stream", { method: "POST", body: fd });
    }
  } catch (e) {
    showError(String(e));
    finishRun();
    return;
  }
  if (!res.ok) {
    showError(await parseApiError(res));
    finishRun();
    return;
  }
  try {
    await consumeSSE(res);
    await updateAccountBar();
  } catch (e) {
    showError(String(e));
  } finally {
    if (running) finishRun();
  }
}

async function loadSessionsList() {
  const ul = $("sessionsList");
  if (!ul) return;
  try {
    const sessions = await (await authFetch("/api/sessions")).json();
    ul.innerHTML = sessions
      .map(
        (s) =>
          `<li><button type="button" class="session-link" data-id="${s.id}">${escapeHtml((s.prompt || "").slice(0, 50))}… <small>v${s.verdict_version || 1}</small></button></li>`
      )
      .join("");
    ul.querySelectorAll(".session-link").forEach((btn) =>
      btn.addEventListener("click", () => openSession(btn.dataset.id))
    );
  } catch {
    ul.innerHTML = "<li>Нет истории</li>";
  }
}

async function openSession(id) {
  const data = await (await authFetch(`/api/sessions/${id}`)).json();
  currentSessionId = id;
  $("prompt").value = data.session.prompt || "";
  if (data.council_config) {
    councilConfig = data.council_config;
    $("priceThreshold").value = councilConfig.price_threshold || 10;
    if (councilConfig.preset) $("presetSelect").value = councilConfig.preset;
    await loadModels();
    await loadAgents();
  }
  document.querySelectorAll('[id^="col-"]').forEach((el) => (el.innerHTML = ""));
  for (const m of data.messages || []) {
    const aid = m.agent_id === "owl" ? "diator" : m.agent_id;
    addCard(aid, { phase: m.phase, round: m.round, content: m.content });
  }
  const v = (data.verdicts || []).slice(-1)[0];
  if (v) {
    renderVerdict(v.content);
    $("reviseBox")?.classList.remove("hidden");
    $("compareVerdictsBtn")?.classList.remove("hidden");
  }
}

async function compareVerdicts() {
  if (!currentSessionId) return;
  const data = await (await authFetch(`/api/sessions/${currentSessionId}/verdicts/compare`)).json();
  const box = $("compareBox");
  if (!box) return;
  box.classList.remove("hidden");
  if (data.message) {
    box.textContent = data.message;
    return;
  }
  box.textContent = `=== v${data.older.version} ===\n${data.older.content.slice(0, 2000)}\n\n=== v${data.newer.version} ===\n${data.newer.content.slice(0, 2000)}`;
}

$("runBtn")?.addEventListener("click", () => runCouncil());
$("reviseBtn")?.addEventListener("click", () => runCouncil({ revise: true }));
$("applyPresetBtn")?.addEventListener("click", applyPreset);
$("autoStackBtn")?.addEventListener("click", autoStack);
$("priceThreshold")?.addEventListener("change", loadModels);
$("compareVerdictsBtn")?.addEventListener("click", compareVerdicts);

(async () => {
  applyOAuthFromUrl();
  showPaymentToast();
  initSidebar();
  initColumnResize();
  await updateAccountBar();
  await loadModels();
  await loadEnvCouncilDefaults();
  await applyPreset();
  loadSessionsList();
  try {
    const h = await (await fetch("/api/health")).json();
    if (h.models?.diator) {
      console.info("[Consilium] модели с сервера:", h.models);
    }
  } catch {
    /* ignore */
  }
})();
