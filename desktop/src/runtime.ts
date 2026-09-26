export type DesktopRuntimeMode = "local";

export function getDesktopRuntimeMode(env: NodeJS.ProcessEnv = process.env): DesktopRuntimeMode {
  const mode = env.JOURNALME_DESKTOP_RUNTIME_MODE ?? "local";
  if (mode !== "local") {
    throw new Error("Unsupported JOURNALME_DESKTOP_RUNTIME_MODE. Cloud mode is not implemented in v0.1.");
  }
  return mode;
}
