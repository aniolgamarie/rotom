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
  if (actual.name !== name || actual.version !== (name === "rotom-dsh-cursor-terminal" ? "0.1.0" : version)) fail();
}
if (manifest(require, "@deepseek-ai/cordis").version !== "4.0.4"
    || manifest(require, "@deepseek-ai/schemastery").version !== "3.18.4"
    || manifest(require, "@deepseek-harness-tui/dsh-tui").version !== "0.14.0") fail();
const tui = createRequire(require.resolve("@deepseek-harness-tui/dsh-tui/package.json"));
const thin = createRequire(require.resolve("rotom-dsh-cursor-terminal"));
const cursor = createRequire(thin.resolve("dsh-cursor-subscription"));
if (manifest(cursor, "dsh-cursor-subscription").version !== "0.6.12") fail();
for (const resolve of [tui, thin, cursor]) {
  for (const name of ["@deepseek-ai/dsh-llm", "@deepseek-ai/dsh-credentials", "@deepseek-ai/cordis", "@deepseek-ai/schemastery"]) {
    if (realpathSync(resolve.resolve(name)) !== realpathSync(require.resolve(name))) fail();
  }
}
if (manifest(tui, "react").version.split(".")[0] !== "19"
    || realpathSync(tui.resolve("react")) !== realpathSync(require.resolve("react"))) fail();
const { LlmAdapter } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-llm")));
const { CursorAdapter } = await import(pathToFileURL(cursor.resolve("dsh-cursor-subscription")));
const { TerminalCursorAdapter } = await import(pathToFileURL(require.resolve("rotom-dsh-cursor-terminal")));
if (!(CursorAdapter.prototype instanceof LlmAdapter) || !(TerminalCursorAdapter.prototype instanceof CursorAdapter)) fail();
console.log("managed runtime versions and public module identities verified");
