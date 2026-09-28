const DEFAULT_TAGS = {
  setup: [
    "Liquidity Sweep", "Prior Day High/Low", "Session High/Low", "Asia High/Low",
    "London High/Low", "Equal Highs/Lows", "Relative Equal Highs/Lows", "FVG",
    "IFVG", "1H FVG", "4H FVG", "HTF PD Array", "Displacement",
    "Market Structure Shift", "Order Block", "Breaker", "Opening Range",
    "VWAP Reclaim", "VWAP Rejection", "RSI Divergence", "Trend Continuation",
    "Liquidity Rotation", "Countertrend", "News Reaction"
  ],
  execution: [
    "Patient Entry", "Waited for Sweep", "Waited for Displacement", "FVG Entry",
    "IFVG Confirmation", "Structure Confirmation", "Good Confirmation", "Clean Risk",
    "Structural Stop", "Target Defined", "Entered Early", "Entered Late", "Chased",
    "No Confirmation", "Missed Entry", "Stop Too Tight", "Moved Stop", "Oversized",
    "Under-sized", "Cut Winner Early", "Took Profit Early", "Held Too Long",
    "Added to Loser", "FOMO", "Revenge Trade", "Overtrading", "Rule Break"
  ],
  emotion: [
    "Neutral", "Calm", "Focused", "Locked In", "Confident", "Patient", "Hesitant",
    "Distracted", "Frustrated", "Anxious", "Fearful", "Greedy", "Overconfident",
    "Tilted", "Rushed", "Bored", "Tired"
  ]
};

let pendingCapture = null;
let activeEpisode = null;
let chosenPhase = null;
let customTags = { setup: [], execution: [], emotion: [] };
let lastSavedRoute = null;
let connection = null;
const selected = {
  setup: new Set(),
  execution: new Set(),
  emotion: new Set(),
};

const $ = (id) => document.getElementById(id);
chrome.runtime.connect({ name: "journalme-sidepanel" });

