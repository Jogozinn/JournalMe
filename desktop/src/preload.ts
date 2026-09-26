import { contextBridge, ipcRenderer } from "electron";
import { CaptureMetadata } from "./types";

contextBridge.exposeInMainWorld("journalmeDesktop", {
  requestScreenshot: () => ipcRenderer.invoke("capture:request-screenshot"),
  saveCapture: (token: string, metadata: CaptureMetadata) => ipcRenderer.invoke("capture:save", { token, metadata }),
  listRecentCaptures: () => ipcRenderer.invoke("capture:list-recent"),
  setCollapsed: (value: boolean) => ipcRenderer.invoke("companion:set-collapsed", value),
  hideCompanion: () => ipcRenderer.invoke("companion:hide"),
  getSettings: () => ipcRenderer.invoke("desktop:get-settings"),
  setLaunchAtLogin: (enabled: boolean) => ipcRenderer.invoke("desktop:set-launch-at-login", enabled),
  onShown: (callback: () => void) => ipcRenderer.on("companion:shown", callback),
  onCollapsed: (callback: (value: boolean) => void) => ipcRenderer.on("companion:collapsed", (_, value) => callback(Boolean(value))),
  onCaptureReady: (callback: (value: unknown) => void) => ipcRenderer.on("capture:ready", (_, value) => callback(value)),
  onCaptureError: (callback: (message: string) => void) => ipcRenderer.on("capture:error", (_, message) => callback(String(message))),
});
