import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, cpSync } from "node:fs";
import { dirname, join } from "node:path";
import { Store } from "../src/store/database.ts";
import { businessDigest } from "../src/store/maintenance.ts";
import { digest } from "../src/contracts/primitives.ts";
import { isolatedDirectory } from "./helpers.ts";

// Calls the repository's actual sync service with a private target inside bwrap.
test("[E CFG-011] repeated actual Pi synchronization preserves live database facts, bindings, credentials and workspace", { timeout: 45000 }, t => {
  assert.equal(process.env.TASK_KEEPER_ISOLATED, "1");
  const root = isolatedDirectory(t), home = join(root, "agent"), workspace = join(root, "workspace");
  mkdirSync(home); mkdirSync(workspace); writeFileSync(join(workspace, "user.txt"), "user modification\n");
  const policy = '{"enabled":false,"schemaVersion":6}', auth = '{"synthetic":{"type":"api_key","key":"test-only"}}';
  writeFileSync(join(home, "task-keeper.json"), policy); writeFileSync(join(home, "auth.json"), auth, { mode: 0o600 });
  const store = new Store(join(home, "task-keeper-state")), owner = store.claimOwner("scope", "sync-observer");
  store.prepare(owner, "unknown-write", "write", { cwd: workspace }, [{ id: "workspace", capacity: 1, units: 1 }]);
  store.markSent(owner, "unknown-write"); store.reserveRequest(owner, "unknown-write", "unknown-request", [{ id: "work", ceiling: 4 }]);
  store.settleRequest("unknown-request", "unknown"); store.settle("unknown-write", "unknown");
  store.put("recovery", "scope", { status: "WAITING_QUOTA", notBefore: 9999999999999, incidentId: "original", history: ["limit"] });
  const before = businessDigest(store.db); store.close();
  const lua = join(root, "sync.lua");
  writeFileSync(lua, `vim.g.ai_test_mode = true
vim.opt.runtimepath:append(vim.env.TASK_KEEPER_TEST_REPO_ROOT .. "/local-plugins/ai")
local opts = { pi_dir = vim.env.TASK_KEEPER_SYNC_TARGET, repo_root = vim.env.TASK_KEEPER_TEST_REPO_ROOT,
 config_dir = vim.env.TASK_KEEPER_TEST_REPO_ROOT, version = "default", pi_executable = "definitely-not-pi", silent = true }
local ok, err = require("ai.pi").write_config(opts)
if not ok then io.stderr:write(tostring(err)); vim.cmd("cquit 1") end
vim.cmd("qa!")
`);
  const logs: string[] = [];
  for (let pass = 0; pass < 2; pass++) {
    const child = spawnSync(process.env.TASK_KEEPER_TEST_NVIM!, ["--headless", "--noplugin", "-u", "NONE", "-l", lua], {
      cwd: process.env.TASK_KEEPER_TEST_REPO_ROOT, encoding: "utf8", timeout: 20000,
      env: { ...process.env, TASK_KEEPER_SYNC_TARGET: home },
    });
    logs.push(child.stdout + child.stderr);
    evidence("CFG-011", () => {
      assert.equal(child.status, 0, String(child.error ?? logs.at(-1)));
      const settings = JSON.parse(readFileSync(join(home, "settings.json"), "utf8"));
      assert.ok(settings.packages.some((item: unknown) => typeof item === "string" && item.endsWith("/pi/packages/task-keeper")));
      assert.equal(readFileSync(join(home, "task-keeper.json"), "utf8"), policy);
      assert.equal(readFileSync(join(home, "auth.json"), "utf8"), auth);
      assert.equal(readFileSync(join(workspace, "user.txt"), "utf8"), "user modification\n");
      assert.equal(readFileSync(join(home, "packages/task-keeper/index.ts"), "utf8"), readFileSync(new URL("../index.ts", import.meta.url), "utf8"));
      const observer = new Store(join(home, "task-keeper-state"));
      try {
        assert.equal(businessDigest(observer.db), before); assert.equal(observer.intent("unknown-write")!.status, "unknown");
        assert.equal(observer.request("unknown-request")!.state, "unknown"); assert.equal(observer.bucket("work")!.reserved, 1);
        assert.equal(observer.claims().length, 1); assert.equal(observer.get<{incidentId:string}>("recovery", "scope")!.incidentId, "original");
      } finally { observer.close(); }
    });
  }
  acceptance("AC35","sync-twice",{level:"E",observer:"two-real-Neovim-sync-invocations-and-live-DB",predicate:"repeated sync preserves policy credentials unknown leases and source",artifact:observerArtifact("sync-twice",{logs,before,policyDigest:digest(policy),authDigest:digest(auth)})},()=>{
    const observer=new Store(join(home,"task-keeper-state"));try{assert.equal(logs.length,2);assert.equal(businessDigest(observer.db),before);assert.equal(observer.claims().length,1);assert.equal(observer.intent("unknown-write")!.status,"unknown");assert.equal(readFileSync(join(home,"auth.json"),"utf8"),auth);}finally{observer.close();}
  });
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const target = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "sync-observers"); mkdirSync(target);
    writeFileSync(join(target, "sync.log"), logs.join("\n"));
    writeFileSync(join(target, "observer.json"), JSON.stringify({ before, policyDigest: digest(policy), authDigest: digest(auth), passes: logs.length }));
    cpSync(join(home, "task-keeper-state"), join(target, "state"), { recursive: true });
  }
});
