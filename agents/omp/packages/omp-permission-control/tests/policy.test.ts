import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import type { ShellAnalysisContext, ShellAnalysis } from "../shell-analysis";
import type { PolicyAssessment, PolicyInput, RestrictionFacts, RestrictionState } from "../policy";
import type { ModelReview } from "../reviewer";
import { inspectReadCommands } from "../shell-analysis";

let analyzeShell: (commandBytes: Uint8Array, context: ShellAnalysisContext) => ShellAnalysis;
let deriveRestrictionState: (input: RestrictionFacts) => RestrictionState;
let assessBeforeReview: (input: PolicyInput) => PolicyAssessment;
let synthesizeReview: (
  input: PolicyInput,
  review: ModelReview | undefined,
  mechanicalEvidenceVerified: boolean,
) => PolicyAssessment;
let externalCalls = 0;
const originalFetch = globalThis.fetch;
const originalSpawn = Bun.spawn;
const originalSpawnSync = Bun.spawnSync;
const originalWorker = globalThis.Worker;

beforeAll(async () => {
  globalThis.fetch = (() => {
    externalCalls += 1;
    throw new Error("NETWORK_DISABLED");
  }) as unknown as typeof fetch;
  Bun.spawn = ((..._args: Parameters<typeof Bun.spawn>) => {
    externalCalls += 1;
    throw new Error("PROCESS_DISABLED");
  }) as unknown as typeof Bun.spawn;
  Bun.spawnSync = ((..._args: Parameters<typeof Bun.spawnSync>) => {
    externalCalls += 1;
    throw new Error("PROCESS_DISABLED");
  }) as unknown as typeof Bun.spawnSync;
  globalThis.Worker = class DisabledWorker {
    constructor() {
      externalCalls += 1;
      throw new Error("WORKER_DISABLED");
    }
  } as unknown as typeof Worker;
  ({ analyzeShell } = await import("../shell-analysis"));
  ({ deriveRestrictionState, assessBeforeReview, synthesizeReview } = await import("../policy"));
});

afterAll(() => {
  globalThis.fetch = originalFetch;
  Bun.spawn = originalSpawn;
  Bun.spawnSync = originalSpawnSync;
  globalThis.Worker = originalWorker;
  expect(externalCalls).toBe(0);
});

const digest = "a".repeat(64);
function context(targets = ["cwd", "docs", "README.md", "out.txt"]): ShellAnalysisContext {
  return {
    cwd: { path: "/repo", category: "repo-root", fingerprint: digest, verified: true },
    shellState: {
      fingerprint: digest,
      verified: true,
      trapsDisabled: true,
      optionsSafe: true,
      implicitCommandsAbsent: true,
    },
    executables: Object.fromEntries(
      ["pwd", "ls", "head", "wc", "rg", "git"].map((name) => [
        name,
        {
          argv0: name,
          resolvedPath: name === "pwd" ? "builtin:pwd" : `/usr/bin/${name}`,
          identityDigest: digest,
          resolutionFingerprint: digest,
          source: name === "pwd" ? "builtin" : "system",
          noRelevantShadowing: true,
          verified: true,
        },
      ]),
    ),
    targets: Object.fromEntries(
      targets.map((target) => [
        target,
        {
          input: target,
          canonical: target === "cwd" ? "/repo" : `/repo/${target}`,
          fingerprint: digest,
          category: target === "cwd" ? "cwd" : "repo-path",
          targetType: target === "cwd" ? "cwd" : target === "docs" ? "directory" : "file",
          normalized: true,
          nonSecret: true,
          nonDevice: true,
          verified: true,
          recursiveReadVerified: target === "cwd" || target === "docs",
          recursiveReadScopeFingerprint: target === "cwd" || target === "docs" ? digest : undefined,
        },
      ]),
    ),
    git: {
      repoRoot: "/repo",
      fingerprint: digest,
      verified: true,
      pagerDisabled: true,
      externalDiffDisabled: true,
      textconvDisabled: true,
      optionalLocksDisabled: true,
      fsmonitorDisabled: true,
      hooksDisabled: true,
      configOverridesDisabled: true,
      configIncludesDisabled: true,
      aliasesDisabled: true,
      repositoryReadScopeVerified: true,
      repositoryReadScopeFingerprint: digest,
    },
  };
}
const bytes = (value: string) => new TextEncoder().encode(value);

