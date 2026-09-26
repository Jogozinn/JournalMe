import { app, BrowserWindow, desktopCapturer, dialog, globalShortcut, ipcMain, Menu, nativeImage, screen, shell, Tray } from "electron";
import { join } from "node:path";
import { BACKEND_URL, BackendManager } from "./services/backend";
import { captureStatusMessage, PendingCaptureStore, postCapture, validateSaveRequest } from "./services/capture";
import { DesktopLogger, logPath } from "./services/logger";
import { FrontendManager, isSafeFrontendNavigation } from "./services/frontend";
import { DesktopConfig, loadDesktopConfig, projectRoot, saveDesktopConfig } from "./config";
import { CompanionWindow } from "./windows/companion";
import { getDesktopRuntimeMode } from "./runtime";

let mainWindow: BrowserWindow | undefined;
let tray: Tray | undefined;
let quitting = false;
let config: DesktopConfig;
let frontendUrl: string | undefined;
const root = projectRoot();
const configPath = join(app.getPath("userData"), "desktop-config.json");
const logger = new DesktopLogger(logPath(app.getPath("userData")));
const backend = new BackendManager(root, logger, BACKEND_URL, !app.isPackaged);
const frontend = new FrontendManager(root, logger, !app.isPackaged || process.env.JOURNALME_DESKTOP_DEV === "1");
const captures = new PendingCaptureStore();
const companion = new CompanionWindow();

