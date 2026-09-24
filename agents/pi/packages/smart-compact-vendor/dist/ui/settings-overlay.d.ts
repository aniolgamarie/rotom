import { type ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import { type Component, type Focusable, SettingsList, type SettingItem } from "@earendil-works/pi-tui";
import { type GlobalConfigPath } from "../utils/config.ts";
import type { CompactConfig } from "../types.ts";
import { type GlobalConfigWriter } from "./settings-complex.ts";
import type { SmartCompactPolicy, SmartCompactPolicySnapshot } from "../app/smart-compact-policy.ts";
type GlobalChoiceGroup = "behavior" | "reasoning" | "safety" | "advanced";
type GlobalSettingWriter = typeof updateGlobalChoiceSetting;
export type GlobalSettingApplied = (path: GlobalConfigPath, config: CompactConfig) => void | Promise<void>;
interface GlobalSettingState {
    display: string;
    config?: CompactConfig;
}
export declare class GlobalSettingsCoordinator {
    private readonly writer;
    private queue;
    private readonly confirmed;
    private confirmedConfig;
    private readonly pending;
    private readonly listeners;
    constructor(writer?: GlobalSettingWriter);
    display(id: GlobalConfigPath): string;
    subscribe(ids: readonly GlobalConfigPath[], listener: (id: GlobalConfigPath, state: GlobalSettingState) => void): () => void;
    submit(group: GlobalChoiceGroup, id: GlobalConfigPath, display: string, onError: (message: string) => void, onApplied?: GlobalSettingApplied): void;
    settled(): Promise<void>;
    private emit;
}
export declare function globalChoiceSettingsItems(group: GlobalChoiceGroup, config: CompactConfig, coordinator?: GlobalSettingsCoordinator): SettingItem[];
export declare function updateGlobalChoiceSetting(group: GlobalChoiceGroup, id: string, display: string): Promise<CompactConfig>;
export declare function sessionSettingsItems(policy: SmartCompactPolicy): SettingItem[];
export declare function updateSessionSetting(policy: SmartCompactPolicy, ctx: ExtensionCommandContext, id: string, value: string): {
    ok: true;
    policy: SmartCompactPolicySnapshot;
} | {
    ok: false;
    policy: SmartCompactPolicySnapshot;
    error: string;
};
export declare function settingsCategoryItems(policy: SmartCompactPolicy, ctx: ExtensionCommandContext, requestRender?: () => void, coordinator?: GlobalSettingsCoordinator, onApplied?: GlobalSettingApplied, writeConfig?: GlobalConfigWriter): SettingItem[];
export declare function createSettingsRoot(policy: SmartCompactPolicy, ctx: ExtensionCommandContext, onCancel: () => void, requestRender?: () => void, coordinator?: GlobalSettingsCoordinator, onApplied?: GlobalSettingApplied, writeConfig?: GlobalConfigWriter): SettingsList;
export declare function createSettingsController(root: SettingsList, display: Component, requestRender: () => void): Component & Focusable;
/** Open the unified Smart Compact settings panel. */
export declare function showSmartCompactSettings(ctx: ExtensionCommandContext, policy: SmartCompactPolicy, coordinator?: GlobalSettingsCoordinator, onApplied?: GlobalSettingApplied): Promise<void>;
export {};
//# sourceMappingURL=settings-overlay.d.ts.map