test("host proof collection uses the same bounded parser and cannot grant approval", () => {
  const parsed = inspectReadCommands("ls -R docs | head -n 2 README.md < extra.txt && pwd");
  expect(parsed?.map(command => command.targets)).toEqual([["docs"], ["README.md", "extra.txt"], ["cwd"]]);
  expect(parsed?.map(command => command.recursive)).toEqual([true, false, false]);
  expect(Object.isFrozen(parsed?.[0].argv)).toBe(true);
  expect(parsed?.map(command => command.hasInputRedirection)).toEqual([false, true, false]);
  expect(inspectReadCommands("ls > out.txt")).toBeUndefined();
  expect(inspectReadCommands("rg --pre custom pattern docs")).toBeUndefined();
});

describe("conservative shell analysis", () => {
  test("parses literal quoting, escaping, comments, and compound connectors", () => {
    const result = analyzeShell(
      bytes("ls -1 'docs' && head -n 2 README\\.md # ignored"),
      context(["docs", "README.md"]),
    );
    expect(result.status).toBe("complete");
    expect(result.commands.map((command) => command.connector)).toEqual(["start", "&&"]);
    expect(result.commands.map((command) => command.argv)).toEqual([
      ["ls", "-1", "docs"],
      ["head", "-n", "2", "README.md"],
    ]);
    expect(result.effects).toHaveLength(2);
    expect(result.effects.every((effect) => effect.kind === "read" && effect.risk === "low")).toBe(
      true,
    );
  });

  test("collects every pipeline and sequence effect; connector alone does not change risk", () => {
    const result = analyzeShell(
      bytes("rg --fixed-strings permission docs | head -n 3 README.md; pwd || wc -l README.md"),
      context(),
    );
    expect(result.status).toBe("complete");
    expect(result.commands.map((command) => command.connector)).toEqual(["start", "|", ";", "||"]);
    expect(result.effects.map((effect) => effect.effectId)).toEqual([
      "effect-1",
      "effect-2",
      "effect-3",
      "effect-4",
    ]);
    expect(result.effects.every((effect) => effect.risk === "low")).toBe(true);
  });

  test("preserves empty words and Bash double-quote backslashes", () => {
    const empty = analyzeShell(bytes("rg --fixed-strings '' README.md"), context(["README.md"]));
    expect(empty.status).toBe("complete");
    expect(empty.commands[0]?.argv).toEqual(["rg", "--fixed-strings", "", "README.md"]);

    const quotedBackslash = analyzeShell(bytes('ls "docs\\q"'), context(["docs\\q"]));
    expect(quotedBackslash.status).toBe("complete");
    expect(quotedBackslash.commands[0]?.argv).toEqual(["ls", "docs\\q"]);
  });

  test("uses only Bash ASCII separators and rejects unquoted tilde expansion", () => {
    const nbspTarget = "docs\u00a0name";
    const literal = analyzeShell(bytes(`ls ${nbspTarget}`), context([nbspTarget]));
    expect(literal.status).toBe("complete");
    expect(literal.commands[0]?.argv).toEqual(["ls", nbspTarget]);

    expect(analyzeShell(bytes("ls ~/docs"), context(["~/docs"])).status).toBe("unknown");
    expect(analyzeShell(bytes("ls '~'"), context(["~"])).status).toBe("complete");
    expect(analyzeShell(bytes("ls \\~"), context(["~"])).status).toBe("complete");
  });

  test("associates pipeline stdin reads with the upstream command", () => {
    const result = analyzeShell(
      bytes("rg --fixed-strings permission docs | head -n 2 | wc -l"),
      context(),
    );
    expect(result.status).toBe("complete");
    expect(result.effects).toHaveLength(3);
    expect(result.effects[1]).toMatchObject({
      kind: "read",
      target: "pipe:command-1",
      parameters: ["head", "-n", "2"],
    });
    expect(result.effects[2]).toMatchObject({
      kind: "read",
      target: "pipe:command-2",
      parameters: ["wc", "-l"],
    });
    const byteCount = analyzeShell(bytes("head -n 2 README.md | wc -c"), context());
    expect(byteCount.effects[1]?.parameters).toEqual(["wc", "-c"]);
    expect(byteCount.effects[1]?.parameters).not.toEqual(result.effects[2]?.parameters);

    const rgStdin = analyzeShell(
      bytes("head -n 2 README.md | rg --fixed-strings permission"),
      context(),
    );
    expect(rgStdin.status).toBe("complete");
    expect(rgStdin.effects[1]).toMatchObject({ target: "pipe:command-1" });
    expect(analyzeShell(bytes("head -n 2"), context()).status).toBe("unknown");
    expect(analyzeShell(bytes("wc -l"), context()).status).toBe("unknown");
  });

  test("verified git status, diff, and log argv remain bounded reads", () => {
    const result = analyzeShell(
      bytes(
        "git status --porcelain=v2 --branch && git diff --name-only -- docs; git log --graph --decorate -n 4 --oneline",
      ),
      context(),
    );
    expect(result.status).toBe("complete");
    expect(result.effects).toHaveLength(3);
    expect(result.effects.every((effect) => effect.kind === "read" && effect.risk === "low")).toBe(
      true,
    );
  });

  test("literal input redirection supplies a verified read target", () => {
    const result = analyzeShell(bytes("wc -l < README.md"), context());
    expect(result.status).toBe("complete");
    expect(result.effects.map((effect) => [effect.kind, effect.target, effect.risk])).toEqual([
      ["read", "/repo/README.md", "low"],
    ]);
  });

  test("literal output redirection is a separate write effect", () => {
    const result = analyzeShell(bytes("head -n 2 README.md > out.txt"), context());
    expect(result.status).toBe("complete");
    expect(result.effects.map((effect) => [effect.kind, effect.target, effect.risk])).toEqual([
      ["read", "/repo/README.md", "low"],
      ["write", "/repo/out.txt", "medium"],
    ]);
  });

  test("fails closed when file-descriptor adjacency cannot be proven", () => {
    const result = analyzeShell(bytes("head -n 2 README.md 2> out.txt"), context());
    expect(result.status).toBe("unknown");
    expect(result.unknowns).toContain("unsupported-syntax");
  });

  test.each([
    "printf '%s' \"$HOME\"",
    "echo $(pwd)",
    "cat <(pwd)",
    "ls *.md",
    "cat <<EOF",
    "sleep 1 &",
    "f() { pwd; }",
    "if true; then pwd; fi",
    "for x in a; do echo $x; done",
    "bash scripts/check.sh",
  ])("marks dynamic or script syntax unknown without executing: %s", (command) => {
    const result = analyzeShell(bytes(command), context());
    expect(result.status).toBe("unknown");
    expect(
      result.effects.some((effect) => effect.kind === "unknown" && effect.risk === "unknown"),
    ).toBe(true);
  });

  test("does not trust a whitelist prefix without executable evidence", () => {
    const ctx = context();
    delete ctx.executables.ls;
    const result = analyzeShell(bytes("ls docs"), ctx);
    expect(result.status).toBe("unknown");
    expect(result.unknowns).toContain("unresolved-executable");
  });

  test("requires per-command no-shadowing and verified shell state", () => {
    const shadowed = context();
    shadowed.executables.ls!.noRelevantShadowing = false;
    expect(analyzeShell(bytes("ls docs"), shadowed).unknowns).toContain("unresolved-executable");
    const trapped = context();
    trapped.shellState.trapsDisabled = false;
    expect(analyzeShell(bytes("ls docs"), trapped).unknowns).toContain(
      "shell-state-not-verifiable",
    );
  });

  test("requires normalized non-secret non-device target evidence", () => {
    const ctx = context(["README.md"]);
    ctx.targets["README.md"]!.nonSecret = false;
    const result = analyzeShell(bytes("head -n 2 README.md"), ctx);
    expect(result.status).toBe("unknown");
    expect(result.unknowns).toContain("unsafe-target");
  });

  test("requires every git execution and configuration proof", () => {
    const ctx = context(["docs"]);
    ctx.git!.hooksDisabled = false;
    const result = analyzeShell(bytes("git diff --stat -- docs"), ctx);
    expect(result.status).toBe("unknown");
    expect(result.unknowns).toContain("git-state-not-verifiable");

    const scope = context(["docs"]);
    scope.git!.repositoryReadScopeVerified = false;
    expect(analyzeShell(bytes("git diff --stat -- docs"), scope).status).toBe("unknown");
  });

  test("rejects digest evidence with a trailing newline", () => {
    const executable = context();
    executable.executables.ls!.identityDigest = `${digest}\n`;
    expect(analyzeShell(bytes("ls docs"), executable).status).toBe("unknown");

    const target = context();
    target.targets.docs!.fingerprint = `${digest}\n`;
    expect(analyzeShell(bytes("ls docs"), target).status).toBe("unknown");

    const git = context();
    git.git!.fingerprint = `${digest}\n`;
    expect(analyzeShell(bytes("git status --short"), git).status).toBe("unknown");
  });

  test("does not infer recursive tree safety from an ordinary directory target proof", () => {
    expect(analyzeShell(bytes("ls -R docs"), context()).status).toBe("complete");
    expect(analyzeShell(bytes("rg permission docs"), context()).status).toBe("complete");

    const ls = context();
    ls.targets.docs!.recursiveReadVerified = false;
    delete ls.targets.docs!.recursiveReadScopeFingerprint;
    expect(analyzeShell(bytes("ls docs"), ls).status).toBe("complete");
    expect(analyzeShell(bytes("ls -R docs"), ls).status).toBe("unknown");

    const rg = context();
    rg.targets.docs!.recursiveReadVerified = false;
    delete rg.targets.docs!.recursiveReadScopeFingerprint;
    expect(analyzeShell(bytes("rg permission docs"), rg).status).toBe("unknown");
  });

  test.each([
    "ls --help docs",
    "head --zero-terminated README.md",
    "wc --files0-from=list",
    "rg --pre cat x docs",
    "git diff --ext-diff",
    "git log --format=%x00",
    "git status --ignored=matching",
    "unknown docs",
  ])("rejects unsupported argv instead of allowing by first word: %s", (command) => {
    const result = analyzeShell(bytes(command), context());
    expect(result.status).toBe("unknown");
    expect(result.effects.some((effect) => effect.risk === "unknown")).toBe(true);
  });

  test("invalid UTF-8, control bytes, and a BOM fail closed", () => {
    expect(analyzeShell(new Uint8Array([0xff]), context()).status).toBe("unknown");
    expect(analyzeShell(bytes("pwd\0ls"), context()).status).toBe("unknown");
    expect(analyzeShell(bytes("pwd\x01"), context()).status).toBe("unknown");
    expect(
      analyzeShell(Uint8Array.from([0xef, 0xbb, 0xbf, 0x70, 0x77, 0x64]), context()).status,
    ).toBe("unknown");
  });
});

