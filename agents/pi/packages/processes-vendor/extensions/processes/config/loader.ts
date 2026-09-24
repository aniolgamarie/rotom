// 只读agentcfg配置，不导入旧Pi目录，也不写global/local配置。
import { pluginSettings } from "@agentcfg/pi-runtime/plugin-settings";
import { DEFAULT_CONFIG } from "./defaults";
import type { ProcessProtocolConfig } from "./types";

function configured(): ProcessProtocolConfig {
  const value = pluginSettings("pi-processes", "processes");
  if (Object.keys(value).some(key => !Object.hasOwn(DEFAULT_CONFIG, key)) || Object.hasOwn(value, "execution")) throw new Error("AGENTCFG_PROCESS_CONFIG");
  return Object.fromEntries(Object.entries(DEFAULT_CONFIG).map(([key, defaults]) => [key, { ...defaults, ...(value[key] as object ?? {}) }])) as unknown as ProcessProtocolConfig;
}
export const configLoader = { getConfig: configured, async load() { configured(); }, drainMessages: (): string[] => [] };
export async function loadProcessConfig(): Promise<void> { await configLoader.load(); }
export function drainImportMessages(): string[] { return []; }
