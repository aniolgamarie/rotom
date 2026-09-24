import type { ExtensionAPI, ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { PendingSlot } from "./pending-slot.ts";
import type { SessionRunLock } from "./session-run-lock.ts";
import type { SmartCompactPolicy } from "./smart-compact-policy.ts";
import type { GlobalConfigPath } from "../utils/config.ts";
interface SmartCompactCommandDependencies {
    pendingRef: PendingSlot;
    runLock: SessionRunLock;
    onNativeApplyError: (runId: string) => boolean;
    policy: SmartCompactPolicy;
    onGlobalSettingApplied?: (path: GlobalConfigPath, ctx: ExtensionCommandContext) => void | Promise<void>;
}
export declare function registerSmartCompactCommand(pi: ExtensionAPI, dependencies: SmartCompactCommandDependencies): void;
export {};
//# sourceMappingURL=register-smart-compact-command.d.ts.map