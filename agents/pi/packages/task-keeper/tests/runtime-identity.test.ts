import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { cpSync, readFileSync, writeFileSync, unlinkSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { runtimeIdentity } from "../src/adapters/runtime-identity.ts";
import { inspectRuntimeProfile } from "../src/adapters/pi-interactive.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[A EXE-002] unchanged CLI stub cannot certify changed runtime chunks", t => {
  const root = isolatedDirectory(t), pkg = fileURLToPath(new URL("../node_modules/@earendil-works/pi-coding-agent", import.meta.url));
  cpSync(join(pkg, "dist/bundle"), join(root, "dist/bundle"), { recursive: true });
  cpSync(join(pkg, "package.json"), join(root, "package.json"));
  const cli = join(root, "dist/bundle/cli.js"), entry = fileURLToPath(new URL("../index.ts", import.meta.url));
  const argv = [process.execPath, cli, "--no-extensions", "-e", entry];
  const original = runtimeIdentity(argv); assert.equal(original.supported, true); assert.equal(inspectRuntimeProfile(argv).supported, true);
  const chunkName = /"\.\/chunks\/([^"/]+\.js)"/.exec(readFileSync(cli, "utf8"))![1];
  const chunk = join(root, "dist/bundle/chunks", chunkName), saved = readFileSync(chunk);
  writeFileSync(chunk, Buffer.concat([saved, Buffer.from("\n// changed executable bundle\n")]));
  const changed = runtimeIdentity(argv);
  assert.equal(changed.cliSha256, original.cliSha256); assert.notEqual(changed.bundleSha256, original.bundleSha256);
  assert.equal(changed.supported, false); assert.equal(inspectRuntimeProfile(argv).supported, false);
  assert.ok(inspectRuntimeProfile(argv).reasons.includes("runtime_identity_not_in_contract_matrix"));
  acceptance("AC25","version-drift",{level:"A",observer:"actual-runtime-bundle-hash-and-profile-contract",predicate:"same CLI stub cannot hide changed runtime implementation",artifact:observerArtifact("runtime-drift",{original,changed,profile:inspectRuntimeProfile(argv)})},()=>{assert.equal(changed.cliSha256,original.cliSha256);assert.notEqual(changed.bundleSha256,original.bundleSha256);assert.equal(changed.supported,false);assert.equal(inspectRuntimeProfile(argv).supported,false);});
  writeFileSync(chunk, saved); assert.equal(runtimeIdentity(argv).supported, true);
  const extra = join(root, "dist/bundle/chunks/extra.js"); writeFileSync(extra, "export const changed=true;");
  assert.equal(runtimeIdentity(argv).supported, false); unlinkSync(extra);
  unlinkSync(chunk); assert.equal(runtimeIdentity(argv).supported, false);
  symlinkSync(join(pkg, "dist/bundle/chunks", chunkName), chunk); assert.equal(runtimeIdentity(argv).supported, false);
});

test("[A EXE-002] Task Keeper code changes require reload and invalidate the old review runtime identity", async t => {
  const root = isolatedDirectory(t), pkg = fileURLToPath(new URL("..", import.meta.url));
  for (const file of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(pkg, file), join(root, file), { recursive: true });
  const url = pathToFileURL(join(root, "src/adapters/task-keeper-identity.ts")).href;
  const loaded = await import(url), before = loaded.taskKeeperRuntimeIdentity();
  assert.equal(typeof before, "string"); assert.equal(loaded.taskKeeperRuntimeIdentity(), before);
  const review = join(root, "src/verification/review.ts"), original = readFileSync(review, "utf8");
  writeFileSync(review, original + "\n// Different review implementation identity\n");
  assert.throws(() => loaded.taskKeeperRuntimeIdentity(), { code: "TASK_KEEPER_RUNTIME_CHANGED_RELOAD_REQUIRED" });
  const restarted = await import(url + "?restarted");
  assert.notEqual(restarted.taskKeeperRuntimeIdentity(), before);
  writeFileSync(review, original);
  assert.equal(loaded.taskKeeperRuntimeIdentity(), before);
  assert.throws(() => restarted.taskKeeperRuntimeIdentity(), { code: "TASK_KEEPER_RUNTIME_CHANGED_RELOAD_REQUIRED" });
});

test("[A EXE-002] the pinned required subagents extension may coexist with recovery but extra extensions are not certified", t => {
  const root = isolatedDirectory(t), pkg = fileURLToPath(new URL("..", import.meta.url));
  const argv = [process.execPath, join(pkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"), "--no-extensions",
    "-e", join(pkg, "node_modules/pi-subagents/index.ts"), "-e", join(pkg, "index.ts")];
  assert.equal(inspectRuntimeProfile(argv).supported, true);
  const extra = join(root, "extra.ts"); writeFileSync(extra, "export default function() {}\n");
  assert.ok(inspectRuntimeProfile([...argv, "-e", extra]).reasons.includes("extension_set_not_in_contract_test_matrix"));
  assert.ok(inspectRuntimeProfile([...argv, "-e", join(pkg, "index.ts")]).reasons.includes("extension_set_not_in_contract_test_matrix"));
  assert.equal(inspectRuntimeProfile(argv.filter(arg => arg !== "--no-extensions")).supported, false);
  assert.equal(inspectRuntimeProfile([...argv.slice(0, 3), "-e", join(pkg, "index.ts"), "-e", join(pkg, "node_modules/pi-subagents/index.ts")]).supported, false);
});