function uniqueTags(values) {
  const seen = new Set();
  return values.filter((value) => {
    const key = String(value || "").trim().toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderChips(containerId, group) {
  const container = $(containerId);
  const customs = customTags[group] || [];
  const tags = uniqueTags([...(DEFAULT_TAGS[group] || []), ...customs]);
  container.innerHTML = "";
  for (const tag of tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip${customs.some((item) => item.toLowerCase() === tag.toLowerCase()) ? " custom-chip" : ""}`;
    button.textContent = tag;
    if (selected[group].has(tag)) button.classList.add("selected");
    button.addEventListener("click", () => {
      if (selected[group].has(tag)) selected[group].delete(tag);
      else selected[group].add(tag);
      renderChips(containerId, group);
    });
    container.appendChild(button);
  }
}

function renderAllTags() {
  renderChips("setupTags", "setup");
  renderChips("executionTags", "execution");
  renderChips("emotionTags", "emotion");
}

async function addCustomTag(group, inputId) {
  const input = $(inputId);
  const value = input.value.trim().replace(/\s+/g, " ");
  if (!value) return;
  const all = [...DEFAULT_TAGS[group], ...(customTags[group] || [])];
  const existing = all.find((item) => item.toLowerCase() === value.toLowerCase());
  const resolved = existing || value;
  if (!existing) {
    customTags[group] = uniqueTags([...(customTags[group] || []), value]);
    await chrome.storage.local.set({ customTags });
  }
  selected[group].add(resolved);
  input.value = "";
  renderAllTags();
}

async function loadCustomTags() {
  const data = await chrome.storage.local.get("customTags");
  const stored = data.customTags || {};
  customTags = {
    setup: Array.isArray(stored.setup) ? stored.setup : [],
    execution: Array.isArray(stored.execution) ? stored.execution : [],
    emotion: Array.isArray(stored.emotion) ? stored.emotion : [],
  };
  renderAllTags();
}

function setStatus(message, type = "") {
  const el = $("status");
  el.textContent = message || "";
  el.className = `status ${type}`.trim();
}

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatDateTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function phaseLabel(value) {
  if (!value) return "Moment";
  return String(value).replaceAll("_", " ");
}

function renderPending() {
  const preview = $("preview");
  const empty = $("emptyPreview");
  if (!pendingCapture?.screenshotDataUrl) {
    preview.style.display = "none";
    preview.removeAttribute("src");
    empty.style.display = "grid";
    $("platform").textContent = "No screenshot attached";
    $("capturedAt").textContent = "";
    return;
  }
  preview.src = pendingCapture.screenshotDataUrl;
  preview.style.display = "block";
  empty.style.display = "none";
  $("platform").textContent = pendingCapture.platform || "Browser";
  $("capturedAt").textContent = formatTime(pendingCapture.capturedAt);
  if (!$("symbol").value && pendingCapture.detectedSymbol) $("symbol").value = pendingCapture.detectedSymbol;
}

async function loadPending() {
  const data = await chrome.storage.local.get(["pendingCapture", "lastCaptureError"]);
  pendingCapture = data.pendingCapture || null;
  renderPending();
  if (data.lastCaptureError) {
    setStatus(data.lastCaptureError, "error");
    await chrome.storage.local.remove("lastCaptureError");
  }
}

async function authContext() {
  const result = await chrome.runtime.sendMessage({ type: "GET_AUTH_CONTEXT" });
  connection = result;
  return result;
}

async function loadConnection() {
  const result = await authContext();
  const dot = $("connectionDot");
  const title = $("connectionTitle");
  const detail = $("connectionDetail");
  dot.className = "connection-dot";
  if (result?.ok && result.mode === "hosted") {
    dot.classList.add("connected");
    title.textContent = "Signed in to JournalMe";
    detail.textContent = result.userEmail || "Cloud account connected";
    $("authCard").hidden = true;
    $("signOutBtn").hidden = false;
    $("brokerSyncCard").hidden = false;
    return result;
  }
  if (result?.mode === "hosted") {
    dot.classList.add("warning");
    title.textContent = "Sign in to sync";
    detail.textContent = "Your moments can sync without the website being open";
    $("authCard").hidden = false;
    $("signOutBtn").hidden = true;
    $("brokerSyncCard").hidden = true;
    return result;
  }
  dot.classList.add("local");
  title.textContent = "Local development mode";
  detail.textContent = "Saving to the configured local JournalMe API";
  $("authCard").hidden = true;
  $("signOutBtn").hidden = true;
  $("brokerSyncCard").hidden = false;
  return result;
}

async function dataUrlToBlob(dataUrl) {
  const response = await fetch(dataUrl);
  return response.blob();
}

async function journalFetch(path, options = {}) {
  const context = connection?.ok ? connection : await authContext();
  if (!context?.ok) throw new Error(context?.error || "JournalMe Companion is not connected.");
  const headers = new Headers(options.headers || {});
  for (const [key, value] of Object.entries(context.headers || {})) headers.set(key, value);
  const base = context.settings.apiBase.replace(/\/$/, "");
  return fetch(`${base}${path}`, { ...options, headers });
}

function apiDetailMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const parts = [];
    if (typeof detail.message === "string") parts.push(detail.message);
    if (Array.isArray(detail.errors)) {
      for (const issue of detail.errors) {
        if (!issue || typeof issue !== "object") continue;
        parts.push(`${issue.filename ? `${issue.filename}: ` : ""}${issue.reason || "Invalid report data."}`);
      }
    }
    if (parts.length) return parts.join(" ");
  }
  return fallback;
}

function quickSyncMissing(preview) {
  const reportTypes = new Set((preview?.reports || []).map((report) => report.type));
  const missing = [];
  if (!reportTypes.has("performance") && !reportTypes.has("position_history")) missing.push("Performance");
  if (!reportTypes.has("fills")) missing.push("Fills");
  return missing;
}

async function cancelImportQuietly(sessionId) {
  if (!sessionId) return;
  try { await journalFetch(`/api/v1/imports/${encodeURIComponent(sessionId)}/cancel`, { method: "POST" }); } catch {}
}

async function syncTradovateReports(files) {
  if (!files?.length) return;
  const button = $("brokerSyncBtn");
  const statusBox = $("brokerSyncStatus");
  button.disabled = true;
  button.textContent = "Syncing...";
  statusBox.className = "status";
  statusBox.textContent = "Reading Tradovate reports...";
  try {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    const accountId = $("account").value || "";
    const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
    const previewResponse = await journalFetch(`/api/v1/imports/preview${query}`, { method: "POST", body: form });
    const preview = await previewResponse.json().catch(() => ({}));
    if (!previewResponse.ok) throw new Error(apiDetailMessage(preview, `Preview failed (${previewResponse.status}).`));
    const missing = quickSyncMissing(preview);
    if (missing.length) {
      await cancelImportQuietly(preview.session_id);
      throw new Error(`Quick Sync needs ${missing.join(" and ")} report${missing.length === 1 ? "" : "s"}.`);
    }
    if (Array.isArray(preview.errors) && preview.errors.length) {
      await cancelImportQuietly(preview.session_id);
      const first = preview.errors[0];
      throw new Error(`${first?.filename || "A report"}: ${first?.reason || "validation failed"}`);
    }
    statusBox.textContent = "Reports recognized. Updating JournalMe...";
    const commitResponse = await journalFetch(`/api/v1/imports/${encodeURIComponent(preview.session_id)}/commit`, { method: "POST" });
    const commit = await commitResponse.json().catch(() => ({}));
    if (!commitResponse.ok) throw new Error(apiDetailMessage(commit, `Sync failed (${commitResponse.status}).`));
    const created = commit.created || {};
    const balanceNote = (preview.reports || []).some((report) => report.type === "account_balance_history")
      ? ` · ${Number(created.daily_balances || 0)} balance snapshot${Number(created.daily_balances || 0) === 1 ? "" : "s"}`
      : " · balance unchanged";
    statusBox.className = "status ok";
    statusBox.textContent = `${Number(created.trades || 0)} new trade${Number(created.trades || 0) === 1 ? "" : "s"} · ${Number(created.fills || 0)} fills${balanceNote}`;
    await loadAccounts();
    await reconcileAndLoadEpisodes();
  } catch (error) {
    statusBox.className = "status error";
    statusBox.textContent = error?.message || String(error);
  } finally {
    button.disabled = false;
    button.textContent = "Sync reports";
    $("brokerFiles").value = "";
  }
}

async function ensureCapturePermission() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab?.url) return true;
  let url;
  try { url = new URL(tab.url); } catch { return true; }
  if (!/^https?:$/.test(url.protocol)) throw new Error("Open a normal web page before taking a screenshot.");
  const originPattern = `${url.origin}/*`;
  if (await chrome.permissions.contains({ origins: [originPattern] })) return true;
  const granted = await chrome.permissions.request({ origins: [originPattern] });
  if (!granted) throw new Error(`Allow JournalMe access to ${url.hostname} so the Take screenshot button can capture this page. Alt+C still works without permanent site access.`);
  return true;
}

async function captureNow() {
  try {
    setStatus("Capturing...");
    $("captureBtn").disabled = true;
    await ensureCapturePermission();
    const response = await chrome.runtime.sendMessage({ type: "CAPTURE_NOW" });
    if (!response?.ok) throw new Error(response?.error || "Capture failed.");
    pendingCapture = response.pending;
    renderPending();
    setStatus("Screenshot ready. Add a thought if useful, then save.", "ok");
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  } finally {
    $("captureBtn").disabled = false;
  }
}

async function clearPending() {
  pendingCapture = null;
  await chrome.storage.local.remove("pendingCapture");
  renderPending();
  setStatus("Pending screenshot cleared.");
}

function setPhase(value) {
  chosenPhase = chosenPhase === value ? null : value;
  document.querySelectorAll(".phase").forEach((button) => {
    button.classList.toggle("selected", button.dataset.phase === chosenPhase);
  });
}

function clearMomentForm() {
  $("note").value = "";
  chosenPhase = null;
  document.querySelectorAll(".phase").forEach((button) => button.classList.remove("selected"));
  selected.setup.clear();
  selected.execution.clear();
  selected.emotion.clear();
  renderAllTags();
}

function momentMetadata() {
  const capturedAt = pendingCapture?.capturedAt || new Date().toISOString();
  const ageMs = Math.abs(Date.now() - new Date(capturedAt).getTime());
  return {
    episode_id: activeEpisode?.id || null,
    captured_at: capturedAt,
    phase: chosenPhase,
    account_id: $("account").value || activeEpisode?.account_id || null,
    symbol: $("symbol").value.trim().toUpperCase() || activeEpisode?.symbol || null,
    side: $("side").value || activeEpisode?.side || null,
    note: $("note").value.trim() || null,
    setup_tags: [...selected.setup],
    execution_tags: [...selected.execution],
    emotion_tags: [...selected.emotion],
    platform: pendingCapture?.platform || "Chrome Companion",
    page_url: pendingCapture?.pageUrl || null,
    page_title: pendingCapture?.pageTitle || null,
    source: "journalme_chrome_extension",
    recorded_live: Number.isFinite(ageMs) ? ageMs <= 15 * 60 * 1000 : true,
  };
}

function hasMomentContent(metadata) {
  return Boolean(
    pendingCapture?.screenshotDataUrl || metadata.note ||
    metadata.setup_tags.length || metadata.execution_tags.length || metadata.emotion_tags.length
  );
}

async function saveMoment() {
  try {
    setStatus("Saving...");
    $("saveBtn").disabled = true;
    $("openSavedBtn").hidden = true;
    const metadata = momentMetadata();
    if (!hasMomentContent(metadata)) throw new Error("Add a thought, screenshot, or optional context before saving.");
    const form = new FormData();
    form.append("metadata", JSON.stringify(metadata));
    if (pendingCapture?.screenshotDataUrl) {
      const blob = await dataUrlToBlob(pendingCapture.screenshotDataUrl);
      form.append("screenshot", blob, `journalme-${Date.now()}.png`);
    }
    const response = await journalFetch("/api/v1/captures/moments", { method: "POST", body: form });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiDetailMessage(body, `Save failed (${response.status}).`));

    activeEpisode = body?.episode?.status === "active" ? body.episode : null;
    const statusText = body?.episode?.status === "active" ? "Moment saved to the active episode." : "Moment saved. Episode complete.";
    setStatus(statusText, "ok");
    lastSavedRoute = "/companion";
    $("openSavedBtn").hidden = false;

    if (pendingCapture) await chrome.storage.local.remove("pendingCapture");
    pendingCapture = null;
    clearMomentForm();
    renderPending();
    renderActiveEpisode();
    await loadEpisodes();
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  } finally {
    $("saveBtn").disabled = false;
  }
}

async function loadAccounts() {
  const select = $("account");
  const hint = $("accountHint");
  const stored = await chrome.storage.local.get("companionAccountId");
  const wanted = stored.companionAccountId || "";
  try {
    const context = connection?.ok ? connection : await authContext();
    if (!context?.ok) {
      select.innerHTML = '<option value="">Sign in first</option>';
      select.disabled = true;
      hint.textContent = "Sign in above to load your JournalMe accounts.";
      return;
    }
    const response = await journalFetch("/api/v1/accounts");
    if (!response.ok) throw new Error(`API ${response.status}`);
    const accounts = await response.json();
    select.disabled = false;
    select.innerHTML = '<option value="">Automatic account</option>';
    for (const account of accounts || []) {
      const option = document.createElement("option");
      option.value = account.id;
      option.textContent = account.name;
      select.appendChild(option);
    }
    if (wanted && [...select.options].some((option) => option.value === wanted)) select.value = wanted;
    else if (accounts?.length === 1) select.value = accounts[0].id;
    hint.textContent = accounts?.length ? `${accounts.length} JournalMe account${accounts.length === 1 ? "" : "s"} available.` : "Create a trading account in JournalMe when you are ready.";
  } catch (error) {
    select.innerHTML = '<option value="">Account list unavailable</option>';
    select.disabled = true;
    hint.textContent = error?.message || "Could not load accounts.";
  }
}

function renderActiveEpisode() {
  const card = $("activeEpisodeCard");
  if (!activeEpisode) {
    card.hidden = true;
    $("activeTimeline").innerHTML = "";
    return;
  }
  card.hidden = false;
  const title = [activeEpisode.symbol || "Trading observation", activeEpisode.side ? activeEpisode.side.toUpperCase() : null].filter(Boolean).join(" · ");
  $("activeEpisodeTitle").textContent = title;
  $("activeEpisodeMeta").textContent = `Started ${formatDateTime(activeEpisode.started_at)} · ${activeEpisode.moment_count || 0} ${(activeEpisode.moment_count || 0) === 1 ? "moment" : "moments"}`;
  if (!$("symbol").value && activeEpisode.symbol) $("symbol").value = activeEpisode.symbol;
  if (!$("side").value && activeEpisode.side) $("side").value = activeEpisode.side;
  const timeline = $("activeTimeline");
  timeline.innerHTML = "";
  const moments = activeEpisode.moments || [];
  if (!moments.length) {
    timeline.innerHTML = '<div class="muted">Your first saved moment will appear here.</div>';
    return;
  }
  for (const moment of moments.slice(-6)) {
    const row = document.createElement("div");
    row.className = "timeline-item";
    const time = document.createElement("div");
    time.className = "timeline-time";
    time.textContent = formatTime(moment.captured_at);
    const copy = document.createElement("div");
    copy.className = "timeline-copy";
    const label = document.createElement("strong");
    label.textContent = phaseLabel(moment.phase);
    copy.appendChild(label);
    if (moment.note) {
      const note = document.createElement("p");
      note.textContent = moment.note;
      copy.appendChild(note);
    }
    const details = [];
    if (moment.has_screenshot) details.push("screenshot");
    if (moment.recorded_live === false) details.push("added later");
    if (details.length) {
      const meta = document.createElement("span");
      meta.textContent = details.join(" · ");
      copy.appendChild(meta);
    }
    row.append(time, copy);
    timeline.appendChild(row);
  }
}

function renderRecentEpisodes(items) {
  const recent = $("recent");
  if (!Array.isArray(items) || !items.length) {
    recent.innerHTML = '<div class="muted">No episode-based activity yet. Your older single captures are still in JournalMe → Captures and are included in the WaveRR research export.</div>';
    return;
  }
  recent.innerHTML = "";
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-item";
    button.addEventListener("click", () => chrome.runtime.sendMessage({ type: "ROUTE_APP", path: "/companion", activate: true }));
    const main = document.createElement("div");
    main.className = "recent-main";
    const title = document.createElement("strong");
    title.textContent = `${item.symbol || "Observation"}${item.side ? ` · ${item.side.toUpperCase()}` : ""}`;
    const status = document.createElement("em");
    status.textContent = item.status || "complete";
    main.append(title, status);
    const meta = document.createElement("div");
    meta.className = "recent-meta";
    meta.textContent = `${item.moment_count || 0} ${(item.moment_count || 0) === 1 ? "moment" : "moments"} · ${item.screenshot_count || 0} ${(item.screenshot_count || 0) === 1 ? "screenshot" : "screenshots"} · ${formatDateTime(item.started_at)}`;
    button.append(main, meta);
    if (item.matched_trade) {
      const pnl = document.createElement("div");
      const numeric = Number(item.matched_trade.net_pnl || 0);
      pnl.className = `recent-pnl ${numeric >= 0 ? "positive" : "negative"}`;
      pnl.textContent = `Matched trade · ${numeric >= 0 ? "+" : ""}$${numeric.toFixed(2)}`;
      button.appendChild(pnl);
    }
    if (item.last_note) {
      const note = document.createElement("div");
      note.className = "recent-note";
      note.textContent = item.last_note;
      button.appendChild(note);
    }
    recent.appendChild(button);
  }
}

async function loadEpisodes() {
  try {
    const accountId = $("account").value || "";
    const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
    const recentQuery = accountId ? `?account_id=${encodeURIComponent(accountId)}&limit=8` : "?limit=8";
    const [activeResponse, recentResponse] = await Promise.all([
      journalFetch(`/api/v1/captures/episodes/active${query}`),
      journalFetch(`/api/v1/captures/episodes${recentQuery}`),
    ]);
    if (!activeResponse.ok) throw new Error(`Active episode API ${activeResponse.status}`);
    if (!recentResponse.ok) throw new Error(`Recent episodes API ${recentResponse.status}`);
    activeEpisode = await activeResponse.json();
    renderActiveEpisode();
    renderRecentEpisodes(await recentResponse.json());
  } catch (error) {
    console.error("JournalMe episode load failed:", error);
    $("recent").innerHTML = `<div class="muted">${error?.message || "Connection unavailable"}</div>`;
  }
}

async function reconcileAndLoadEpisodes() {
  try {
    const accountId = $("account").value || "";
    const query = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
    await journalFetch(`/api/v1/captures/reconcile${query}`, { method: "POST" });
  } catch (error) {
    console.warn("JournalMe reconciliation request failed:", error);
  }
  await loadEpisodes();
}

async function endEpisode() {
  if (!activeEpisode?.id) return;
  try {
    $("endEpisodeBtn").disabled = true;
    const response = await journalFetch(`/api/v1/captures/episodes/${encodeURIComponent(activeEpisode.id)}/complete`, { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiDetailMessage(body, `Could not end episode (${response.status}).`));
    activeEpisode = null;
    renderActiveEpisode();
    setStatus("Episode ended. Your next saved moment can start a new one.", "ok");
    await loadEpisodes();
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  } finally {
    $("endEpisodeBtn").disabled = false;
  }
}

async function openJournalMe() {
  await chrome.runtime.sendMessage({ type: "ROUTE_APP", path: "/companion", activate: true });
}

async function signInHosted() {
  const email = $("authEmail").value.trim();
  const password = $("authPassword").value;
  $("authError").textContent = "";
  if (!email || !password) {
    $("authError").textContent = "Enter your email and password.";
    return;
  }
  $("signInBtn").disabled = true;
  $("signInBtn").textContent = "Signing in...";
  try {
    const result = await chrome.runtime.sendMessage({ type: "SIGN_IN_HOSTED", email, password });
    if (!result?.ok) throw new Error(result?.error || "JournalMe sign in failed.");
    $("authPassword").value = "";
    setStatus("Signed in. Companion sync is ready.", "ok");
    await loadConnection();
    await loadAccounts();
    await reconcileAndLoadEpisodes();
  } catch (error) {
    $("authError").textContent = error?.message || String(error);
  } finally {
    $("signInBtn").disabled = false;
    $("signInBtn").textContent = "Sign in";
  }
}

async function signOutHosted() {
  await chrome.runtime.sendMessage({ type: "SIGN_OUT_HOSTED" });
  connection = null;
  activeEpisode = null;
  renderActiveEpisode();
  setStatus("Signed out of JournalMe Companion.");
  await loadConnection();
  await loadAccounts();
  $("recent").innerHTML = '<div class="muted">Sign in to load your episodes.</div>';
}

async function openAuthRoute(path) {
  await chrome.runtime.sendMessage({ type: "ROUTE_APP", path, activate: true });
}

document.querySelectorAll(".phase").forEach((button) => button.addEventListener("click", () => setPhase(button.dataset.phase)));
for (const [buttonId, inputId, group] of [
  ["addSetupCustom", "setupCustom", "setup"],
  ["addExecutionCustom", "executionCustom", "execution"],
  ["addEmotionCustom", "emotionCustom", "emotion"],
]) {
  $(buttonId).addEventListener("click", () => addCustomTag(group, inputId));
  $(inputId).addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void addCustomTag(group, inputId);
    }
  });
}

$("account").addEventListener("change", async () => {
  await chrome.storage.local.set({ companionAccountId: $("account").value || null });
  activeEpisode = null;
  renderActiveEpisode();
  await loadEpisodes();
});
$("brokerSyncBtn").addEventListener("click", () => $("brokerFiles").click());
$("brokerFiles").addEventListener("change", (event) => void syncTradovateReports(event.target.files));
$("captureBtn").addEventListener("click", captureNow);
$("saveBtn").addEventListener("click", saveMoment);
$("clearBtn").addEventListener("click", clearPending);
$("refreshBtn").addEventListener("click", reconcileAndLoadEpisodes);
$("endEpisodeBtn").addEventListener("click", endEpisode);
$("openJournalBtn").addEventListener("click", openJournalMe);
$("signInBtn").addEventListener("click", signInHosted);
$("authPassword").addEventListener("keydown", (event) => { if (event.key === "Enter") void signInHosted(); });
$("signOutBtn").addEventListener("click", signOutHosted);
$("registerBtn").addEventListener("click", () => openAuthRoute("/register"));
$("forgotBtn").addEventListener("click", () => openAuthRoute("/forgot-password"));
$("openSavedBtn").addEventListener("click", () => lastSavedRoute && chrome.runtime.sendMessage({ type: "ROUTE_APP", path: lastSavedRoute, activate: true }));

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.pendingCapture) {
    pendingCapture = changes.pendingCapture.newValue || null;
    renderPending();
  }
  if (changes.companionAuth || changes.settings) {
    void loadConnection().then(async (result) => {
      await loadAccounts();
      if (result?.ok) await reconcileAndLoadEpisodes();
      else $("recent").innerHTML = '<div class="muted">Sign in to load your episodes.</div>';
    });
  }
});

(async () => {
  await loadCustomTags();
  await loadPending();
  const result = await loadConnection();
  await loadAccounts();
  if (result?.ok) await reconcileAndLoadEpisodes();
  else $("recent").innerHTML = '<div class="muted">Sign in to load your episodes.</div>';
})();