const restrictionFacts = (overrides: Partial<RestrictionFacts> = {}): RestrictionFacts => ({
  generation: 4,
  currentGeneration: 4,
  contextComplete: true,
  uninterpretedUserText: false,
  structuredRestrictions: [],
  ...overrides,
});

const readEffect = (effectId = "effect-1") => ({
  effectId,
  kind: "read" as const,
  target: "/repo/README.md",
  parameters: ["head", "-n", "2", "README.md"],
  cwdCategory: "repo-root" as const,
  risk: "low" as const,
});

const policyInput = (overrides: Partial<PolicyInput> = {}): PolicyInput => ({
  mode: "smart",
  effects: [readEffect()],
  analysisComplete: true,
  nativeConstraints: [{ source: "native-allow", policy: "allow" }],
  restrictionFacts: restrictionFacts(),
  hardProhibited: false,
  mechanical: {
    coverageVerified: true,
    healthVerified: true,
    contextComplete: true,
    redactionComplete: true,
    targetProofVerified: true,
    generationVerified: true,
  },
  ...overrides,
});

const modelReview = (overrides: Partial<ModelReview> = {}): ModelReview => ({
  decision: "allow",
  risk: "low",
  authorization: "sufficient",
  effects: ["effect-1"],
  unknowns: [],
  reasonCode: "LOW_RISK_AUTHORIZED",
  evidence: {
    userMessageIds: ["msg-1"],
    bindings: [
      {
        effectId: "effect-1",
        userMessageId: "msg-1",
        startByte: 0,
        endByte: 4,
        scopeDigest: digest,
      },
    ],
  },
  ...overrides,
});

