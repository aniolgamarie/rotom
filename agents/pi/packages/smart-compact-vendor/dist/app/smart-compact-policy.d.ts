import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { CompactConfig } from "../types.ts";
type AgentToolAccess = CompactConfig["agentToolAccess"];
export interface SmartCompactPolicySnapshot {
    agentToolAccess: AgentToolAccess;
    /** Effective host state after allowlists and other tool controls are applied. */
    agentToolEnabled: boolean;
    autoTrigger: boolean;
    showStatus: boolean;
}
export interface DesiredSmartCompactPolicy {
    agentToolAccess: AgentToolAccess;
    autoTrigger: boolean;
    showStatus: boolean;
}
export type SmartCompactPolicyField = keyof DesiredSmartCompactPolicy;
type SmartCompactPolicyUpdate = {
    ok: true;
    policy: SmartCompactPolicySnapshot;
} | {
    ok: false;
    policy: SmartCompactPolicySnapshot;
    error: string;
};
export interface SmartCompactPolicy {
    snapshot(): SmartCompactPolicySnapshot;
    branchOverrides(): Readonly<Partial<DesiredSmartCompactPolicy>>;
    isAgentToolEnabled(): boolean;
    isAutoTriggerEnabled(): boolean;
    restore(ctx: ExtensionContext): void;
    update(patch: Partial<DesiredSmartCompactPolicy>, ctx: ExtensionContext): SmartCompactPolicyUpdate;
    reset(field: SmartCompactPolicyField, ctx: ExtensionContext): SmartCompactPolicyUpdate;
}
export declare function createSmartCompactPolicy(pi: ExtensionAPI): SmartCompactPolicy;
export {};
//# sourceMappingURL=smart-compact-policy.d.ts.map