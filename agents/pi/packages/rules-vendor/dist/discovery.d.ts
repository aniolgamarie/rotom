import Type from "typebox";
import type { DiscoveryResult, Rule, RuleDiagnostic } from "./types.js";
declare const RULE_SOURCE_SCHEMA: Type.TObject<{
    scope: Type.TUnion<[Type.TLiteral<"repo">, Type.TLiteral<"user">]>;
    kind: Type.TUnion<[Type.TLiteral<"pi">, Type.TLiteral<"agents">, Type.TLiteral<"claude">]>;
}>;
export declare const RULE_CONFIG_SCHEMA: Type.TObject<{
    enabled: Type.TOptional<Type.TBoolean>;
    sources: Type.TArray<Type.TObject<{
        scope: Type.TUnion<[Type.TLiteral<"repo">, Type.TLiteral<"user">]>;
        kind: Type.TUnion<[Type.TLiteral<"pi">, Type.TLiteral<"agents">, Type.TLiteral<"claude">]>;
    }>>;
    nudges: Type.TOptional<Type.TObject<{
        afterCommit: Type.TOptional<Type.TBoolean>;
    }>>;
}>;
export declare const RULE_CONFIG_PATCH_SCHEMA: Type.TObject<{
    enabled: Type.TOptional<Type.TBoolean>;
    sources: Type.TOptional<Type.TArray<Type.TObject<{
        scope: Type.TUnion<[Type.TLiteral<"repo">, Type.TLiteral<"user">]>;
        kind: Type.TUnion<[Type.TLiteral<"pi">, Type.TLiteral<"agents">, Type.TLiteral<"claude">]>;
    }>>>;
    nudges: Type.TOptional<Type.TObject<{
        afterCommit: Type.TOptional<Type.TBoolean>;
    }>>;
}>;
export type RuleSource = Type.Static<typeof RULE_SOURCE_SCHEMA>;
export type RuleConfig = Type.Static<typeof RULE_CONFIG_SCHEMA>;
export type RuleConfigPatch = Type.Static<typeof RULE_CONFIG_PATCH_SCHEMA>;
export declare const DEFAULT_RULE_SOURCES: RuleSource[];
interface DiscoveryOptions {
    env?: NodeJS.ProcessEnv;
    home?: string;
    sources?: RuleSource[];
}
export interface RuleConfigResult {
    enabled: boolean;
    sources: RuleSource[];
    nudgeAfterCommit: boolean;
    configPath?: string;
    diagnostic?: RuleDiagnostic;
}
type ParseResult = {
    rule: Rule;
} | {
    diagnostic: RuleDiagnostic;
};
export declare function validateRuleConfigPatch(value: unknown): {
    config: RuleConfigPatch;
} | {
    reason: string;
};
export declare function loadRuleConfig(cwd: string, options?: DiscoveryOptions): Promise<RuleConfigResult>;
export declare function discoverRules(cwd: string, options?: DiscoveryOptions): Promise<DiscoveryResult>;
export declare function parseRuleFile(sourcePath: string, sourceLabel: string): Promise<ParseResult>;
export {};
//# sourceMappingURL=discovery.d.ts.map