import { test, assert } from "./recorded-test.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { Store } from "../src/store/database.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S TK08] separate ledgers admit independent slots and doctor declares each directory as its own coordination scope", async t => {
  const directories = [isolatedDirectory(t), isolatedDirectory(t)], reports: any[] = [];
  for (const [i, root] of directories.entries()) {
    const cwd=join(root,"workspace");mkdirSync(cwd);const config=configured();
    config.features.interactiveRecovery=false;config.features.managedWorkflows=false;config.storage.path=join(root,"state/runtime.db");
    const configPath=join(root,"config.json");writeFileSync(configPath,JSON.stringify(config));
    const saved=process.env.PI_TASK_KEEPER_CONFIG;process.env.PI_TASK_KEEPER_CONFIG=configPath;
    const hooks=new Map<string,any>(),commands=new Map<string,any>(),output:string[]=[];
    const pi={on:(name:string,fn:any)=>hooks.set(name,fn),registerCommand:(name:string,fn:any)=>commands.set(name,fn),registerTool(){},appendEntry(){}} as unknown as ExtensionAPI;
    const ctx={cwd,model:{api:"openai-completions",provider:"fixture-provider",id:"fixture-model",baseUrl:"http://127.0.0.1:1/v1"},
      modelRegistry:{find:()=>undefined},abort(){},ui:{notify:(text:string)=>output.push(text),setStatus(){}},
      sessionManager:{getBranch:()=>[],getHeader:()=>null,getSessionId:()=>`session-${i}`,getSessionFile:()=>null}} as unknown as ExtensionContext;
    taskKeeper(pi);
    try {
      await hooks.get("session_start")({},ctx);
      const store=new Store(join(root,"state"));
      try {
        const owner=store.claimOwner("manual-scope","owner");store.prepare(owner,"held-slot","write",{},[{id:"host-child",capacity:1,units:1}]);
        store.markSent(owner,"held-slot");store.settle("held-slot","unknown");
        await commands.get("orch").handler("doctor",ctx);
        const report=JSON.parse(output.at(-1)!);reports.push(report);
        assert.equal(report.coordination.stateRoot,store.root);assert.equal(report.coordination.database,store.path);
        assert.equal(report.coordination.scope,"one-database-per-state-directory");assert.equal(report.coordination.otherStateDirectories,"independent");
        assert.equal(report.coordination.crossParentFairness,false);assert.equal(store.claims().length,1);
        assert.equal(store.claims()[0].intent_id,"held-slot");
      } finally {store.close();}
    } finally {
      await hooks.get("session_shutdown")({},ctx);
      if(saved===undefined)delete process.env.PI_TASK_KEEPER_CONFIG;else process.env.PI_TASK_KEEPER_CONFIG=saved;
    }
  }
  assert.notEqual(reports[0].coordination.stateRoot,reports[1].coordination.stateRoot);
  assert.notEqual(reports[0].coordination.database,reports[1].coordination.database);
  for(const root of directories){const store=new Store(join(root,"state"));try{assert.equal(store.claims().length,1);assert.equal(store.intent("held-slot")!.status,"unknown");}finally{store.close();}}
});
