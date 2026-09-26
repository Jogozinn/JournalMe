const DEFAULT_SETTINGS = {
  apiBase: "http://127.0.0.1:8066",
  appBase: "http://localhost:3070",
  connectionMode: "local",
  autoRouteAfterSave: true,
};

let sidePanelConnections = 0;

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "journalme-sidepanel") return;
  sidePanelConnections += 1;
  port.onDisconnect.addListener(() => {
    sidePanelConnections = Math.max(0, sidePanelConnections - 1);
  });
});

function isoNow() {
  return new Date().toISOString();
}

function detectPlatform(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes("tradingview")) return "TradingView";
    if (host.includes("tradelocker")) return "TradeLocker";
    if (host.includes("tradovate")) return "Tradovate";
    if (host.includes("topstepx")) return "TopstepX";
    return host || "Browser";
  } catch {
    return "Browser";
  }
}

function detectSymbol(title, url) {
  const raw = `${title || ""} ${url || ""}`.toUpperCase();
  const known = [
    "MNQ1!", "NQ1!", "MES1!", "ES1!", "MGC1!", "GC1!", "MCL1!", "CL1!",
    "MNQ", "NQ", "MES", "ES", "MGC", "GC", "MCL", "CL",
    "NAS100", "USTEC", "XAUUSD", "XAU", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD"
  ];
  for (const symbol of known) {
    if (raw.includes(symbol)) return symbol;
  }
  const tv = raw.match(/SYMBOL=([A-Z0-9:_!.-]+)/);
  if (tv) {
    const value = tv[1].split(":").pop();
    if (value) return value;
  }
  const firstToken = (title || "").trim().split(/\s+/)[0]?.toUpperCase();
  if (firstToken && /^[A-Z0-9:_!.-]{2,16}$/.test(firstToken)) {
    return firstToken.split(":").pop();
  }
  return "";
}

async function getSettings() {
  const data = await chrome.storage.local.get("settings");
  const settings = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
  if (JSON.stringify(settings) !== JSON.stringify(data.settings || {})) {
    await chrome.storage.local.set({ settings });
  }
  return settings;
}

async function createPendingCapture(tab) {
  if (!tab || !tab.id || !tab.windowId) {
    throw new Error("No active browser tab was found.");
  }
  const screenshotDataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
  const pending = {
    screenshotDataUrl,
    capturedAt: isoNow(),
    pageUrl: tab.url || "",
    pageTitle: tab.title || "",
    platform: detectPlatform(tab.url || ""),
    detectedSymbol: detectSymbol(tab.title || "", tab.url || "")
  };
  await chrome.storage.local.set({ pendingCapture: pending });
  return pending;
}

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

async function beginConnect() {
  const settings = await getSettings();
  const nonce = crypto.randomUUID();
  await chrome.storage.local.set({ pendingConnect: { nonce, createdAt: Date.now() } });
  const url = new URL("/companion/connect", settings.appBase);
  url.searchParams.set("extension_id", chrome.runtime.id);
  url.searchParams.set("nonce", nonce);
  await chrome.tabs.create({ url: url.toString(), active: true });
  return { ok: true, url: url.toString() };
}

async function refreshHostedSession(auth) {
  if (!auth?.refreshToken || !auth?.supabaseUrl || !auth?.supabaseAnonKey) {
    throw new Error("JournalMe Companion needs to reconnect to the web app.");
  }
  const response = await fetch(`${auth.supabaseUrl.replace(/\/$/, "")}/auth/v1/token?grant_type=refresh_token`, {
    method: "POST",
    headers: {
      apikey: auth.supabaseAnonKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refresh_token: auth.refreshToken }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.access_token) {
    await chrome.storage.local.remove("companionAuth");
    throw new Error(body?.msg || body?.error_description || "JournalMe sign-in expired. Reconnect the Companion.");
  }
  const next = {
    ...auth,
    accessToken: body.access_token,
    refreshToken: body.refresh_token || auth.refreshToken,
    expiresAt: body.expires_at || Math.floor(Date.now() / 1000) + Number(body.expires_in || 3600),
    connectedAt: Date.now(),
  };
  await chrome.storage.local.set({ companionAuth: next });
  return next;
}

async function getAuthContext() {
  const settings = await getSettings();
  if (settings.connectionMode !== "hosted") {
    return { ok: true, mode: "local", settings, headers: {} };
  }
  const data = await chrome.storage.local.get("companionAuth");
  let auth = data.companionAuth;
  if (!auth?.accessToken) {
    return { ok: false, mode: "hosted", settings, error: "Connect JournalMe Companion to the web app." };
  }
  const now = Math.floor(Date.now() / 1000);
  if (!auth.expiresAt || Number(auth.expiresAt) <= now + 90) {
    auth = await refreshHostedSession(auth);
  }
  return {
    ok: true,
    mode: "hosted",
    settings,
    userEmail: auth.userEmail || null,
    headers: { Authorization: `Bearer ${auth.accessToken}` },
  };
}

async function routeApp(path = "/", activate = false) {
  const settings = await getSettings();
  const base = settings.appBase.replace(/\/$/, "");
  const targetUrl = new URL(path || "/", `${base}/`).toString();
  const tabs = await chrome.tabs.query({});
  const match = tabs.find((tab) => typeof tab.url === "string" && tab.url.startsWith(`${base}/`));
  if (match?.id) {
    await chrome.tabs.update(match.id, { url: targetUrl, active: activate });
    if (activate && match.windowId) await chrome.windows.update(match.windowId, { focused: true });
    return { ok: true, reused: true, tabId: match.id };
  }
  const created = await chrome.tabs.create({ url: targetUrl, active: activate });
  return { ok: true, reused: false, tabId: created.id };
}

chrome.runtime.onInstalled.addListener(async () => {
  await getSettings();
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command !== "capture-journalme") return;

  // Alt+C has one job: take a screenshot. If the Companion is closed,
  // open it. If it is already open, leave it open and only refresh the capture.
  if (sidePanelConnections === 0 && tab?.windowId) {
    chrome.sidePanel.open({ windowId: tab.windowId }).catch(async (error) => {
      console.error("JournalMe side panel failed", error);
      await chrome.storage.local.set({ lastCaptureError: String(error?.message || error) });
    });
  }

  (async () => {
    try {
      const targetTab = tab?.id ? tab : await activeTab();
      await createPendingCapture(targetTab);
    } catch (error) {
      console.error("JournalMe capture failed", error);
      await chrome.storage.local.set({ lastCaptureError: String(error?.message || error) });
    }
  })();
});


chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "CAPTURE_NOW") {
    (async () => {
      try {
        const tab = await activeTab();
        sendResponse({ ok: true, pending: await createPendingCapture(tab) });
      } catch (error) {
        sendResponse({ ok: false, error: String(error?.message || error) });
      }
    })();
    return true;
  }

  if (message?.type === "GET_ACTIVE_TAB_META") {
    (async () => {
      try {
        const tab = await activeTab();
        sendResponse({
          ok: true,
          meta: {
            pageUrl: tab?.url || "",
            pageTitle: tab?.title || "",
            platform: detectPlatform(tab?.url || ""),
            detectedSymbol: detectSymbol(tab?.title || "", tab?.url || "")
          }
        });
      } catch (error) {
        sendResponse({ ok: false, error: String(error?.message || error) });
      }
    })();
    return true;
  }

  if (message?.type === "BEGIN_CONNECT") {
    beginConnect().then(sendResponse).catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  if (message?.type === "GET_AUTH_CONTEXT") {
    getAuthContext().then(sendResponse).catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  if (message?.type === "DISCONNECT_HOSTED") {
    (async () => {
      const settings = await getSettings();
      await chrome.storage.local.remove(["companionAuth", "pendingConnect", "companionAccountId"]);
      await chrome.storage.local.set({
        settings: {
          ...settings,
          connectionMode: "local",
          apiBase: "http://127.0.0.1:8066",
        }
      });
      sendResponse({ ok: true });
    })().catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  if (message?.type === "ROUTE_APP") {
    routeApp(message.path || "/", Boolean(message.activate))
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }
});

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message?.type !== "JOURNALME_COMPANION_CONNECT") {
      sendResponse({ ok: false, error: "Unsupported JournalMe Companion message." });
      return;
    }
    const data = await chrome.storage.local.get(["pendingConnect", "settings"]);
    const settings = { ...DEFAULT_SETTINGS, ...(data.settings || {}) };
    const pending = data.pendingConnect;
    if (!pending?.nonce || message.nonce !== pending.nonce) {
      sendResponse({ ok: false, error: "This Companion connection request is no longer valid." });
      return;
    }
    if (Date.now() - Number(pending.createdAt || 0) > 10 * 60 * 1000) {
      await chrome.storage.local.remove("pendingConnect");
      sendResponse({ ok: false, error: "This Companion connection request expired. Try again." });
      return;
    }
    const expectedOrigin = new URL(settings.appBase).origin;
    const senderOrigin = sender.url ? new URL(sender.url).origin : "";
    if (senderOrigin !== expectedOrigin) {
      sendResponse({ ok: false, error: "The connection did not come from the configured JournalMe app." });
      return;
    }
    const required = ["accessToken", "refreshToken", "supabaseUrl", "supabaseAnonKey", "apiBase", "appBase"];
    for (const field of required) {
      if (!message[field] || typeof message[field] !== "string") {
        sendResponse({ ok: false, error: `Missing ${field}.` });
        return;
      }
    }
    const companionAuth = {
      accessToken: message.accessToken,
      refreshToken: message.refreshToken,
      expiresAt: Number(message.expiresAt || 0),
      supabaseUrl: message.supabaseUrl,
      supabaseAnonKey: message.supabaseAnonKey,
      userEmail: message.userEmail || null,
      connectedAt: Date.now(),
    };
    const storagePayload = {
      companionAuth,
      settings: {
        ...settings,
        connectionMode: "hosted",
        apiBase: message.apiBase.replace(/\/$/, ""),
        appBase: message.appBase.replace(/\/$/, ""),
      },
    };
    if (message.accountId && typeof message.accountId === "string") {
      storagePayload.companionAccountId = message.accountId;
    }
    await chrome.storage.local.set(storagePayload);
    await chrome.storage.local.remove("pendingConnect");
    sendResponse({ ok: true });
  })().catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
  return true;
});
