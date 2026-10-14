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
  const localVersion = { "rotom-dsh-cursor-terminal": "0.1.2", "rotom-dsh-review-context": "0.1.0" }[name];
  if (actual.name !== name || actual.version !== (localVersion ?? version)) fail();
}
if (manifest(require, "@deepseek-ai/cordis").version !== "4.0.5-alpha.1"
    || manifest(require, "@deepseek-ai/schemastery").version !== "3.18.5-alpha.1"
    || manifest(require, "@deepseek-harness-tui/dsh-tui").version !== "0.15.0") fail();
const tui = createRequire(require.resolve("@deepseek-harness-tui/dsh-tui/package.json"));
const thin = createRequire(require.resolve("rotom-dsh-cursor-terminal"));
const cursor = createRequire(thin.resolve("dsh-cursor-subscription"));
const perry = createRequire(require.resolve("dsh-auto-review"));
const reviewContext = createRequire(require.resolve("rotom-dsh-review-context"));
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
if (!["3.18.4", "3.18.5-alpha.1"].includes(manifest(cursor, "@deepseek-ai/schemastery").version)) fail();
for (const name of ["dsh-agent", "dsh-session", "dsh-subagent", "dsh-tools", "dsh-user-approval", "dsh-invariants", "dsh-brand"]) {
  const packageName = "@deepseek-ai/" + name;
  if (manifest(perry, packageName).version !== "0.2.0-rc.2"
      || realpathSync(perry.resolve(packageName)) !== realpathSync(require.resolve(packageName))) fail();
}
if (manifest(tui, "react").version.split(".")[0] !== "19"
    || realpathSync(tui.resolve("react")) !== realpathSync(require.resolve("react"))) fail();
const { LlmAdapter } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-llm")));
const { CursorAdapter } = await import(pathToFileURL(cursor.resolve("dsh-cursor-subscription")));
const { TerminalCursorAdapter } = await import(pathToFileURL(require.resolve("rotom-dsh-cursor-terminal")));
const review = await import(pathToFileURL(require.resolve("dsh-auto-review")));
if (manifest(perry, "dsh-auto-review").version !== "0.12.17" || typeof review.apply !== "function") fail();
// 原生 preset 的文件搜索/jobs 和 spill 路径也必须能导入，不能只验证顶层 SDK。
for (const name of ["dsh-command-feedback", "dsh-spill-local", "dsh-spill-policy", "dsh-tool-fs-search", "dsh-tool-jobs"]) {
  await import(pathToFileURL(require.resolve("@deepseek-ai/" + name)));
}
if (!(CursorAdapter.prototype instanceof LlmAdapter) || !(TerminalCursorAdapter.prototype instanceof CursorAdapter)) fail();
console.log("managed runtime versions and public module identities verified");
