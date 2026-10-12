import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { semanticSource, sourceSnapshot, createWorkspace } from "../src/workspace/worktree.ts";
import { inputCanonical,inputDigest,compileInputSnapshot,validateSemanticSource } from "../src/evidence/context.ts";

function fixture(t:any){
  const root=fs.mkdtempSync(join(tmpdir(),"semantic-input-"));fs.mkdirSync(join(root,".git"));fs.writeFileSync(join(root,"source.txt"),"ordinary source");
  let tracked=["source.txt"],untracked:string[]=[];
  const mock=t.mock.method(childProcess,"execFileSync",(_exe:any,args:string[])=>{
    const cwd=args[args.indexOf("-C")+1];
    if(args.includes("--show-toplevel"))return Buffer.from(cwd+"\n");
    if(args.includes("--verify"))return Buffer.from("a".repeat(40)+"\n");
    if(args.includes("ls-tree")||args.includes("--cached"))return Buffer.from(tracked.join("\0")+(tracked.length?"\0":""));
    if(args.includes("--others"))return Buffer.from(untracked.join("\0")+(untracked.length?"\0":""));
    if(args.includes("--git-common-dir"))return Buffer.from(join(root,".git")+"\n");
    if(args.includes("--no-checkout")){const target=args[args.indexOf("--no-checkout")+1];fs.mkdirSync(target,{recursive:true});fs.writeFileSync(join(target,".git"),"gitdir: "+join(root,".git")+"\n");}
    return Buffer.from("");
  });syncBuiltinESMExports();t.after(()=>{mock.mock.restore();syncBuiltinESMExports();});
  const scope={schema_version:1,source_root:root,candidate_root:root,root_identity:null,creating:true,policy:{explicit_inputs:[],artifact_exclusions:[]},protected_inputs:[],outside_exclusions:[]};
  return {root,scope,tracked:(v:string[])=>tracked=v,untracked:(v:string[])=>untracked=v,capture:()=>semanticSource(root,scope)};
}
function identities(){
  const hash="a".repeat(64);return {config_identity:hash,effective_config_digest:hash,host_manifest_identity:hash,policy_digest:hash,project_constraints_digest:hash,resources_digest:hash,taskkeeper_policy_digest:hash,runtime_identity:hash,lock_identity:hash,slice_identity:hash,taskkeeper_runtime_identity:hash,capability_provider_digest:hash,model_routes:[],checker_contracts:[],local_acceptance_digest:hash,environment:{platform:"linux",architecture:"x64",node_version:"v24.14.0",sdk_version:"1.0.1",declared_nonsecret_variables:[{name:"LANG",value:"C.UTF-8"}]}};
}
test("real selected files detect untracked/external edits/deletion; filesystem outside Git inventory is not indexed",t=>{
 const f=fixture(t),initial=inputDigest(f.capture());fs.writeFileSync(join(f.root,"ignored.txt"),"ignored");assert.equal(inputDigest(f.capture()),initial);
 f.untracked(["new.txt"]);fs.writeFileSync(join(f.root,"new.txt"),"new");const added=inputDigest(f.capture());assert.notEqual(added,initial);
 fs.writeFileSync(join(f.root,"new.txt"),"external edit");assert.notEqual(inputDigest(f.capture()),added);
 fs.unlinkSync(join(f.root,"source.txt"));assert.equal(f.capture().files.find((x:any)=>x.relative_path==="source.txt").kind,"missing");
});
test("protected secret is never read by original sourceSnapshot/createWorkspace or semantic capture",t=>{
 const f=fixture(t),secret=join(f.root,".env"),body="secret sentinel unique-not-an-account";fs.writeFileSync(secret,body);f.tracked([".env","source.txt"]);
 f.scope.protected_inputs=[{relative_path:".env",reference:"file:project:.env",category:"protected-file",owner:null,provider:null}] as any;
 let secretReads=0;const original=fs.readFileSync;const read=t.mock.method(fs,"readFileSync",(p:any,...args:any[])=>{if(p===secret){secretReads++;throw Error("SECRET_READ");}return (original as any)(p,...args);});syncBuiltinESMExports();
 const old=sourceSnapshot(f.root,[],[secret]),fresh=f.capture();assert.equal(secretReads,0);assert.equal(old.files.some(x=>x.path===".env"),false);assert.equal(fresh.sensitive_inputs[0].state,"present");assert.equal(inputCanonical(fresh).includes(body),false);
 const state=join(f.root,"private-state");fs.mkdirSync(state);const workspace=createWorkspace(f.root,state,"job-secret",[],[secret]);assert.equal(fs.existsSync(join(workspace.path,".env")),false);assert.equal(secretReads,0);
 read.mock.restore();syncBuiltinESMExports();
});
test("explicit artifact growth stable; ordinary file named log remains input; tracked exclusion rejected",t=>{
 const f=fixture(t);fs.writeFileSync(join(f.root,"output.log"),"first");fs.writeFileSync(join(f.root,"log"),"source");f.untracked(["output.log","log"]);f.scope.policy.artifact_exclusions=[{relative_path:"output.log",kind:"file"}] as any;
 const initial=inputDigest(f.capture());fs.appendFileSync(join(f.root,"output.log")," observation grows");assert.equal(inputDigest(f.capture()),initial);
 fs.appendFileSync(join(f.root,"log")," real source edit");assert.notEqual(inputDigest(f.capture()),initial);f.tracked(["output.log"]);assert.throws(f.capture,/TRACKED_OVERLAP/);
});
test("every identity changes digest; nonsemantic observations are never supplied to composition",t=>{
 const f=fixture(t),source=f.capture(),meta=identities(),base=compileInputSnapshot(source,meta);
 for(const key of Object.keys(meta).filter(k=>typeof (meta as any)[k]==="string")){const altered={...meta,[key]:"b".repeat(64)};assert.notEqual(compileInputSnapshot(source,altered).digest,base.digest,key);}
 const observations={heartbeat:1,logs:1,polls:1,usage:1};observations.heartbeat++;observations.usage++;assert.equal(compileInputSnapshot(source,meta).digest,base.digest);assert.equal(inputCanonical(base).includes("heartbeat"),false);
 assert.throws(()=>compileInputSnapshot(source,{...meta,headers:{Authorization:"secret"}}),/INVALID/);
});
test("closed DTO rejects unknown/duplicate/order/unsafe shape, external/hardlink and list drift",t=>{
 const f=fixture(t),body=f.capture();assert.throws(()=>validateSemanticSource({...body,approved:true}),/INVALID/);
 assert.throws(()=>validateSemanticSource({...body,files:[...body.files,...body.files]}),/INVALID/);
 assert.throws(()=>inputCanonical({get value(){throw Error("must not invoke");}}),/INVALID/);
 assert.throws(()=>inputCanonical({value:Infinity}),/INVALID/);assert.throws(()=>inputCanonical({value:9007199254740992}),/INVALID/);
 fs.linkSync(join(f.root,"source.txt"),join(f.root,"alias"));assert.throws(f.capture,/LIMIT/);
});
test("UTF8 canonical ordering equals Python shared vector",()=>{
 assert.equal(inputCanonical({"😀":"x","\ue000":"y",a:1}),'{"a":1,"\ue000":"y","😀":"x"}');
});

