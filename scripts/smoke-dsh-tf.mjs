// 真实宿主与 Provider 适配器；仅向本机 fixture 发送三次虚构模型请求。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const runtime = process.argv[2];
const root = process.env.ROTOM_TF_ROOT;
assert(root?.startsWith("/dev/shm/") && ["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"]
  .every(key => process.env[key]?.startsWith(root + "/")));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)).href);
let booted;
let report = {kind: "native-host-simulated-TF", real_account_calls: 0, stage: "boot"};
try {
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
  booted = await runProfile({environment: createLaunchEnvironmentSnapshot([{source: "process", values: process.env}]),
    profile: "agentcfg", patchFiles: [process.env.ROTOM_TF_PATCH], args: [],
    packageManager: {command: "/bin/false", args: [], env: {}}});
  for (let i = 0; i < 1000 && booted.ctx.get("agents").list().length === 0; i++) {
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  const llm = booted.ctx.get("llm");
  const cases = [["kimi_tf", "k3", 4], ["zhipu_tf", "glm-5.3", 5], ["deepseek_tf", "deepseek-flash", 2]];
  report.catalogs = {};
  for (const [key, model, count] of cases) {
    report.stage = key;
    const provider = "agentcfg-" + key;
    const catalog = await llm.listModels(provider);
    assert.equal(catalog.length, count);
    assert(catalog.some(item => item.id === model));
    report.catalogs[key] = catalog.map(item => item.id);
    const chunks = [];
    for await (const chunk of llm.stream({provider, model, maxTokens: 16,
      messages: [{role: "user", content: [{type: "text", text: "TF_FIXTURE_REQUEST"}]}],
      signal: AbortSignal.timeout(10000)})) chunks.push(chunk);
    assert(JSON.stringify(chunks).includes("TF_FIXTURE_OK"));
    assert.equal(chunks.at(-1)?.type, "finish");
    assert(!["error", "aborted"].includes(chunks.at(-1)?.reason?.kind));
  }
  const settings = booted.ctx.get("settings").describe({redactSecrets: true}).find(row => row.ns === "dsh-tui")?.value;
  report.ui = {brand: settings?.brand, statusBar: settings?.statusBar};
  report.overall = "PASS";
} catch {
  report.overall = "FAIL";
  report.error = "TF_NATIVE_CASE_FAILED";
} finally {
  fs.writeFileSync(process.env.ROTOM_TF_RESULT, JSON.stringify(report, null, 2) + "\n", {mode: 0o600});
  if (booted) await booted.shutdown.shutdown(report.overall === "PASS" ? 0 : 1);
  else process.exitCode = 1;
}
