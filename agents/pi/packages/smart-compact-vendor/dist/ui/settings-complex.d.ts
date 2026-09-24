import type { ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { type SettingItem } from "@earendil-works/pi-tui";
import type { CompactConfig } from "../types.ts";
import { type GlobalConfigPath, type GlobalConfigValue } from "../utils/config.ts";
export type GlobalConfigWriter = (path: GlobalConfigPath, value: GlobalConfigValue) => Promise<CompactConfig>;
export declare function modelSettingsItems(ctx: ExtensionCommandContext, requestRender: () => void, writeConfig?: GlobalConfigWriter): SettingItem[];
export declare function complexSettingsCategories(ctx: ExtensionCommandContext, requestRender: () => void, writeConfig?: GlobalConfigWriter): SettingItem[];
export declare function complexConfigPaths(): GlobalConfigPath[];
//# sourceMappingURL=settings-complex.d.ts.map