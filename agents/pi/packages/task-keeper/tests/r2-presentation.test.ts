import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {spawn} from "node:child_process";
import {createServer} from "node:http";
import {mkdirSync,writeFileSync,readFileSync} from "node:fs";
import {join,dirname} from "node:path";
import {fileURLToPath} from "node:url";
import {isolatedDirectory,listenLoopback} from "./helpers.ts";

test("[A E] Pi JSON print mode reports status without UI or model requests",{timeout:20000},async t=>{
  const root=isolatedDirectory(t),agent=join(root,"agent"),pkg=fileURLToPath(new URL("..",import.meta.url));mkdirSync(agent);
  let requests=0;const server=createServer((req,res)=>{requests++;req.resume();res.writeHead(500);res.end("unexpected model request");});await listenLoopback(server);t.after(()=>{server.closeAllConnections();server.close();});
  writeFileSync(join(agent,"models.json"),JSON.stringify({providers:{fixture:{api:"openai-completions",baseUrl:`http://127.0.0.1:${(server.address() as {port:number}).port}/v1`,apiKey:"fixture-only",models:[{id:"model",name:"Fixture",reasoning:false,input:["text"],contextWindow:32000,maxTokens:1000,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}}]}}}));
  writeFileSync(join(agent,"settings.json"),JSON.stringify({packages:[],enableInstallTelemetry:false,compaction:{enabled:false}}));
  const config=join(root,"config.json");writeFileSync(config,JSON.stringify({enabled:false,storage:{path:join(root,"state/runtime.db")}}));
  const child=spawn(process.execPath,[join(pkg,"node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"),"--mode","json","--print","--no-extensions","-e",join(pkg,"index.ts"),"--no-tools","--no-skills","--no-context-files","--no-prompt-templates","--no-themes","--offline","--provider","fixture","--model","model","--session-dir",join(root,"sessions"),"/orch doctor"],{cwd:root,env:{PATH:process.env.PATH,PI_CODING_AGENT_DIR:agent,PI_TASK_KEEPER_CONFIG:config,PI_OFFLINE:"1",PI_TELEMETRY:"0"},stdio:["ignore","pipe","pipe"]});
  t.after(()=>{if(child.exitCode===null&&child.signalCode===null)child.kill("SIGKILL");});let output="",error="";child.stdout.on("data",b=>{output+=b;});child.stderr.on("data",b=>{error+=b;});
  const exit=await new Promise<number|null>((resolve,reject)=>{child.once("error",reject);child.once("close",resolve);});
  const events=output.trim().split("\n").filter(Boolean).map(line=>JSON.parse(line)),status=events.find(e=>e.message?.customType==="task-keeper:status")?.message;
  acceptance("AC33","no-ui",{level:"A",observer:"actual-Pi-JSON-mode-events-without-interactive-UI",predicate:"explicit status is visible without triggering a model turn",artifact:observerArtifact("no-ui",{events,error,exit,requests})},()=>{assert.equal(exit,0,error);assert.ok(status,output);assert.equal(requests,0);assert.equal(status.display,true);assert.deepEqual(JSON.parse(status.content),status.details);assert.equal(status.details.enabled,false);});
});

test("[P E] actual test namespace hides real home and protects absolute and symlink targets",()=>{
  const root=dirname(process.env.TASK_KEEPER_TEST_WORK_ROOT!),proof=JSON.parse(readFileSync(join(root,"isolation.json"),"utf8"));
  acceptance("AC35","readonly-real-home",{level:"P",observer:"launcher-independent-mount-and-write-probes",predicate:"synchronization and Pi run with real home hidden and host files read-only",artifact:observerArtifact("home-isolation",proof)},()=>{assert.equal(proof.passed,true);for(const check of ["private home","absolute write denied","symlink write denied","real Claude config hidden"])assert.ok(proof.checks.includes(check));assert.notEqual(process.env.HOME,"/home/weixiaoxian.wxx");});
});
