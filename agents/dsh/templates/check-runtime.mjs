// 只校验公开模块身份，不挂载宿主、WebUI 或 working-activity，不调用模型。
import { readFileSync, realpathSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

const root = process.argv[2];
if (!root || !path.isAbsolute(root)) throw new Error("runtime path must be absolute");
const require = createRequire(path.join(root, "package.json"));
const expected = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8")).dependencies;
const manifest = (resolve, name) => JSON.parse(readFileSync(resolve.resolve(`${name}/package.json`), "utf8"));
const fail = () => { throw new Error("managed runtime package versions or module identities differ"); };
for (const [name, version] of Object.entries(expected)) {
  const actual = manifest(require, name);
  const localVersion = { "rotom-dsh-cursor-terminal": "0.1.3", "rotom-dsh-review-context": "0.2.0",
    "rotom-dsh-execution-environment": "0.1.1", "rotom-dsh-ssh-shell-env": "0.1.0",
    "rotom-dsh-ssh-subscription-auth": "0.1.1" }[name];
  if (actual.name !== name || actual.version !== (localVersion ?? version)) fail();
}
if (manifest(require, "@deepseek-ai/cordis").version !== "4.0.5"
    || manifest(require, "@deepseek-ai/schemastery").version !== "3.18.5"
    || manifest(require, "@deepseek-harness-tui/dsh-tui").version !== "0.16.1") fail();
const tui = createRequire(require.resolve("@deepseek-harness-tui/dsh-tui/package.json"));
const thin = createRequire(require.resolve("rotom-dsh-cursor-terminal"));
const cursor = createRequire(thin.resolve("dsh-cursor-subscription"));
const perry = createRequire(require.resolve("dsh-auto-review"));
const reviewContext = createRequire(require.resolve("rotom-dsh-review-context"));
const execution = createRequire(require.resolve("rotom-dsh-execution-environment"));
if (realpathSync(execution.resolve("@deepseek-ai/dsh-subprocess-local"))
    !== realpathSync(require.resolve("@deepseek-ai/dsh-subprocess-local"))) fail();
if (manifest(cursor, "dsh-cursor-subscription").version !== "0.6.12") fail();
for (const resolve of [tui, thin, cursor, perry, reviewContext]) {
  for (const name of ["@deepseek-ai/dsh-llm", "@deepseek-ai/dsh-credentials", "@deepseek-ai/cordis"]) {
    if (realpathSync(resolve.resolve(name)) !== realpathSync(require.resolve(name))) fail();
  }
}
for (const resolve of [tui, thin, perry, reviewContext]) {
  if (realpathSync(resolve.resolve("@deepseek-ai/schemastery")) !== realpathSync(require.resolve("@deepseek-ai/schemastery"))) fail();
}
// Cursor 的直接 Schema 依赖仅构造配置，不实例化审批/会话服务；它可单独解析稳定版。
if (!["3.18.5"].includes(manifest(cursor, "@deepseek-ai/schemastery").version)) fail();
for (const name of ["dsh-agent", "dsh-session", "dsh-subagent", "dsh-tools", "dsh-user-approval", "dsh-brand"]) {
  const packageName = "@deepseek-ai/" + name;
  if (manifest(perry, packageName).version !== "0.2.1-rc.2"
      || realpathSync(perry.resolve(packageName)) !== realpathSync(require.resolve(packageName))) fail();
}
if (manifest(tui, "react").version.split(".")[0] !== "19"
    || realpathSync(tui.resolve("react")) !== realpathSync(require.resolve("react"))) fail();
const { LlmAdapter } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-llm")));
const { CursorAdapter } = await import(pathToFileURL(cursor.resolve("dsh-cursor-subscription")));
const { TerminalCursorAdapter } = await import(pathToFileURL(require.resolve("rotom-dsh-cursor-terminal")));
const review = await import(pathToFileURL(require.resolve("dsh-auto-review")));
if (manifest(perry, "dsh-auto-review").version !== "0.13.7" || typeof review.apply !== "function") fail();
const reviewerRestriction = await import(pathToFileURL(require.resolve("rotom-dsh-review-context/reviewer")));
if (typeof reviewerRestriction.apply !== "function") fail();
for (const name of ["dsh-agent-preset", "dsh-agent-tool-presentation", "dsh-tools"]) {
  const packageName = "@deepseek-ai/" + name;
  if (manifest(reviewContext, packageName).version !== "0.2.1-rc.2"
      || realpathSync(reviewContext.resolve(packageName)) !== realpathSync(require.resolve(packageName))) fail();
}
// 原生 preset 的文件搜索/jobs 和 spill 路径也必须能导入，不能只验证顶层 SDK。
for (const name of ["dsh-command-feedback", "dsh-spill-local", "dsh-spill-policy", "dsh-tool-fs-search", "dsh-tool-jobs"]) {
  await import(pathToFileURL(require.resolve("@deepseek-ai/" + name)));
}
for (const name of ["dsh-tmux-context", "dsh-experimental-worktree", "dsh-experimental-tool-worktree",
  "dsh-headless", "dsh-ssh", "dsh-fs-ssh", "dsh-subprocess-ssh", "dsh-sandbox-ssh"]) {
  await import(pathToFileURL(require.resolve("@deepseek-ai/" + name)));
}
// Teams 只验证公开入口和共享服务身份；这里不挂载插件或启动成员。
for (const [name, services] of [
  ["dsh-experimental-agent-team-profile", ["cordis", "dsh-experimental-agent-team", "dsh-experimental-tool-agent-team", "dsh-experimental-client-ui-agent-team"]],
  ["dsh-experimental-agent-team", ["cordis", "schemastery", "dsh-agent", "dsh-session", "dsh-subagent", "dsh-llm", "dsh-brand", "dsh-session-projection", "dsh-session-persistence"]],
  ["dsh-experimental-tool-agent-team", ["cordis", "schemastery", "dsh-agent", "dsh-tools", "dsh-session", "dsh-system-prompt", "dsh-experimental-agent-team"]],
  ["dsh-experimental-client-ui-agent-team", ["cordis"]],
]) {
  const packageName = "@deepseek-ai/" + name;
  if (manifest(require, packageName).version !== "0.2.1-rc.2") fail();
  await import(pathToFileURL(require.resolve(packageName)));
  const team = createRequire(require.resolve(packageName));
  for (const service of services) {
    const dependency = "@deepseek-ai/" + service;
    if (realpathSync(team.resolve(dependency)) !== realpathSync(require.resolve(dependency))) fail();
  }
}
const { ShellEnvRegistry } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-shell-env")));
const { default: SshShellEnvRegistry } = await import(pathToFileURL(require.resolve("rotom-dsh-ssh-shell-env")));
if (!(SshShellEnvRegistry.prototype instanceof ShellEnvRegistry)) fail();
const subscriptionAuth = await import(pathToFileURL(require.resolve("rotom-dsh-ssh-subscription-auth")));
const subscriptionCli = await import(pathToFileURL(require.resolve("rotom-dsh-ssh-subscription-auth/cli")));
if (typeof subscriptionAuth.apply !== "function" || typeof subscriptionCli.runAuth !== "function") fail();
const { loadDependencies } = subscriptionAuth;
const authDependencies = await loadDependencies(["codex", "cursor"]);
if (authDependencies.TerminalCursorAdapter !== TerminalCursorAdapter
    || typeof authDependencies.CredentialGatedAdapter !== "function"
    || typeof authDependencies.createDshAuthApi !== "function") fail();
if (!(CursorAdapter.prototype instanceof LlmAdapter) || !(TerminalCursorAdapter.prototype instanceof CursorAdapter)) fail();
console.log("managed runtime versions and public module identities verified");
