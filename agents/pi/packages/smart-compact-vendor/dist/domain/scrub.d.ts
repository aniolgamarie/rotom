export interface RedactionFinding {
    kind: string;
    count: number;
}
export interface ScrubResult<T = string> {
    value: T;
    findings: RedactionFinding[];
}
/** Run-scoped scrubber used at LLM, cache, backup and persistence boundaries. */
export declare class SecretScrubber {
    private readonly secretsEnabled;
    private readonly piiEnabled;
    private total;
    constructor(secretsEnabled?: boolean, piiEnabled?: boolean);
    scrubText(text: string): ScrubResult<string>;
    scrubValue<T>(input: T): ScrubResult<T>;
    count(): number;
}
//# sourceMappingURL=scrub.d.ts.map