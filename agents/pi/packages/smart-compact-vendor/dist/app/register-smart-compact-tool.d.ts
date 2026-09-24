import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { PendingSlot } from "./pending-slot.ts";
import type { SessionRunLock } from "./session-run-lock.ts";
import type { SmartCompactPolicy } from "./smart-compact-policy.ts";
interface SmartCompactToolDependencies {
    pendingRef: PendingSlot;
    runLock: SessionRunLock;
    onNativeApplyError: (runId: string) => boolean;
    policy: SmartCompactPolicy;
}
export declare function registerSmartCompactTool(pi: ExtensionAPI, dependencies: SmartCompactToolDependencies): void;
export {};
//# sourceMappingURL=register-smart-compact-tool.d.ts.map