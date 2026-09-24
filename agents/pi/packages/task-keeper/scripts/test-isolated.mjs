// 旧验证入口会启动真实 SDK/宿主，不能作为默认 npm test。
if (!process.argv.includes("--allow-host")) {
  process.stderr.write("Native tests require explicit --allow-host authorization.\n");
  process.exit(2);
}
process.argv = process.argv.filter(value => value !== "--allow-host");

import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readlinkSync, readdirSync, cpSync, rmSync, existsSync, renameSync, symlinkSync, realpathSync, statSync } from "node:fs";
import { tmpdir, homedir } from "node:os";
import { dirname, join, relative, resolve, isAbsolute, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Test-only launcher. Never falls back to a process running in the user's home/network.
const pkg = fileURLToPath(new URL("..", import.meta.url));
const root = mkdtempSync(join(tmpdir(), "task-keeper-isolation-"));
const nodeRoot = dirname(dirname(process.execPath));
const nvim = spawnSync("which", ["nvim"], { encoding: "utf8" });
const sourceCopy = join(root, "package");
cpSync(pkg, sourceCopy, { recursive: true, filter: path => !relative(pkg, path).split("/").some(part => ["node_modules", "test-results", "coverage", ".git", ".env"].includes(part)) });
symlinkSync(join(pkg, "node_modules"), join(sourceCopy, "node_modules"));
for (const part of ["home", "config", "cache", "state", "pi", "native", "results", "protected", "work-tests"]) mkdirSync(join(root, part), { mode: 0o700 });
writeFileSync(join(root, "protected", "sentinel"), "unchanged", { mode: 0o600 });
const input = process.argv.slice(2);
function focusedArguments(args) {
  const result = [], valueOptions = new Set(["--test-name-pattern", "--test-skip-pattern", "--test-concurrency", "--test-timeout", "--test-reporter", "--test-reporter-destination", "--test-shard", "--test-coverage-exclude", "--test-coverage-include", "--test-coverage-lines", "--test-coverage-branches", "--test-coverage-functions", "--import", "--require", "-r", "--loader", "--experimental-loader"]);
  const sourceRoot = realpathSync(pkg), targets = []; let value = false, options = true;
  for (const token of args) {
    if (value) { result.push(token); value = false; continue; }
    if (options && token === "--") { options = false; continue; }
    if (options && token.startsWith("-")) { result.push(token); value = valueOptions.has(token); continue; }
    const path = resolve(pkg, token);
    if (!token || !existsSync(path)) throw new Error(`MISSING_TEST_TARGET: ${token}`);
    const canonical = realpathSync(path), local = relative(sourceRoot, canonical);
    if (local === ".." || local.startsWith(`..${sep}`) || isAbsolute(local)) throw new Error(`TEST_TARGET_OUTSIDE_PACKAGE: ${token}`);
    if (local.split(sep).some(part => ["node_modules", "test-results", "coverage", ".git", ".env"].includes(part))) throw new Error(`TEST_TARGET_OUTSIDE_SNAPSHOT: ${token}`);
    if (!statSync(canonical).isFile()) throw new Error(`TEST_TARGET_MUST_BE_FILE: ${token}`);
    targets.push(local);
  }
  if (value) throw new Error("MISSING_TEST_OPTION_VALUE");
  if (!targets.length) targets.push(...readdirSync(join(pkg, "tests")).filter(name => name.endsWith(".test.ts")).sort().map(name => `tests/${name}`));
  // Node stops processing runtime flags at its first file argument. Preserve
  // caller option order while moving every validated target after the flags.
  return [...result, "--", ...targets];
}
let nodeArgs;
try {
if (input[0] === "--report" && input.slice(1).some(arg => arg !== "--release")) throw new Error("UNSUPPORTED_LAUNCH_ARGUMENT");
if (["--typecheck", "--plan"].includes(input[0]) && input.length !== 1) throw new Error("UNSUPPORTED_LAUNCH_ARGUMENT");
if (input[0] === "--report") nodeArgs = ["--experimental-strip-types", "scripts/test-report.ts", ...input.slice(1)];
else if (input[0] === "--typecheck") nodeArgs = ["node_modules/typescript/bin/tsc", "-p", "tsconfig.json"];
else if (input[0] === "--plan") nodeArgs = ["--experimental-strip-types", "scripts/check-plan.ts"];
else {
  const coverage = input[0] === "--coverage"; if (coverage) input.shift();
  nodeArgs = ["--experimental-strip-types", ...(coverage ? ["--experimental-test-coverage"] : []), "--test",
    ...focusedArguments(input)];
}
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  rmSync(root, { recursive: true, force: true }); process.exit(1);
}
const namespaces = Object.fromEntries(["mnt", "net", "pid"].map(key => [key, readlinkSync(`/proc/self/ns/${key}`)]));
writeFileSync(join(root, "launch.json"), JSON.stringify({ root, pkg: sourceCopy, nodeArgs, namespaces, realHome: homedir() }), { mode: 0o600 });
const env = { PATH: `${join(nodeRoot, "bin")}:/usr/bin:/bin`, LANG: "C.UTF-8", TERM: "xterm-256color",
  HOME: join(root, "home"), XDG_CONFIG_HOME: join(root, "config"), XDG_CACHE_HOME: join(root, "cache"), XDG_STATE_HOME: join(root, "state"),
  TMPDIR: "/tmp", PI_CODING_AGENT_DIR: join(root, "pi"), PI_SUBAGENTS_TEMP_ROOT: join(root, "native"),
  PI_MODEL_EXCLUSIONS_PATH: join(root, "native", "exclusions.json"), PI_OFFLINE: "1", PI_TELEMETRY: "0",
  TASK_KEEPER_TEST_REPO_ROOT: resolve(pkg, "../../.."), TASK_KEEPER_TEST_NVIM: nvim.status === 0 ? nvim.stdout.trim() : "",
  TASK_KEEPER_TEST_WORK_ROOT: join(root, "work-tests"), TASK_KEEPER_TEST_RESULT_ROOT: join(root, "results"), TASK_KEEPER_ISOLATED: "1" };
const args = ["--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--die-with-parent", "--new-session",
  "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/run",
  "--tmpfs", "/home", "--ro-bind", nodeRoot, nodeRoot,
  "--bind", root, root, "--ro-bind", join(root, "protected"), join(root, "protected"),
  "--ro-bind", sourceCopy, sourceCopy,
  "--chdir", sourceCopy, process.execPath, join(sourceCopy, "scripts/isolation-child.mjs"), join(root, "launch.json")];
let output = "";
const child = spawn("bwrap", args, { env, stdio: ["ignore", "pipe", "pipe"] });
for (const [stream, sink] of [[child.stdout, process.stdout], [child.stderr, process.stderr]]) stream.on("data", chunk => { output += chunk; sink.write(chunk); });
let interrupted = false;
for (const signal of ["SIGINT", "SIGTERM"]) process.once(signal, () => { interrupted = true; child.kill(signal); });
const code = await new Promise(resolveCode => { child.on("error", error => { output += String(error); console.error(error); resolveCode(1); }); child.on("close", code => resolveCode(code ?? 1)); });
const resultRoot = join(pkg, "test-results"); mkdirSync(resultRoot, { recursive: true, mode: 0o700 });
const auditRoot = join(resultRoot, `isolation-${new Date().toISOString().replace(/[:.]/g, "-")}`); mkdirSync(auditRoot, { mode: 0o700 });
if (code !== 0) cpSync(join(root, "work-tests"), join(auditRoot, "failed-workspaces"), { recursive: true, dereference: false });
cpSync(sourceCopy, join(auditRoot, "source"), { recursive: true, filter: path => relative(sourceCopy, path) !== "node_modules" });
writeFileSync(join(auditRoot, "launcher.log"), output, { mode: 0o600 });
writeFileSync(join(auditRoot, "launch.json"), JSON.stringify({ code, interrupted, nodeArgs, namespaces, root }), { mode: 0o600 });
if (existsSync(join(root, "isolation.json"))) cpSync(join(root, "isolation.json"), join(auditRoot, "isolation.json"));
// Publish only fresh result directories. Previous runs cannot be overwritten inside the sandbox.
for (const entry of readdirSync(join(root, "results"), { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const target = join(resultRoot, entry.name); if (existsSync(target)) throw new Error(`Result collision: ${entry.name}`);
  cpSync(join(root, "results", entry.name), target, { recursive: true });
}
if (existsSync(join(root, "results", "latest.json"))) {
  const temporary = join(resultRoot, `.latest-${process.pid}.json`);
  cpSync(join(root, "results", "latest.json"), temporary); renameSync(temporary, join(resultRoot, "latest.json"));
}
rmSync(root, { recursive: true, force: true });
process.exitCode = code;
