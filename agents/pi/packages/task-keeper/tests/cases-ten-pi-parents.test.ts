import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { once } from "node:events";
import { createServer, type ServerResponse } from "node:http";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import type { RecoveryRecord } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

for (const mode of ["complete", "cancel-holder", "lost-holder"] as const)
test(`[A P E ${mode === "complete" ? "REC-013 T24" : "REC-014"}] ten actual Pi sessions ${mode} preserve the shared recovery permit`, { timeout: 100000 }, async t => {
  const ids = mode === "complete" ? ["REC-013", "T24"] : ["REC-014"];
  const expectedExits = new Set<string>();
  const root = isolatedDirectory(t), state = join(root, "state"), store = new Store(state);
  const pkg = fileURLToPath(new URL("..", import.meta.url));
  const initial = new Map<string, ServerResponse>(), pending: Array<{ model: string; res: ServerResponse }> = [];
  const counts = new Map<string, number>(), receiver: Array<{ model:string; ordinal:number; input:unknown; at:number }> = [];
  const clients: Array<{ model:string; child:ChildProcessWithoutNullStreams; events:any[]; stderr:string }> = [];
  const server = createServer((req,res) => {
    let body="";req.on("data",chunk=>body+=chunk);req.on("end",()=>{
      const input=JSON.parse(body), ordinal=(counts.get(input.model)??0)+1;counts.set(input.model,ordinal);
      receiver.push({model:input.model,ordinal,input,at:Date.now()});
      if(ordinal===1){
        initial.set(input.model,res);
        if(initial.size===10)for(const response of initial.values()){
          // The test controls quota and owner loss, not idle keep-alive socket
          // expiry while ten SDKs wait. Close the initial response explicitly.
          response.writeHead(429,{"content-type":"application/json","retry-after":"1","connection":"close"});
          response.end('{"error":{"code":"rate_limit","message":"shared controlled quota"}}');
        }
      } else pending.push({model:input.model,res});
    });
  });
  const port=await listenLoopback(server);
  t.after(async()=>{
    if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const target=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"ten-pi-parents");mkdirSync(target,{recursive:true});
      writeFileSync(join(target,`${mode}.json`),JSON.stringify({receiver,states:store.list("recovery"),claims:store.claims(),clients:clients.map(c=>({model:c.model,pid:c.child.pid,events:c.events,stderr:c.stderr}))},null,2));}
    store.close();
    await Promise.all(clients.map(async c=>{if(c.child.exitCode===null&&c.child.signalCode===null){const exited=once(c.child,"exit");c.child.kill("SIGKILL");await exited;}}));
    server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));
  });
  const deadline=Date.now()+85000;
  async function until(predicate:()=>boolean,label:string){while(!predicate()){
    if(Date.now()>deadline||clients.some(c=>!expectedExits.has(c.model)&&(c.child.exitCode!==null||c.child.signalCode!==null)))throw new Error(JSON.stringify({label,receiver:receiver.map(r=>[r.model,r.ordinal]),states:store.list("recovery"),errors:clients.map(c=>c.stderr)}));
    await delay(20);
  }}
  for(let i=0;i<10;i++){
    const model=`parent-${i}`, agent=join(root,model,"agent"),cwd=join(root,model,"workspace");mkdirSync(agent,{recursive:true});mkdirSync(cwd);
    writeFileSync(join(agent,"models.json"),JSON.stringify({providers:{"fixture-provider":{baseUrl:`http://127.0.0.1:${port}/v1`,apiKey:"fixture-only",api:"openai-completions",
      models:[{id:model,name:model,reasoning:false,input:["text"],contextWindow:32000,maxTokens:1000,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]}}}));
    writeFileSync(join(agent,"settings.json"),JSON.stringify({packages:[],compaction:{enabled:false},retry:{enabled:true,maxRetries:0,baseDelayMs:10,provider:{maxRetries:0,timeoutMs:90000}},quietStartup:true,enableInstallTelemetry:false}));
    const config=configured();config.routes.primary.model=model;config.storage.path=join(state,"runtime.db");config.recovery.requestTimeoutMs=60000;config.executionProfiles.interactive.timeoutMs=60000;
    const configPath=join(root,model,"task-keeper.json");writeFileSync(configPath,JSON.stringify(config));
    const child=spawn(process.execPath,[join(pkg,"node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"),"--mode","rpc","--no-extensions","-e",join(pkg,"index.ts"),
      "--no-skills","--no-context-files","--no-prompt-templates","--no-themes","--offline","--provider","fixture-provider","--model",model,"--thinking","off","--tools","read,write,edit","--session-dir",join(root,model,"sessions")],
      {cwd,stdio:["pipe","pipe","pipe"],env:{PATH:process.env.PATH,LANG:"C.UTF-8",PI_CODING_AGENT_DIR:agent,PI_TASK_KEEPER_CONFIG:configPath,PI_OFFLINE:"1",PI_TELEMETRY:"0"}});
    const client={model,child,events:[] as any[],stderr:""};clients.push(client);let buffer="";
    child.stderr.on("data",chunk=>client.stderr=(client.stderr+chunk).slice(-8000));
    child.stdout.on("data",chunk=>{buffer+=chunk;let at:number;while((at=buffer.indexOf("\n"))>=0){const line=buffer.slice(0,at);buffer=buffer.slice(at+1);if(line.trim())client.events.push(JSON.parse(line));}});
    child.stdin.write(JSON.stringify({id:"original",type:"prompt",message:`Complete the original bounded task ${model}`})+"\n");
  }
  await until(()=>pending.length>=1,"first actual recovery request");
  await until(()=>store.list<RecoveryRecord>("recovery").length===10,"ten native scopes");
  const query=async(c:typeof clients[number],id:string,action="status")=>{
    const offset=c.events.length;c.child.stdin.write(JSON.stringify({id,type:"prompt",message:`/throttle ${action}`})+"\n");
    await until(()=>c.events.slice(offset).some(e=>e.type==="response"&&e.id===id),id);
    return c.events.slice(offset).filter(e=>e.type==="extension_ui_request"&&e.method==="notify").flatMap(e=>{try{return[JSON.parse(e.message)];}catch{return[];}}).find(v=>v.recovery);
  };
  const ui=await Promise.all(clients.map((c,i)=>query(c,`waiting-status-${i}`)));
  const before=store.list<RecoveryRecord>("recovery").map(row=>row.value);
  for(const id of ids)evidence(id,()=>{
    assert.equal(new Set(clients.map(c=>c.child.pid)).size,10);assert.equal(new Set(before.map(r=>r.sessionId)).size,10);
    assert.equal(receiver.length,11);assert.equal(pending.length,1);assert.equal(store.claims().length,1);
    assert.equal(before.filter(r=>r.status==="RUNNING").length,1);assert.equal(before.filter(r=>r.status==="WAITING_QUOTA").length,9);
    assert.equal(store.claims()[0].intent_id,before.find(r=>r.status==="RUNNING")!.intentId);
    assert.equal(ui.filter(v=>v.recovery.status==="RUNNING").length,1);assert.equal(ui.filter(v=>v.recovery.status==="WAITING_QUOTA").length,9);
    assert.ok(ui.every(v=>v.adapter.certified===true&&v.coordination.stateRoot===state));
  });
  if(mode!=="complete"){
    const held=pending[0], holder=clients.find(c=>c.model===held.model)!, old=before.find(record=>record.status==="RUNNING")!, originalIntent=old.intentId!;
    let connectionClosed=false;held.res.on("close",()=>{connectionClosed=true;});
    if(mode==="lost-holder"){
      expectedExits.add(holder.model);const exited=once(holder.child,"exit");holder.child.kill("SIGKILL");await exited;
      await until(()=>connectionClosed,"dead holder socket closes");
      const floors=store.list<RecoveryRecord>("recovery").filter(row=>row.value.scopeId!==old.scopeId);
      await until(()=>floors.every(row=>store.get<RecoveryRecord>("recovery",row.id)!.notBefore>row.value.notBefore+100),"surviving waiters recheck capacity");
      // Test-only lock holder: force real BUSY errors beyond the production
      // connection's five-second timeout, then release this external writer.
      // Retry BEGIN IMMEDIATE if database is locked by other processes
      let lockAcquired = false;
      for (let attempt = 0; attempt < 10 && !lockAcquired; attempt++) {
        try {
          store.db.exec("BEGIN IMMEDIATE");
          lockAcquired = true;
          try { await delay(6500); }
          finally { store.db.exec("ROLLBACK"); }
        } catch (error) {
          if ((error as any).code === 'ERR_SQLITE_ERROR' && (error as any).message.includes('database is locked')) {
            await delay(500); // Wait before retry
          } else {
            throw error;
          }
        }
      }
      if (!lockAcquired) throw new Error('Failed to acquire database lock after 10 attempts');
      await until(()=>store.list<RecoveryRecord>("recovery").some(row=>row.value.lastDispatchError?.sqliteCode===5),"a real peer records transient SQLite contention");
      const views=await Promise.all(clients.filter(c=>c!==holder).map((c,i)=>query(c,`after-loss-${i}`)));
      evidence("REC-014",()=>{
        assert.equal(receiver.length,11);assert.equal(pending.length,1);assert.equal(store.claims().length,1);assert.equal(store.claims()[0].intent_id,originalIntent);
        assert.ok(["sent","acked","unknown"].includes(store.intent(originalIntent)!.status));
        assert.ok(views.every(view=>view.recovery.status==="WAITING_QUOTA"&&view.recovery.attempts===0));
        assert.ok(views.some(view=>view.recovery.lastDispatchError?.sqliteCode===5));
        assert.equal(holder.child.signalCode,"SIGKILL");assert.equal(connectionClosed,true);
        assert.equal(store.list<RecoveryRecord>("recovery").filter(row=>row.value.status==="DONE").length,0);
      });
      acceptance("AC09","unknown-held",{level:"P",observer:"ten-native-parents-and-dead-holder",predicate:"unknown execution keeps its shared permit",artifact:observerArtifact("ten-unknown-held",{receiver,views,intent:store.intent(originalIntent),claims:store.claims()})},()=>{assert.equal(receiver.length,11);assert.equal(store.claims().length,1);assert.equal(store.claims()[0].intent_id,originalIntent);});
      return;
    }
    await query(holder,"stop-holder","stop");
    await until(()=>connectionClosed&&store.intent(originalIntent)!.status==="settled"&&pending.length>=2,"cancelled request settles before successor");
    evidence("REC-014",()=>{
      assert.equal(receiver.length,12);assert.equal(pending.length,2);assert.equal(store.claims().length,1);
      assert.notEqual(store.claims()[0].intent_id,originalIntent);assert.notEqual(pending[1].model,held.model);
      assert.equal(store.get<RecoveryRecord>("recovery",old.scopeId)!.status,"PAUSED");
      assert.equal(store.get<RecoveryRecord>("recovery",old.scopeId)!.attempts,1);assert.equal(store.intent(originalIntent)!.status,"settled");
    });
    await Promise.all(clients.map((c,i)=>query(c,`pause-after-cancel-${i}`,"pause")));
    const successor=pending[1];successor.res.writeHead(200,{"content-type":"text/event-stream"});
    successor.res.end(`data: ${JSON.stringify({id:"successor",model:successor.model,choices:[{index:0,delta:{role:"assistant",content:"settled after pause"},finish_reason:"stop"}]})}\n\ndata: [DONE]\n\n`);
    await until(()=>store.claims().length===0,"successor terminal fact settles after pause");
    const finalViews=await Promise.all(clients.map((c,i)=>query(c,`cancel-final-${i}`)));
    evidence("REC-014",()=>{
      assert.equal(receiver.length,12);assert.equal(pending.length,2);assert.ok(finalViews.every(view=>view.recovery.status==="PAUSED"));
      assert.equal(store.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue' AND status='settled'").get()!.n,2);
      assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n,0);
    });
    return;
  }
  const completed:string[]=[];
  for(let i=0;i<10;i++){
    await until(()=>pending.length===i+1,`recovery ${i+1}`);assert.equal(store.claims().length,1);
    const current=pending[i];assert.equal(completed.includes(current.model),false);
    current.res.writeHead(200,{"content-type":"text/event-stream"});
    for(const choice of [{index:0,delta:{role:"assistant",content:"Original bounded task complete."},finish_reason:null},{index:0,delta:{},finish_reason:"stop"}])
      current.res.write(`data: ${JSON.stringify({id:`completed-${i}`,object:"chat.completion.chunk",model:current.model,choices:[choice]})}\n\n`);
    current.res.end("data: [DONE]\n\n");completed.push(current.model);
    await until(()=>store.list<RecoveryRecord>("recovery").filter(row=>row.value.status==="DONE").length===i+1,`terminal ${i+1}`);
  }
  const finalUi=await Promise.all(clients.map((c,i)=>query(c,`final-status-${i}`))),final=store.list<RecoveryRecord>("recovery").map(row=>row.value);
  for(const variant of ["ten-parents","settled-release"])acceptance("AC09",variant,{level:"P",observer:"ten-real-Pi-receivers-and-shared-SQLite-claims",predicate:"one holder at a time and release after settlement",artifact:observerArtifact(`ten-${variant}`,{receiver,final,finalUi,claims:store.claims(),completed})},()=>{assert.equal(receiver.length,20);assert.equal(new Set(completed).size,10);assert.equal(store.claims().length,0);assert.ok(final.every(row=>row.status==="DONE"&&row.attempts===1));});
  for(const id of ids)evidence(id,()=>{
    assert.equal(receiver.length,20);assert.equal(store.claims().length,0);assert.equal(new Set(completed).size,10);
    for(const client of clients){assert.equal(counts.get(client.model),2);assert.ok(client.events.some(e=>e.type==="agent_end"));}
    for(const record of final){const prior=before.find(r=>r.scopeId===record.scopeId)!;assert.equal(record.status,"DONE");assert.equal(record.attempts,1);assert.equal(record.sessionId,prior.sessionId);assert.equal(record.incidentId,prior.incidentId);assert.equal(record.history.length,1);}
    assert.ok(finalUi.every(v=>v.recovery.status==="DONE"&&v.recovery.attempts===1&&v.nativeFailures.total===1));
    for(const entry of receiver.filter(row=>row.ordinal===2)){
      const messages=(entry.input as {messages:Array<{role:string;content:unknown}>}).messages;
      assert.equal(messages.filter(message=>message.role==="user"&&JSON.stringify(message.content).includes(`Complete the original bounded task ${entry.model}`)).length,1);
      assert.ok(JSON.stringify(messages).includes("shared controlled quota"));
    }
    assert.equal(store.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n,10);
    assert.equal(store.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue' AND status='settled'").get()!.n,10);
    assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n,0);
  });
});
