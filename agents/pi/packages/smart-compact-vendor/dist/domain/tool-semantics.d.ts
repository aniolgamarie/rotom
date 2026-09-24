/**
 * Extract a non-empty file-path argument from a tool call, covering common key
 * names. Returns undefined when no usable path is present.
 */
export declare function extractToolPath(args: unknown): string | undefined;
export interface ShellFileOperations {
    modified: string[];
    deleted: string[];
}
/** Extract only explicit literal file targets from common mutating shell forms. */
export declare function extractShellFileOperations(args: unknown): ShellFileOperations;
export type ToolClass = "mutates" | "accesses" | "executes" | "other";
export type ToolOperation = "read" | "search" | "list" | "mutate" | "delete" | "execute" | "unknown";
/** Normalize provider wrappers and spelling differences without merging namespaces. */
export declare function normalizeToolName(name: unknown): string;
/**
 * Fine-grained EESV operation taxonomy. Argument shape is authoritative;
 * normalized names only disambiguate otherwise-safe path/text and access calls.
 */
export declare function classifyToolOperation(args: unknown, toolName?: string): ToolOperation;
/** Stable identity for deciding whether a later call is a retry of an earlier one. */
export declare function toolOperationSignature(toolName: string, args: Record<string, unknown>): string;
export declare function sameToolOperation(left: {
    name: string;
    arguments: Record<string, unknown>;
}, right: {
    name: string;
    arguments: Record<string, unknown>;
}): boolean;
/**
 * Broad compatibility classifier retained for existing name-agnostic callers.
 */
export declare function classifyTool(args: unknown): ToolClass;
//# sourceMappingURL=tool-semantics.d.ts.map