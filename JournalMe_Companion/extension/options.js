const DEFAULTS = {
  apiBase: "http://127.0.0.1:8066",
  appBase: "http://localhost:3070",
  connectionMode: "local",
  autoRouteAfterSave: true,
};

async function load() {
  const data = await chrome.storage.local.get("settings");
  const settings = { ...DEFAULTS, ...(data.settings || {}) };
  document.getElementById("apiBase").value = settings.apiBase;
  document.getElementById("appBase").value = settings.appBase;
  document.getElementById("autoRouteAfterSave").checked = settings.autoRouteAfterSave !== false;
}

async function save() {
  const data = await chrome.storage.local.get("settings");
  const existing = { ...DEFAULTS, ...(data.settings || {}) };
  const apiBase = document.getElementById("apiBase").value.trim().replace(/\/$/, "");
  const appBase = document.getElementById("appBase").value.trim().replace(/\/$/, "");
  const autoRouteAfterSave = document.getElementById("autoRouteAfterSave").checked;
  await chrome.storage.local.set({ settings: { ...existing, apiBase, appBase, autoRouteAfterSave } });
  document.getElementById("status").textContent = "Saved.";
}

document.getElementById("save").addEventListener("click", save);
load();
