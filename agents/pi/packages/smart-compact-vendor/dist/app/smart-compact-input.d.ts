import type { CompactionMode } from "../types.ts";
export interface SmartCompactInput {
    modelArg?: string;
    mode?: CompactionMode;
    verbose: boolean;
    dryRun: boolean;
    action?: "metrics" | "dashboard" | "restore" | "loops" | "settings";
    focus?: string;
    note?: string;
    maxLlmCalls?: number;
    maxLlmInputTokens?: number;
    timeoutMs?: number;
}
export type SmartCompactInputResult = {
    ok: true;
    value: SmartCompactInput;
} | {
    ok: false;
    error: string;
};
export declare function parseSmartCompactCommand(args: string, isModelToken: (token: string) => boolean): SmartCompactInputResult;
export declare function parseSmartCompactTool(params: Record<string, unknown>): SmartCompactInputResult;
//# sourceMappingURL=smart-compact-input.d.ts.map