import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { fork } from "node:child_process";
import { once } from "node:events";
import { readdirSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";
function retain(name: string, data: unknown) {
  if (!process.env.TASK_KEEPER_TEST_RECORD_DIR) return;
  const root = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "directory-observers"); mkdirSync(root, {recursive:true});
  writeFileSync(join(root, `${name}.json`), JSON.stringify(data, null, 2));
}
for (const different of [false, true]) test(`[P SCH-011 TK07] first-open race with ${different ? "different" : "identical"} configured database names cannot duplicate the host slot`, { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t), names = ["custom.db", different ? "other.db" : "custom.db"];
  const children = names.map((name, index) => fork(fileURLToPath(new URL("./fixtures/database-binding-worker.ts", import.meta.url)), [root, name, `owner-${index}`],
    { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] }));
  t.after(async () => { await Promise.all(children.map(async child => { if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGKILL"); await exit; } })); });
  const ready = await Promise.all(children.map(child => once(child, "message")));
  const pending = children.map(child => once(child, "message")); children.forEach(child => child.send("go"));
  const results = (await Promise.all(pending)).map(value => value[0]), winner = results.find(value => value.acquired);
  assert.ok(winner); const observer = new Store(root, winner.filename); t.after(() => observer.close());
  for (const id of ["SCH-011", "TK07"]) evidence(id, () => {
    assert.notEqual(ready[0][0].pid, ready[1][0].pid); assert.equal(results.filter(value => value.acquired).length, 1);
    assert.equal(results.find(value => !value.acquired).code, different ? "STATE_DATABASE_CONFLICT" : "RESOURCE_DENIED");
    assert.deepEqual(readdirSync(root).filter(name => name.endsWith(".db")), [winner.filename]);
    assert.equal(observer.claims().length, 1); assert.equal(observer.claims()[0].resource_id, "host-child");
    assert.equal(JSON.parse(readFileSync(join(root, ".task-keeper-database.json"), "utf8")).filename, winner.filename);
  });
  retain(different ? "different-filenames" : "same-filename", {ready,results,root:observer.root,claims:observer.claims()});
});


test("[P SCH-012 TK08] separate state directories coordinate independently even with the same resource and database name", {timeout:15000}, async t => {
  const roots = [isolatedDirectory(t), isolatedDirectory(t)];
  const children = roots.map((root, index) => fork(fileURLToPath(new URL("./fixtures/database-binding-worker.ts", import.meta.url)), [root, "custom.db", `owner-${index}`],
    { execArgv:["--experimental-strip-types"], stdio:["ignore","ignore","pipe","ipc"] }));
  t.after(async () => { await Promise.all(children.map(async child => { if (child.exitCode === null && child.signalCode === null) { const exit = once(child,"exit"); child.kill("SIGKILL"); await exit; } })); });
  const ready = await Promise.all(children.map(child => once(child,"message"))); const pending = children.map(child => once(child,"message")); children.forEach(child => child.send("go"));
  const results = (await Promise.all(pending)).map(value => value[0]);
  const observers = roots.map(root => new Store(root,"custom.db")); t.after(() => observers.forEach(store => store.close()));
  for (const id of ["SCH-012", "TK08"]) evidence(id, () => {
    assert.equal(results.filter(value => value.acquired).length, 2); assert.notEqual(results[0].stateRoot, results[1].stateRoot);
    for (const [index, observer] of observers.entries()) {
      assert.equal(results[index].stateRoot, observer.root); assert.equal(observer.claims().length, 1);
      assert.equal(observer.claims()[0].resource_id, "host-child"); assert.equal(observer.claims()[0].intent_id, `owner-${index}`);
      assert.equal(observer.intent(`owner-${1-index}`), null);
    }
  });
  acceptance("AC28","different-roots",{level:"P",observer:"two-real-processes-on-independent-state-roots",predicate:"separate configured roots coordinate independently",artifact:observerArtifact("different-roots",{ready,results,roots,claims:observers.map(s=>s.claims())})},()=>{assert.equal(results.filter(r=>r.acquired).length,2);assert.notEqual(results[0].stateRoot,results[1].stateRoot);assert.ok(observers.every(s=>s.claims().length===1));});
  retain("independent-roots", {ready,results,roots,claims:observers.map(store => store.claims())});
});
