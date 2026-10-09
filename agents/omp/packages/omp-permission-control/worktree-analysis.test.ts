import { expect, test } from "bun:test";
import { resolve } from "node:path";
import { analyzeWorktree, type WorktreeHelpers } from "./worktree-analysis";

// 合成 helper 输出不实现上游 lexer；官方 helper 的等价性另以固定公开源码直接核验。
const raw = "git worktree add ../rotom-cli-ux -b cli-ux-help && cd ../rotom-cli-ux && git log --oneline -1";
const command = "/fixture/omp worktree add -b cli-ux-help -- ../rotom-cli-ux && cd ../rotom-cli-ux && git log --oneline -1";
const helpers: WorktreeHelpers = {
  resolveCliEntryCmd: () => ["/fixture/omp"],
  extractLeadingCdTarget: value => value.startsWith("cd ../source && ") ? { path: "../source", rest: value.slice(16) } : null,
  resolveToCwd: (path, cwd) => resolve(cwd, path),
  rewriteGitWorktreeAdd: value => value === raw ? command : value,
};

test("supported screenshot plan preserves complete execution effects", () => {
  const result = analyzeWorktree(raw, undefined, "/fixture/work", true, "auto", helpers);
  expect(result.supported).toBe(true);
  expect(result.plan).toMatchObject({ rawCommand: raw, normalizedCommand: raw, executionCommand: command,
    cliArgv: ["/fixture/omp"], effectiveCwd: "/fixture/work", backend: "auto",
    operations: [{ target: "../rotom-cli-ux", branch: "cli-ux-help", forceBranch: false,
      repositoryCwd: "/fixture/work", startPoint: null, pathsAreLexical: true }] });
  expect(result.plan!.effects).toHaveLength(6);
  expect(result.plan).toMatchObject({ backendScope: "native-session-intent",
    executionSettingsScope: "new-cli-repository-cwd-unverified", analysisScope: "native-dispatch-and-declared-possible-effects" });
  expect((result.plan!.effects as string[]).join(" ")).toContain("Post-checkout hooks may execute local code");
});
test("leading cd uses helper normalization and its effective cwd", () => {
  const result = analyzeWorktree("cd ../source && " + raw, undefined, "/fixture/work", true, "rcopy", helpers);
  expect(result.supported).toBe(true);
  expect(result.plan).toMatchObject({ normalizedCommand: raw, effectiveCwd: "/fixture/source", backend: "rcopy" });
});
test("literal data, path git, and unrewritten pipeline have no clone plan", () => {
  for (const value of ["echo 'git worktree add target'", "/usr/bin/git worktree add target", "git worktree add target | cat"]) {
    const result = analyzeWorktree(value, undefined, "/fixture/work", true, "auto", helpers);
    expect(result.supported).toBe(true);
    expect(result.plan).toBeUndefined();
  }
});
test("missing or invalid public rewrite helpers fail closed", () => {
  expect(analyzeWorktree(raw, undefined, "/fixture/work", true, "auto").supported).toBe(false);
  expect(analyzeWorktree(raw, undefined, "/fixture/work", true, "auto", { ...helpers,
    rewriteGitWorktreeAdd: () => "unexplained target" }).supported).toBe(false);
});
test("Git -C, -B, start point and multiple segments retain lexical segment context", () => {
  const input = "git -C ../repo worktree add -B reset ../one HEAD && git worktree add -b two ../two";
  const execution = "/fixture/omp worktree add -C ../repo -B reset -- ../one HEAD && /fixture/omp worktree add -b two -- ../two";
  const result = analyzeWorktree(input, undefined, "/fixture/work", true, "reflink", {
    ...helpers, rewriteGitWorktreeAdd: () => execution });
  expect(result.supported).toBe(true);
  expect(result.plan!.operations).toMatchObject([{ repositoryArgument: "../repo", repositoryCwd: "/fixture/repo",
    segmentCwd: "/fixture/work", target: "../one", branch: "reset", forceBranch: true, startPoint: "HEAD" },
    { segmentCwd: "/fixture/work", target: "../two", branch: "two" }]);
});