function saveConfig(): void { saveDesktopConfig(configPath, config); }
function showMainWindow(): void { if (!mainWindow && frontendUrl) createMainWindow(frontendUrl); mainWindow?.show(); mainWindow?.focus(); }
function createMainWindow(verifiedFrontendUrl: string): void {
  const saved = config.window;
  mainWindow = new BrowserWindow({
    width: saved?.width ?? 1440, height: saved?.height ?? 920, x: saved?.x, y: saved?.y,
    minWidth: 900, minHeight: 620, show: false, backgroundColor: "#101418",
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  logger.info("window.loading_verified_frontend", { url: verifiedFrontendUrl });
  void mainWindow.loadURL(verifiedFrontendUrl); mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.on("close", (event) => { if (!quitting) { event.preventDefault(); mainWindow?.hide(); logger.info("window.hidden_to_tray"); } });
  mainWindow.on("resize", persistWindow); mainWindow.on("move", persistWindow);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => { if (isSafeFrontendNavigation(url, verifiedFrontendUrl)) return { action: "allow" }; void shell.openExternal(url); return { action: "deny" }; });
  mainWindow.webContents.on("will-navigate", (event, url) => { if (!isSafeFrontendNavigation(url, verifiedFrontendUrl)) { event.preventDefault(); void shell.openExternal(url); } });
}
function showStartupError(message: string): void {
  mainWindow = new BrowserWindow({ width: 680, height: 420, show: false, backgroundColor: "#101418", webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  const body = encodeURIComponent(`<main style="font-family:Segoe UI,sans-serif;background:#101418;color:#e7ecef;min-height:100vh;padding:48px"><h1>JournalMe could not start</h1><p style="color:#b6c0c2;line-height:1.55">${message.replace(/[&<>]/g, "")}</p><p style="color:#8d9c9f">JournalMe will not load an unverified local application.</p></main>`);
  void mainWindow.loadURL(`data:text/html;charset=utf-8,${body}`); mainWindow.once("ready-to-show", () => mainWindow?.show());
}
function persistWindow(): void { if (!mainWindow || mainWindow.isMinimized() || mainWindow.isMaximized()) return; const bounds = mainWindow.getBounds(); config.window = bounds; saveConfig(); }
function createTray(): void {
  const icon = nativeImage.createFromPath(join(__dirname, "..", "assets", "icon.png"));
  tray = new Tray(icon); tray.setToolTip("JournalMe");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Open JournalMe", click: showMainWindow },
    { label: "Quick Capture", click: () => void openQuickCapture() },
    { label: "Show/Hide Companion", click: () => { const visible = companion.toggle(); config.companionVisible = visible; saveConfig(); } },
    { type: "separator" }, { label: "Quit JournalMe", click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on("double-click", showMainWindow);
}
async function takeScreenshot() {
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const maxWidth = Math.min(Math.round(display.size.width * display.scaleFactor), 2560);
  const maxHeight = Math.min(Math.round(display.size.height * display.scaleFactor), 1600);
  const sources = await desktopCapturer.getSources({ types: ["screen"], thumbnailSize: { width: maxWidth, height: maxHeight } });
  const source = sources.find((item) => Number(item.display_id) === display.id);
  if (!source || source.thumbnail.isEmpty()) throw new Error("JournalMe could not capture the selected display.");
  const png = source.thumbnail.toPNG(); const useJpeg = png.length > 9 * 1024 * 1024;
  const buffer = useJpeg ? source.thumbnail.toJPEG(92) : png;
  logger.info("screenshot.captured", { displayId: display.id, mime: useJpeg ? "image/jpeg" : "image/png", bytes: buffer.length });
  return captures.add({ buffer, mime: useJpeg ? "image/jpeg" : "image/png", capturedAt: new Date().toISOString(), displayId: display.id });
}
async function openQuickCapture(): Promise<void> { const preview = await takeScreenshot(); companion.setCollapsed(false); config.companionCollapsed = false; config.companionVisible = true; saveConfig(); companion.showForDisplay(preview.displayId); companion.browserWindow?.webContents.send("capture:ready", preview); }
function registerIpc(): void {
  ipcMain.handle("capture:request-screenshot", async () => { const preview = await takeScreenshot(); companion.showForDisplay(preview.displayId); return preview; });
  ipcMain.handle("capture:save", async (_, request: unknown) => {
    const raw = validateSaveRequest(request); const image = captures.get(raw.token); if (!image) throw new Error("Screenshot expired. Capture a new screenshot before saving.");
    const metadata = raw.metadata; logger.info("capture.saving", { eventType: metadata.event_type, symbol: metadata.symbol });
    const result = await postCapture(BACKEND_URL, metadata, image); captures.remove(raw.token); logger.info("capture.saved", { status: result.match_status, id: result.id });
    return { result, message: captureStatusMessage(result.match_status) };
  });
  ipcMain.handle("capture:list-recent", async () => { const response = await fetch(`${BACKEND_URL}/captures?limit=5`, { signal: AbortSignal.timeout(10_000) }); if (!response.ok) throw new Error("Could not load recent captures."); return response.json(); });
  ipcMain.handle("companion:set-collapsed", (_, value: unknown) => { if (typeof value !== "boolean") throw new Error("Invalid companion state."); config.companionCollapsed = companion.setCollapsed(value); saveConfig(); return config.companionCollapsed; });
  ipcMain.handle("companion:hide", () => { companion.hide(); config.companionVisible = false; saveConfig(); });
  ipcMain.handle("desktop:get-settings", () => ({ launchAtLogin: config.launchAtLogin, companionVisible: config.companionVisible }));
  ipcMain.handle("desktop:set-launch-at-login", (_, value: unknown) => { if (typeof value !== "boolean") throw new Error("Invalid launch-at-login setting."); app.setLoginItemSettings({ openAtLogin: value }); config.launchAtLogin = value; saveConfig(); return { launchAtLogin: value }; });
}
async function start(): Promise<void> {
  const runtimeMode = getDesktopRuntimeMode();
  config = loadDesktopConfig(configPath); app.setLoginItemSettings({ openAtLogin: config.launchAtLogin }); logger.info("desktop.starting", { root, runtimeMode });
  registerIpc(); await backend.ensureRunning(); frontendUrl = await frontend.ensureRunning(); createMainWindow(frontendUrl); createTray(); companion.create(join(__dirname, "preload.js"), config.companionCollapsed); if (config.companionVisible) companion.showForDisplay();
  const registered = globalShortcut.register("Alt+C", () => void openQuickCapture().catch((error: Error) => { logger.error("shortcut.capture_failed", { message: error.message }); companion.showForDisplay(); companion.browserWindow?.webContents.send("capture:error", error.message); }));
  logger.info("shortcut.registration", { accelerator: "Alt+C", registered }); if (!registered) companion.browserWindow?.webContents.send("capture:error", "Alt+C is already in use by another application.");
}
if (!app.requestSingleInstanceLock()) { app.quit(); } else {
  app.on("second-instance", () => showMainWindow()); app.whenReady().then(start).catch((error: Error) => { logger.error("desktop.start_failed", { message: error.message }); showStartupError(error.message); dialog.showErrorBox("JournalMe could not start", error.message); });
  app.on("before-quit", () => { quitting = true; globalShortcut.unregisterAll(); frontend.stopOwned(); backend.stopOwned(); logger.info("desktop.quitting"); });
}
