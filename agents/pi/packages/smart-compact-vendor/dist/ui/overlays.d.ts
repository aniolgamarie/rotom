/**
 * TUI overlays: model/profile selection, progress, result screen.
 */
import type { ExtensionCommandContext, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { CompactConfig, CompactionMode, ModelOption, ProgressState, SmartCompactDetails, StructuredExtraction } from "../types.ts";
import { type SmartCompactServices } from "../infra/services.ts";
import { type ManualPreflight } from "../app/preflight.ts";
import type { EffectiveCompactionMode } from "../types.ts";
export declare function recommendPreflight(plans: ReadonlyMap<EffectiveCompactionMode, ManualPreflight>): {
    mode: EffectiveCompactionMode;
    reason: string;
};
/** Compact decision copy; technical planner data stays behind D. */
export declare function formatPreflightSummary(preflight: ManualPreflight, modelLabel: string, details?: boolean): string[];
export declare function showProgressOverlay(ctx: ExtensionContext, state: ProgressState): void;
export declare function clearCompactProgress(ctx: ExtensionContext): void;
export declare function notifyAppliedCompaction(ctx: ExtensionContext, details: SmartCompactDetails, concise: boolean): void;
export declare function showResultScreen(ctx: ExtensionContext, details: SmartCompactDetails, extraction: StructuredExtraction, services: SmartCompactServices, opts?: {
    approval?: boolean;
    summary?: string;
}): Promise<"apply" | "cancel" | "closed">;
export declare function showCompactUI(ctx: ExtensionCommandContext, opts: {
    contextTokens: number;
    contextPercent: number;
    activeModelLabel: string;
    defaultModelIndex: number;
    config: CompactConfig;
}): Promise<{
    model: ModelOption;
    mode: CompactionMode;
} | null>;
export { showBackupViewer, showRestoreAction, showRestorePicker, } from "./backup-overlays.ts";
export { showOpenLoopsUI } from "./open-loops-overlay.ts";
//# sourceMappingURL=overlays.d.ts.map