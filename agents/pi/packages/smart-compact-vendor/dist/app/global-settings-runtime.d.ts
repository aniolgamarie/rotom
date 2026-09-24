import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ContextToolAvailability } from "./register-context-tools.ts";
import type { SmartCompactPolicy } from "./smart-compact-policy.ts";
import type { GlobalConfigPath } from "../utils/config.ts";
/** Apply the small subset of global settings that own live host state. */
export declare function applyGlobalSettingRuntime(path: GlobalConfigPath, ctx: ExtensionContext, policy: SmartCompactPolicy, contextTools: ContextToolAvailability): void;
//# sourceMappingURL=global-settings-runtime.d.ts.map