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

let eventType = "entry";
let pendingCapture = null;
let customTags = { setup: [], execution: [], emotion: [] };
let lastSavedRoute = null;
let connection = null;
const selected = {
  setup: new Set(),
  execution: new Set(),
  emotion: new Set(),
};

const $ = (id) => document.getElementById(id);
const sidePanelPort = chrome.runtime.connect({ name: "journalme-sidepanel" });


function uniqueTags(values) {
  const seen = new Set();
  return values.filter((value) => {
    const key = value.trim().toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function renderChips(containerId, group) {
  const container = $(containerId);
  const defaults = DEFAULT_TAGS[group];
  const customs = customTags[group] || [];
  const tags = uniqueTags([...defaults, ...customs]);
  container.innerHTML = "";
  for (const tag of tags) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chip${customs.some((item) => item.toLowerCase() === tag.toLowerCase()) ? " custom-chip" : ""}`;
    button.textContent = tag;
    if (selected[group].has(tag)) button.classList.add("selected");
    button.addEventListener("click", () => {
      if (selected[group].has(tag)) {
        selected[group].delete(tag);
        button.classList.remove("selected");
      } else {
        selected[group].add(tag);
        button.classList.add("selected");
      }
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

function formatCapturedAt(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function renderPending() {
  const preview = $("preview");
  const empty = $("emptyPreview");
  if (!pendingCapture?.screenshotDataUrl) {
    preview.style.display = "none";
    empty.style.display = "grid";
    $("platform").textContent = "No capture";
    $("capturedAt").textContent = "";
    return;
  }
  preview.src = pendingCapture.screenshotDataUrl;
  preview.style.display = "block";
  empty.style.display = "none";
  $("platform").textContent = pendingCapture.platform || "Browser";
  $("capturedAt").textContent = formatCapturedAt(pendingCapture.capturedAt);
  if (!$("symbol").value && pendingCapture.detectedSymbol) {
    $("symbol").value = pendingCapture.detectedSymbol;
  }
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
  const authCard = $("authCard");
  const signOutBtn = $("signOutBtn");
  const brokerSyncCard = $("brokerSyncCard");
  dot.className = "connection-dot";
  if (result?.ok && result.mode === "hosted") {
    dot.classList.add("connected");
    title.textContent = "Signed in to JournalMe";
    detail.textContent = result.userEmail || "Cloud account connected";
    authCard.hidden = true;
    signOutBtn.hidden = false;
    brokerSyncCard.hidden = false;
    return result;
  }
  if (result?.mode === "hosted") {
    dot.classList.add("warning");
    title.textContent = "Sign in to sync";
    detail.textContent = "Your captures can sync without the website being open";
    authCard.hidden = false;
    signOutBtn.hidden = true;
    brokerSyncCard.hidden = true;
    return result;
  }
  dot.classList.add("local");
  title.textContent = "Local development mode";
  detail.textContent = "Saving to the configured local JournalMe API";
  authCard.hidden = true;
  signOutBtn.hidden = true;
  brokerSyncCard.hidden = false;
  return result;
}


async function dataUrlToBlob(dataUrl) {
  const response = await fetch(dataUrl);
  return await response.blob();
}

async function journalFetch(path, options = {}) {
  const context = await authContext();
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
        const prefix = issue.filename ? `${issue.filename}: ` : "";
        parts.push(`${prefix}${issue.reason || "Invalid report data."}`);
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
  try {
    await journalFetch(`/api/v1/imports/${encodeURIComponent(sessionId)}/cancel`, { method: "POST" });
  } catch {
    // The preview remains visible in Import history if cancellation itself fails.
  }
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
    if (!previewResponse.ok) {
      throw new Error(apiDetailMessage(preview, `Preview failed (${previewResponse.status}).`));
    }

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
    if (!commitResponse.ok) {
      throw new Error(apiDetailMessage(commit, `Sync failed (${commitResponse.status}).`));
    }
    const created = commit.created || {};
    const balanceNote = (preview.reports || []).some((report) => report.type === "account_balance_history")
      ? ` · ${Number(created.daily_balances || 0)} balance snapshot${Number(created.daily_balances || 0) === 1 ? "" : "s"}`
      : " · balance unchanged";
    statusBox.className = "status ok";
    statusBox.textContent = `${Number(created.trades || 0)} new trade${Number(created.trades || 0) === 1 ? "" : "s"} · ${Number(created.fills || 0)} fills${balanceNote}`;
    await loadAccounts();
    await reconcileAndLoadRecent();
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
  try {
    url = new URL(tab.url);
  } catch {
    return true;
  }
  if (!/^https?:$/.test(url.protocol)) {
    throw new Error("Open a normal web page before taking a screenshot.");
  }
  const originPattern = `${url.origin}/*`;
  const hasAccess = await chrome.permissions.contains({ origins: [originPattern] });
  if (hasAccess) return true;

  const granted = await chrome.permissions.request({ origins: [originPattern] });
  if (!granted) {
    throw new Error(`Allow JournalMe access to ${url.hostname} so the Take screenshot button can capture this page. Alt+C still works without permanent site access.`);
  }
  return true;
}

async function captureNow() {
  try {
    setStatus("Capturing...");
    $("captureBtn").disabled = true;
    await ensureCapturePermission();
    const response = await chrome.runtime.sendMessage({ type: "CAPTURE_NOW" });
    if (!response?.ok) {
      setStatus(response?.error || "Capture failed.", "error");
      return;
    }
    pendingCapture = response.pending;
    renderPending();
    setStatus("Screenshot ready.", "ok");
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
  setStatus("Pending capture cleared.");
}

function buildMetadata() {
  if (!pendingCapture) throw new Error("Take a screenshot first.");
  const symbol = $("symbol").value.trim().toUpperCase();
  if (!symbol && eventType !== "wait") throw new Error("Add a symbol before saving.");
  return {
    captured_at: pendingCapture.capturedAt,
    event_type: eventType,
    account_id: $("account").value || null,
    symbol: symbol || null,
    side: $("side").value || null,
    note: $("note").value.trim() || null,
    setup_tags: [...selected.setup],
    execution_tags: [...selected.execution],
    emotion_tags: [...selected.emotion],
    platform: pendingCapture.platform || null,
    page_url: pendingCapture.pageUrl || null,
    page_title: pendingCapture.pageTitle || null,
    source: "journalme_chrome_extension",
    match_status: "unmatched",
    matched_trade_id: null
  };
}

async function routeCapture(captureId, activate = false) {
  lastSavedRoute = `/captures?selected=${encodeURIComponent(captureId)}`;
  $("openSavedBtn").hidden = false;
  return chrome.runtime.sendMessage({ type: "ROUTE_APP", path: lastSavedRoute, activate });
}

async function saveCapture() {
  try {
    setStatus("Saving...");
    $("saveBtn").disabled = true;
    $("openSavedBtn").hidden = true;
    const metadata = buildMetadata();
    const screenshotBlob = await dataUrlToBlob(pendingCapture.screenshotDataUrl);
    const form = new FormData();
    form.append("metadata", JSON.stringify(metadata));
    form.append("screenshot", screenshotBlob, `journalme-${Date.now()}.png`);
    const response = await journalFetch("/api/v1/captures", { method: "POST", body: form });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body?.detail || body?.message || `Save failed (${response.status}).`);

    if (body?.match_status === "matched") setStatus("Saved and matched to the trade.", "ok");
    else if (body?.match_status === "suggested") setStatus("Saved. JournalMe found a possible trade match.", "ok");
    else setStatus("Saved to JournalMe.", "ok");

    await chrome.storage.local.remove("pendingCapture");
    pendingCapture = null;
    $("note").value = "";
    selected.setup.clear();
    selected.execution.clear();
    selected.emotion.clear();
    renderAllTags();
    renderPending();
    await loadRecent();

    const context = connection || await authContext();
    if (body?.id && context?.settings?.autoRouteAfterSave !== false) {
      await routeCapture(body.id, false);
    }
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
    const context = connection || await authContext();
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
    if (!accounts?.length) {
      select.innerHTML = '<option value="">No trading accounts yet</option>';
      hint.textContent = "Captures still sync to your journal. Create an account in JournalMe when you are ready.";
    } else {
      hint.textContent = `${accounts.length} JournalMe account${accounts.length === 1 ? "" : "s"} available.`;
    }
  } catch (error) {
    console.warn("JournalMe account load failed", error);
    select.innerHTML = '<option value="">Account list unavailable</option>';
    select.disabled = true;
    hint.textContent = error?.message || "Could not load accounts.";
  }
}


async function removeRecentCapture(item) {
  if (!confirm(`Remove ${item.symbol || "this"} capture? This removes only the Companion capture and screenshot, not the trade or journal.`)) return;
  try {
    const response = await journalFetch(`/api/v1/captures/${item.id}`, { method: "DELETE" });
    if (!response.ok) throw new Error(`API ${response.status}`);
    setStatus("Capture removed.", "ok");
    await loadRecent();
  } catch (error) {
    console.error("JournalMe remove capture failed:", error);
    setStatus(error?.message || "Capture could not be removed.", "error");
  }
}

async function loadRecent() {
  const recent = $("recent");
  try {
    const response = await journalFetch("/api/v1/captures?limit=8");
    if (!response.ok) throw new Error(`API ${response.status}`);
    const items = await response.json();
    if (!Array.isArray(items) || !items.length) {
      recent.innerHTML = '<div class="muted">No captures yet.</div>';
      return;
    }
    recent.innerHTML = "";
    for (const item of items) {
      const wrap = document.createElement("div");
      wrap.className = "recent-item";

      const open = document.createElement("button");
      open.type = "button";
      open.className = "recent-open";
      open.addEventListener("click", () => routeCapture(item.id, true));

      const main = document.createElement("div");
      main.className = "recent-main";
      const left = document.createElement("span");
      left.textContent = `${item.symbol || "WAIT"} · ${(item.event_type || "").toUpperCase()}`;
      const right = document.createElement("span");
      right.textContent = formatCapturedAt(item.captured_at || item.created_at);
      main.append(left, right);
      const note = document.createElement("div");
      note.className = "recent-note";
      const matchLabel = item.match_status === "matched" ? "MATCHED" : item.match_status === "suggested" ? "POSSIBLE MATCH" : "UNMATCHED";
      note.textContent = `${matchLabel} · ${item.note || item.platform || "Saved capture"}`;
      open.append(main, note);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "recent-remove";
      remove.title = "Remove capture";
      remove.setAttribute("aria-label", `Remove ${item.symbol || "capture"}`);
      remove.textContent = "×";
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        void removeRecentCapture(item);
      });

      wrap.append(open, remove);
      recent.appendChild(wrap);
    }
  } catch (error) {
    console.error("JournalMe loadRecent failed:", error);
    recent.innerHTML = `<div class="muted">${error?.message || "Connection unavailable"}</div>`;
  }
}

async function reconcileAndLoadRecent() {
  try {
    await journalFetch("/api/v1/captures/reconcile", { method: "POST" });
  } catch (error) {
    console.warn("JournalMe reconciliation request failed:", error);
  }
  await loadRecent();
}

async function openJournalMe() {
  await chrome.runtime.sendMessage({ type: "ROUTE_APP", path: "/captures", activate: true });
}

async function signInHosted() {
  const email = $("authEmail").value.trim();
  const password = $("authPassword").value;
  const errorBox = $("authError");
  errorBox.textContent = "";
  if (!email || !password) {
    errorBox.textContent = "Enter your email and password.";
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
    await reconcileAndLoadRecent();
  } catch (error) {
    errorBox.textContent = error?.message || String(error);
  } finally {
    $("signInBtn").disabled = false;
    $("signInBtn").textContent = "Sign in";
  }
}

async function signOutHosted() {
  await chrome.runtime.sendMessage({ type: "SIGN_OUT_HOSTED" });
  connection = null;
  setStatus("Signed out of JournalMe Companion.");
  await loadConnection();
  await loadAccounts();
  $("recent").innerHTML = '<div class="muted">Sign in to load your captures.</div>';
}

async function openAuthRoute(path) {
  await chrome.runtime.sendMessage({ type: "ROUTE_APP", path, activate: true });
}


document.querySelectorAll(".seg").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".seg").forEach(el => el.classList.remove("active"));
    button.classList.add("active");
    eventType = button.dataset.event;
  });
});

const customBindings = [
  ["addSetupCustom", "setupCustom", "setup"],
  ["addExecutionCustom", "executionCustom", "execution"],
  ["addEmotionCustom", "emotionCustom", "emotion"],
];
for (const [buttonId, inputId, group] of customBindings) {
  $(buttonId).addEventListener("click", () => addCustomTag(group, inputId));
  $(inputId).addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addCustomTag(group, inputId);
    }
  });
}

$("account").addEventListener("change", () => chrome.storage.local.set({ companionAccountId: $("account").value || null }));
$("brokerSyncBtn").addEventListener("click", () => $("brokerFiles").click());
$("brokerFiles").addEventListener("change", (event) => void syncTradovateReports(event.target.files));
$("captureBtn").addEventListener("click", captureNow);
$("saveBtn").addEventListener("click", saveCapture);
$("clearBtn").addEventListener("click", clearPending);
$("refreshBtn").addEventListener("click", reconcileAndLoadRecent);
$("openJournalBtn").addEventListener("click", openJournalMe);
$("signInBtn").addEventListener("click", signInHosted);
$("authPassword").addEventListener("keydown", (event) => {
  if (event.key === "Enter") void signInHosted();
});
$("signOutBtn").addEventListener("click", signOutHosted);
$("registerBtn").addEventListener("click", () => openAuthRoute("/register"));
$("forgotBtn").addEventListener("click", () => openAuthRoute("/forgot-password"));
$("openSavedBtn").addEventListener("click", () => lastSavedRoute && chrome.runtime.sendMessage({ type: "ROUTE_APP", path: lastSavedRoute, activate: true }));

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.companionAuth || changes.settings) {
    void loadConnection().then(async (result) => {
      await loadAccounts();
      if (result?.ok) await reconcileAndLoadRecent();
      else $("recent").innerHTML = '<div class="muted">Sign in to load your captures.</div>';
    });
  }
});

(async () => {
  await loadCustomTags();
  await loadPending();
  const result = await loadConnection();
  await loadAccounts();
  if (result?.ok) await reconcileAndLoadRecent();
  else $("recent").innerHTML = '<div class="muted">Sign in to load your captures.</div>';
})();