test("conditional internal navigation before a later clone remains unsupported", () => {
  const input = "false && cd a && git worktree add ../b; git worktree add ../c";
  const output = "false && cd a && /fixture/omp worktree add -- ../b; /fixture/omp worktree add -- ../c";
  expect(analyzeWorktree(input, undefined, "/fixture/work", true, "auto", {
    ...helpers, rewriteGitWorktreeAdd: () => output }).supported).toBe(false);
});
test("unchanged redirect segments remain in the raw reviewed command", () => {
  const input = "git worktree add ../target && git log --oneline -1 2>/dev/null";
  const output = "/fixture/omp worktree add -- ../target && git log --oneline -1 2>/dev/null";
  const result = analyzeWorktree(input, undefined, "/fixture/work", true, "auto", {
    ...helpers, rewriteGitWorktreeAdd: () => output });
  expect(result.supported).toBe(true);
  expect(result.plan!.rawCommand).toBe(input);
});

test("unverified actual/helper-unavailable rewrite effects survive unsupported analysis", () => {
  const command = "echo ok && cd sub && git worktree add ../x";
  const result = analyzeWorktree(command, undefined, "/fixture/work", true, "auto", {
    ...helpers, rewriteGitWorktreeAdd: () => "echo ok && cd sub && /fixture/omp worktree add -- ../x" });
  expect(result.supported).toBe(false); expect(result.plan).toBeUndefined();
  expect(result.unverified).toMatchObject({ mayRewrite: true, verified: false, rewriteEvidence: "changed" });
  expect(analyzeWorktree(raw, undefined, "/fixture/work", true, "auto").unverified)
    .toMatchObject({ mayRewrite: true, rewriteEvidence: "helper-unavailable" });
});
test("ordinary HOME navigation and no-rewrite cases gain no clone gate or warning", () => {
  for (const command of ["cd ~/bin", "echo 'git worktree add fake'", "git worktree add target | cat"]) {
    const result = analyzeWorktree(command, undefined, "/fixture/work", true, "auto", helpers);
    expect(result.supported).toBe(true); expect(result.plan).toBeUndefined(); expect(result.unverified).toBeUndefined();
  }
});
test("HOME navigation after the final clone leaves the dispatch plan supported", () => {
  const command = "git worktree add ../x && cd ~/bin";
  const result = analyzeWorktree(command, undefined, "/fixture/work", true, "auto", {
    ...helpers, rewriteGitWorktreeAdd: () => "/fixture/omp worktree add -- ../x && cd ~/bin" });
  expect(result.supported).toBe(true); expect(result.plan).toBeDefined(); expect(result.unverified).toBeUndefined();
});

test("exact git prefix avoids argument false positives; proven no rewrite adds no clone gate", () => {
  for (const command of ["git grep worktree add", "git log --grep worktree add", "git worktree add --unknown target",
    "git worktree add 'target$literal'", "echo $NAME"]) {
    const result = analyzeWorktree(command, undefined, "/fixture/work", true, "auto", helpers);
    expect(result.supported).toBe(true); expect(result.plan).toBeUndefined(); expect(result.unverified).toBeUndefined();
  }
});

test("source/missing CLI resolver preserves ordinary dynamic policy but exposes late clone uncertainty", () => {
  for (const failure of ["source", "missing"]) {
    const unavailable: WorktreeHelpers = { ...helpers,
      resolveCliEntry: () => { throw new Error(failure); },
      rewriteGitWorktreeAdd: value => value.endsWith(" && git worktree add ../late")
        ? "unverified-probe-changed" : value };
    const ordinary = analyzeWorktree("echo $NAME", undefined, "/fixture/work", true, "auto", unavailable);
    expect(ordinary.supported).toBe(true); expect(ordinary.plan).toBeUndefined();
    expect(ordinary.unverified).toBeUndefined(); expect(ordinary.rewriteApplied).toBe(false);
    const command = "echo $NAME && git worktree add ../late";
    const late = analyzeWorktree(command, undefined, "/fixture/work", true, "auto", unavailable);
    expect(late.supported).toBe(false); expect(late.plan).toBeUndefined();
    expect(late.unverified).toMatchObject({ mayRewrite: true, verified: false });
    expect(late.executionCommand).toBe(command); expect(late.cliArgv).toEqual([]);
  }
});
