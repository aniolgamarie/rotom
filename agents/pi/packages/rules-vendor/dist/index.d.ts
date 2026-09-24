import { type ExtensionAPI, type ToolResultEvent } from "@earendil-works/pi-coding-agent";
import type { RuleConfigPatch } from "./discovery.js";
import type { PendingRule } from "./types.js";
export declare const CUSTOM_MESSAGE_TYPE = "pi-rules-injection";
export declare const NUDGE_MESSAGE_TYPE = "pi-rules-nudge";
export declare const CONFIG_EVENT = "pi-rules:config";
export declare function emitPiRulesConfig(pi: Pick<ExtensionAPI, "events">, config: RuleConfigPatch): void;
export declare function makeExtension(): (pi: ExtensionAPI) => void;
export declare function isSuccessfulGitCommit(event: ToolResultEvent): boolean;
interface SkillBlock {
    name: string;
    content: string;
}
export declare function createInjection(entries: PendingRule[], skillBlocks?: SkillBlock[]): {
    customType: string;
    content: string;
    display: boolean;
    details: {
        sources: string[];
        targets: {
            [k: string]: string[];
        };
        skills: string[];
    };
};
declare const _default: (pi: ExtensionAPI) => void;
export default _default;
//# sourceMappingURL=index.d.ts.map