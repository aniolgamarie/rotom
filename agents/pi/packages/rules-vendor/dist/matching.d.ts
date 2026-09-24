import type { ToolCallEvent, ToolResultEvent } from "@earendil-works/pi-coding-agent";
import type { Rule } from "./types.js";
export declare function extractTarget(event: ToolCallEvent | ToolResultEvent, cwd: string): string | undefined;
export declare function ruleMatchesTarget(rule: Rule, target: string): boolean;
export declare function ruleMatchesToolCallEvent(rule: Rule, toolName: string): boolean;
//# sourceMappingURL=matching.d.ts.map