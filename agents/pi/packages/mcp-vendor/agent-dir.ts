import { join } from "node:path";
import { pluginAgentDir } from "@agentcfg/pi-runtime/plugin-settings";
export function getConfigDirName(): string { return ".pi"; }
export function getAgentDir(): string { return pluginAgentDir(); }
export function getAgentPath(...segments: string[]): string { return join(getAgentDir(), ...segments); }
export function getAppName(): string { return "pi"; }
export function getAppClientUri(): string | undefined { return undefined; }