test("held parent FD replacement with same path is rejected without partial snapshot",t=>{
 const f=fixture(t),dir=join(f.root,"nested"),originalDir=join(f.root,"held-old");fs.mkdirSync(dir);fs.writeFileSync(join(dir,"a.txt"),"same");f.tracked(["nested/a.txt"]);
 const original=fs.readSync;let changed=false;const mock=t.mock.method(fs,"readSync",(...args:any[])=>{const result=(original as any)(...args);if(!changed){changed=true;fs.renameSync(dir,originalDir);fs.mkdirSync(dir);fs.writeFileSync(join(dir,"a.txt"),"same");}return result;});syncBuiltinESMExports();
 assert.throws(f.capture,/INPUT_SNAPSHOT_DRIFT/);assert.equal(changed,true);mock.mock.restore();syncBuiltinESMExports();
});
test("selected set changes while reading and missing tracked parent are not silently omitted",t=>{
 const f=fixture(t);f.tracked(["removed/a.txt","source.txt"]);assert.equal(f.capture().files[0].kind,"missing");
 const original=fs.readSync;let changed=false;const mock=t.mock.method(fs,"readSync",(...args:any[])=>{const value=(original as any)(...args);if(!changed){changed=true;fs.writeFileSync(join(f.root,"external.txt"),"new input");f.untracked(["external.txt"]);}return value;});syncBuiltinESMExports();assert.throws(f.capture,/DRIFT/);mock.mock.restore();syncBuiltinESMExports();
});
test("metadata/selected-record/output caps, internal symlink coverage and secret accessors fail closed",t=>{
 const f=fixture(t);fs.symlinkSync("source.txt",join(f.root,"link"));f.untracked(["link"]);assert.equal(f.capture().files.find((v:any)=>v.kind==="symlink").target,"source.txt");
 f.tracked([]);assert.throws(f.capture,/SYMLINK/);assert.throws(()=>inputDigest({value:"x".repeat(1024*1024)}),/INVALID/);
 const poisoned:any={};Object.defineProperty(poisoned,"headers",{get(){throw Error("secret callback");},enumerable:true});assert.throws(()=>inputCanonical(poisoned),/INVALID/);
});

test("identical semantic snapshot still reserves every independent request under original budget",async()=>{
 const {RequestLedger}=await import("../src/store/request-ledger.ts");const {fixture:ledgerFixture}=await import("../../../runtime/tests/fixtures.ts");const {store}=ledgerFixture();let admissions=0;
 const ledger=new RequestLedger({store,task_id:"semantic-task",budget_scope_id:"scope",limits:{model_requests:2,model_turns:2,deadline:"2026-10-12T01:00:00Z"},now:()=>Date.parse("2026-10-12T00:00:00Z"),verify:(request:any)=>{admissions++;return {valid:true,route_id:request.route_id,grant_digest:request.grant_digest,bounds_certified:true};}});
 const semantic=inputDigest({semantic:"identical"});const base={task_id:"semantic-task",attempt_id:"attempt",reason:"initial",turn_id:"turn",route_id:"direct",grant_digest:"a".repeat(64),payload_digest:semantic,reserved_input_tokens:1,reserved_output_tokens:1,reserved_cost:"0.01"};
 const first=await ledger.reserve({...base,request_id:"one"}),second=await ledger.reserve({...base,request_id:"two"});assert.notEqual(first.reservation_id,second.reservation_id);assert.equal(second.ordinal,2);assert.equal(admissions,2);
 await assert.rejects(ledger.reserve({...base,request_id:"three"}),/BUDGET_EXHAUSTED/);assert.equal(admissions,3);
});

test("complete DTO Python/TS shared UTF8 vector has identical digest",()=>{
 const vector=JSON.parse(fs.readFileSync(new URL("./fixtures/input-snapshot-vector.json",import.meta.url),"utf8"));assert.equal(compileInputSnapshot(vector.source,vector.identities).digest,vector.expected_digest);
});
