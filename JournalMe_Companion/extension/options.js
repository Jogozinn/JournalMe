const DEFAULTS = {
  apiBase: "https://p01--journalme-api--z928s7lw8hps.code.run",
  appBase: "https://journalme-beige.vercel.app",
  connectionMode: "hosted",
  autoRouteAfterSave: true,
};

async function load() {
  const data = await chrome.storage.local.get("settings");
  const settings = { ...DEFAULTS, ...(data.settings || {}) };
  document.getElementById("connectionMode").value = settings.connectionMode;
  document.getElementById("apiBase").value = settings.apiBase;
  document.getElementById("appBase").value = settings.appBase;
  document.getElementById("autoRouteAfterSave").checked = settings.autoRouteAfterSave !== false;
}

async function save() {
  const data = await chrome.storage.local.get("settings");
  const existing = { ...DEFAULTS, ...(data.settings || {}) };
  const connectionMode = document.getElementById("connectionMode").value;
  const apiBase = document.getElementById("apiBase").value.trim().replace(/\/$/, "");
  const appBase = document.getElementById("appBase").value.trim().replace(/\/$/, "");
  const autoRouteAfterSave = document.getElementById("autoRouteAfterSave").checked;
  await chrome.storage.local.set({ settings: { ...existing, connectionMode, apiBase, appBase, autoRouteAfterSave } });
  if (connectionMode === "local") {
    await chrome.storage.local.remove(["companionAuth", "companionAccountId"]);
  }
  document.getElementById("status").textContent = "Saved.";
}

document.getElementById("save").addEventListener("click", save);
load();