describe("fixed permission policy", () => {
  test("derives restriction state without trusting a caller-supplied state", () => {
    expect(deriveRestrictionState(restrictionFacts())).toBe("clear");
    expect(deriveRestrictionState(restrictionFacts({ uninterpretedUserText: true }))).toBe(
      "unknown",
    );
    expect(deriveRestrictionState(restrictionFacts({ contextComplete: false }))).toBe("unknown");
    expect(
      deriveRestrictionState(
        restrictionFacts({
          structuredRestrictions: [{ verified: true, result: "conflicting" }],
        }),
      ),
    ).toBe("conflicting");
    expect(
      deriveRestrictionState(
        restrictionFacts({
          generation: 3,
          structuredRestrictions: [{ verified: true, result: "conflicting" }],
        }),
      ),
    ).toBe("unknown");
    expect(
      deriveRestrictionState(
        restrictionFacts({
          structuredRestrictions: [{ verified: false, result: "satisfied" }],
        }),
      ),
    ).toBe("unknown");
  });

  test("hard deny wins before native and human boundaries", () => {
    const result = assessBeforeReview(
      policyInput({
        hardProhibited: true,
        nativeConstraints: [{ source: "command-prompt", policy: "prompt" }],
      }),
    );
    expect(result).toMatchObject({
      outcome: "deny",
      source: "hard-rule",
      reason_code: "PROHIBITED_EFFECT",
      modelCallsAllowed: false,
    });
  });

  test.each([
    { source: "explicit-deny" as const, policy: "deny" as const, outcome: "deny" },
    { source: "command-prompt" as const, policy: "prompt" as const, outcome: "ask" },
    { source: "critical-safety" as const, policy: "allow" as const, outcome: "ask" },
    { source: "unknown" as const, policy: "allow" as const, outcome: "ask" },
  ])("preserves native protection: $source", ({ source, policy, outcome }) => {
    expect(
      assessBeforeReview(policyInput({ nativeConstraints: [{ source, policy }] })),
    ).toMatchObject({ outcome, modelCallsAllowed: false });
  });

  test("known structured conflicts never reach the reviewer", () => {
    const result = assessBeforeReview(
      policyInput({
        restrictionFacts: restrictionFacts({
          structuredRestrictions: [{ verified: true, result: "conflicting" }],
        }),
      }),
    );
    expect(result).toMatchObject({
      outcome: "ask",
      source: "native-protection",
      modelCallsAllowed: false,
      restrictionState: "conflicting",
    });
  });

  test.each(["write", "delete", "network-send", "secret-access", "device-access"] as const)(
    "applies the fixed risk floor to %s",
    (kind) => {
      const result = assessBeforeReview(
        policyInput({ effects: [{ ...readEffect(), kind, risk: "low" }] }),
      );
      expect(result).toMatchObject({
        outcome: "ask",
        source: "native-protection",
        reason_code: "USER_CONFIRMATION_REQUIRED",
        modelCallsAllowed: false,
      });
    },
  );

  test("unknown non-read effects ask without a model", () => {
    const result = assessBeforeReview(
      policyInput({ effects: [{ ...readEffect(), kind: "unknown", risk: "unknown" }] }),
    );
    expect(result).toMatchObject({
      outcome: "ask",
      reason_code: "UNKNOWN_EFFECT",
      modelCallsAllowed: false,
    });
  });

  test("incomplete analysis, empty effects, and failed mechanical gates cannot allow", () => {
    expect(assessBeforeReview(policyInput({ analysisComplete: false }))).toMatchObject({
      outcome: "ask",
      modelCallsAllowed: false,
    });
    expect(assessBeforeReview(policyInput({ effects: [] }))).toMatchObject({
      outcome: "ask",
      modelCallsAllowed: false,
    });
    const mechanical = policyInput().mechanical;
    for (const key of Object.keys(mechanical) as (keyof typeof mechanical)[]) {
      expect(
        assessBeforeReview(policyInput({ mechanical: { ...mechanical, [key]: false } })),
      ).toMatchObject({ outcome: "ask", modelCallsAllowed: false });
    }
  });

  test("only clear complete deterministic reads bypass review", () => {
    expect(assessBeforeReview(policyInput())).toMatchObject({
      outcome: "allow",
      source: "low-risk-rule",
      reason_code: "DETERMINISTIC_LOW_RISK",
      modelCallsAllowed: false,
    });
    const unknown = policyInput({
      restrictionFacts: restrictionFacts({ uninterpretedUserText: true }),
    });
    expect(assessBeforeReview(unknown)).toMatchObject({
      outcome: "review",
      source: "reviewer",
      modelCallsAllowed: true,
    });
    expect(assessBeforeReview({ ...unknown, mode: "manual" })).toMatchObject({
      outcome: "ask",
      source: "manual-boundary",
      modelCallsAllowed: false,
    });
  });

  test("preserves valid reviewer deny and ask outcomes", () => {
    const input = policyInput({
      restrictionFacts: restrictionFacts({ uninterpretedUserText: true }),
    });
    expect(
      synthesizeReview(
        input,
        modelReview({ decision: "deny", reasonCode: "AUTHORIZATION_CONFLICTING" }),
        true,
      ),
    ).toMatchObject({
      outcome: "deny",
      source: "reviewer",
      reason_code: "AUTHORIZATION_CONFLICTING",
    });
    expect(
      synthesizeReview(
        input,
        modelReview({ decision: "ask", reasonCode: "AUTHORIZATION_INSUFFICIENT" }),
        true,
      ),
    ).toMatchObject({
      outcome: "ask",
      source: "reviewer",
      reason_code: "AUTHORIZATION_INSUFFICIENT",
    });
  });

  test("allows only a mechanically verified fully bound low-risk model review", () => {
    const input = policyInput({
      restrictionFacts: restrictionFacts({ uninterpretedUserText: true }),
    });
    expect(synthesizeReview(input, modelReview(), true)).toMatchObject({
      outcome: "allow",
      source: "reviewer",
      reason_code: "LOW_RISK_AUTHORIZED",
      restrictionState: "unknown",
      modelCallsAllowed: false,
    });
    expect(synthesizeReview(input, modelReview(), false)).toMatchObject({
      outcome: "ask",
      reason_code: "POLICY_MISMATCH",
    });
    expect(synthesizeReview(input, modelReview({ effects: [] }), true)).toMatchObject({
      outcome: "ask",
      reason_code: "POLICY_MISMATCH",
    });
    expect(
      synthesizeReview(
        input,
        modelReview({ evidence: { userMessageIds: [], bindings: [] } }),
        true,
      ),
    ).toMatchObject({ outcome: "ask", reason_code: "POLICY_MISMATCH" });
  });

  test("reapplies fixed floors and never caches a reviewer allow as clear", () => {
    const unknown = policyInput({
      restrictionFacts: restrictionFacts({ uninterpretedUserText: true }),
    });
    expect(synthesizeReview(unknown, modelReview(), true).outcome).toBe("allow");
    expect(assessBeforeReview(unknown)).toMatchObject({
      outcome: "review",
      restrictionState: "unknown",
    });

    const write = policyInput({
      restrictionFacts: restrictionFacts({ uninterpretedUserText: true }),
      effects: [{ ...readEffect(), kind: "write", risk: "low" }],
    });
    expect(synthesizeReview(write, modelReview(), true)).toMatchObject({
      outcome: "ask",
      source: "native-protection",
      modelCallsAllowed: false,
    });
  });
});
test.each(["tool-default", "tier-default", "compound-structural"] as const)(
  "native %s prompt delegates to the smart reviewer", (source) => {
    const input = policyInput({ nativeConstraints: [{ source, policy: "prompt" }] });
    input.restrictionFacts.uninterpretedUserText = true;
    expect(assessBeforeReview(input).outcome).toBe("review");
  },
);
import { inspectReadCommandNames } from "../shell-analysis";

test("shell continuity uses the same full compound parser without claiming target safety", () => {
  expect(inspectReadCommandNames("pwd && ls . | head -n 2; wc -l README.md")).toEqual(["pwd", "ls", "head", "wc"]);
  for (const text of ["ls\nalias pwd=rm", "ls\u00a0foo", "pwd && eval x", "rg --pre=evil x .", "ls > output", "pwd\n", "constructor", "__proto__"]) {
    expect(inspectReadCommandNames(text)).toBeUndefined();
  }
});
