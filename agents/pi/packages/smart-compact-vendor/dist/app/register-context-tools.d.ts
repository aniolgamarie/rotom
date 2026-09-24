import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type ContextGraphScope } from "../infra/context-graph.ts";
export declare function resolveGraphScope(ctx: ExtensionContext): ContextGraphScope | null;
export interface ContextToolAvailability {
    apply(): void;
}
export declare function registerContextTools(pi: ExtensionAPI): ContextToolAvailability;
//# sourceMappingURL=register-context-tools.d.ts.map