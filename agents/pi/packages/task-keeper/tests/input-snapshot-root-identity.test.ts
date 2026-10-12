import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import childProcess from "node:child_process";
import { createHash } from "node:crypto";
import { syncBuiltinESMExports } from "node:module";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { semanticSource } from "../src/workspace/worktree.ts";
import { inputCanonical,inputDigest } from "../src/evidence/context.ts";

const physical=(tuple:any)=>createHash("sha256").update(inputCanonical(tuple)+"\n").digest("hex");
test("original Python root identity LF vector and real snapshot non-null scope match; creation shares physical identity",t=>{
  const vector=JSON.parse(fs.readFileSync(new URL("./fixtures/workspace-physical-identity-vector.json",import.meta.url),"utf8"));
  const tuple={device:vector.device,inode:vector.inode,uid:vector.uid};assert.equal(physical(tuple),vector.root_identity);assert.notEqual(inputDigest(tuple),vector.root_identity);
  const root=fs.mkdtempSync(join(tmpdir(),"root-identity-"));fs.mkdirSync(join(root,".git"));fs.writeFileSync(join(root,"source.txt"),"source");
  const mock=t.mock.method(childProcess,"execFileSync",(_exe:any,args:string[])=>{
    if(args.includes("ls-tree")||args.includes("--cached"))return Buffer.from("source.txt\0");
    if(args.includes("--others"))return Buffer.from("");throw Error("unexpected fake Git command");
  });syncBuiltinESMExports();t.after(()=>{mock.mock.restore();syncBuiltinESMExports();});
  const info=fs.lstatSync(root,{bigint:true}),current={device:String(info.dev),inode:String(info.ino),uid:String(info.uid)};
  const expected=physical(current),scope={schema_version:1,source_root:root,candidate_root:root,root_identity:null as string|null,creating:true,policy:{explicit_inputs:[],artifact_exclusions:[]},protected_inputs:[],outside_exclusions:[]};
  assert.equal(semanticSource(root,scope).workspace_identity,expected);
  scope.creating=false;scope.root_identity=expected;assert.equal(semanticSource(root,scope).workspace_identity,expected);
  for(const changed of [{...current,inode:String(info.ino+1n)},{...current,uid:String(info.uid+1n)}]){scope.root_identity=physical(changed);assert.throws(()=>semanticSource(root,scope),/ROOT_IDENTITY/);}
  scope.root_identity=inputDigest(current);assert.throws(()=>semanticSource(root,scope),/ROOT_IDENTITY/);
});

test("empty selected domain still rejects root UID drift during final inventory rescan",t=>{
  const root=fs.mkdtempSync(join(tmpdir(),"root-uid-drift-"));fs.mkdirSync(join(root,".git"));let scans=0,changed=false;
  const git=t.mock.method(childProcess,"execFileSync",(_exe:any,args:string[])=>{if(args.includes("--others")&&++scans===2)changed=true;return Buffer.from("");});
  const original=fs.lstatSync;
  const stat=t.mock.method(fs,"lstatSync",(p:any,opts:any)=>{const info=(original as any)(p,opts);if(p===root&&changed)return Object.assign(Object.create(Object.getPrototypeOf(info)),info,{uid:info.uid+1n});return info;});
  syncBuiltinESMExports();t.after(()=>{git.mock.restore();stat.mock.restore();syncBuiltinESMExports();});
  const scope={schema_version:1,source_root:root,candidate_root:root,root_identity:null,creating:true,policy:{explicit_inputs:[],artifact_exclusions:[]},protected_inputs:[],outside_exclusions:[]};
  assert.throws(()=>semanticSource(root,scope),/INPUT_SNAPSHOT_DRIFT/);
});
