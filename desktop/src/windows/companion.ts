import { BrowserWindow, screen } from "electron";
import { join } from "node:path";

const COLLAPSED = { width: 52, height: 52 };
const EXPANDED = { width: 390, height: 700 };

export class CompanionWindow {
  private window: BrowserWindow | undefined;
  private collapsed = true;
  create(preload: string, collapsed: boolean): BrowserWindow {
    this.collapsed = collapsed;
    const size = collapsed ? COLLAPSED : EXPANDED;
    this.window = new BrowserWindow({
      ...size, show: false, frame: false, transparent: false, resizable: false,
      alwaysOnTop: true, skipTaskbar: true, maximizable: false, minimizable: false,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload },
      backgroundColor: "#101418",
    });
    this.window.setAlwaysOnTop(true, "floating");
    this.window.loadFile(join(__dirname, "renderer", "companion.html"));
    this.window.on("closed", () => { this.window = undefined; });
    return this.window;
  }
  showForDisplay(displayId?: number): void {
    if (!this.window) return;
    const display = displayId === undefined ? screen.getDisplayNearestPoint(screen.getCursorScreenPoint()) : screen.getAllDisplays().find((item) => item.id === displayId) ?? screen.getPrimaryDisplay();
    this.position(display); this.window.showInactive(); this.window.webContents.send("companion:shown");
  }
  hide(): void { this.window?.hide(); }
  toggle(): boolean { if (this.window?.isVisible()) { this.hide(); return false; } this.showForDisplay(); return true; }
  setCollapsed(value: boolean): boolean {
    if (!this.window) return value; this.collapsed = value;
    const display = screen.getDisplayMatching(this.window.getBounds()); const size = value ? COLLAPSED : EXPANDED;
    this.window.setSize(size.width, size.height); this.position(display); this.window.webContents.send("companion:collapsed", value); return value;
  }
  isCollapsed(): boolean { return this.collapsed; }
  get browserWindow(): BrowserWindow | undefined { return this.window; }
  private position(display: Electron.Display): void {
    if (!this.window) return; const { workArea } = display; const [width, height] = this.window.getSize();
    this.window.setPosition(workArea.x + workArea.width - width - 16, workArea.y + workArea.height - height - 16, false);
  }
}
