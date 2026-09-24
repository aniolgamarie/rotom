export function pluginSettings(capability: string, key: string): Record<string, unknown>;
export function pluginAgentDir(): string;
export function managedSettingWrite(): never;
export function pluginProjectRoot(cwd: string): string | null;
