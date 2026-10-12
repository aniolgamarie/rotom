import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import childProcess from "node:child_process";
import { createHash } from "node:crypto";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { captureTree } from "../src/workspace/worktree.ts";
function setup(t:any,fault:string|null=null){
 const root=fs.mkdtempSync(join(tmpdir(),"semantic-tree-")),cwd=join(root,"source"),state=join(root,"state");fs.mkdirSync(cwd);fs.mkdirSync(state);fs.mkdirSync(join(cwd,".git"));fs.writeFileSync(join(cwd,"source.txt"),"safe original");
 const calls:any[]=[],objects=new Map<string,Buffer>(),entries:any[]=[];let pathAdds=0,tracked=["source.txt"];
 const mock=t.mock.method(childProcess,"execFileSync",(_exe:any,args:string[],opts:any)=>{
  calls.push({args:[...args],stdin:opts.input});const source=args[args.indexOf("-C")+1];assert.equal(opts.maxBuffer,32*1024*1024);
  if(args.includes("--show-toplevel"))return Buffer.from(source+"\n");if(args.includes("--verify"))return Buffer.from("a".repeat(40)+"\n");
  if(args.includes("--git-common-dir"))return Buffer.from(join(cwd,".git")+"\n");
  if(args.includes("--bare")){fs.mkdirSync(join(args.at(-1),"objects/info"),{recursive:true});return Buffer.from("");}
  if(args.includes("ls-files"))return Buffer.from(tracked.join("\0")+"\0");
  if(args.includes("ls-tree")&&args.includes("--name-only"))return Buffer.from(tracked.join("\0")+"\0");
  if(args.includes("add")&&!args.includes("--cacheinfo")){pathAdds++;return Buffer.from("");}
  if(args.includes("hash-object")){assert.ok(Buffer.isBuffer(opts.input));const body=Buffer.from(opts.input),oid=createHash("sha1").update(`blob ${body.length}\0`).update(body).digest("hex");objects.set(oid,body);if(fault==="replace")fs.writeFileSync(join(cwd,"source.txt"),"replaced after capture");return Buffer.from((fault==="wrong-oid"?"0".repeat(40):oid)+"\n");}
  if(args.includes("cat-file"))return objects.get(args.at(-1))??Buffer.from("wrong blob");
  if(args.includes("--cacheinfo")){const i=args.indexOf("--cacheinfo");entries.push({mode:args[i+1],oid:args[i+2],name:args[i+3]});return Buffer.from("");}
  if(args.includes("write-tree"))return Buffer.from("b".repeat(40)+"\n");
  if(args.includes("ls-tree")){const rows=entries.map(e=>`${fault==="wrong-mode"?"100755":e.mode} blob ${e.oid}\t${fault==="wrong-name"?"untracked.txt":e.name}\0`);return Buffer.from(rows.join(""));}
  return Buffer.from("");
 });syncBuiltinESMExports();t.after(()=>{mock.mock.restore();syncBuiltinESMExports();});return {root,cwd,state,calls,entries,pathAdds:()=>pathAdds,setTracked:(v:string[])=>tracked=v};
}
test("modern capture writes only verified fixed stdin blobs/index entries, no path git add or filters",t=>{
 const f=setup(t),result=captureTree(f.cwd,f.state,"job",[],[],true);assert.equal(f.pathAdds(),0);assert.equal(f.entries.length,1);assert.equal(f.entries[0].mode,"100644");assert.equal(result.tree,"b".repeat(40));assert.ok(f.calls.some(c=>c.args.includes("hash-object")&&c.args.includes("--stdin")&&c.stdin.toString()==="safe original"));
});
for(const fault of ["replace","wrong-oid","wrong-mode","wrong-name"])test(`modern capture rejects ${fault} instead of publishing mismatched patch/tree`,t=>{
 const f=setup(t,fault);assert.throws(()=>captureTree(f.cwd,f.state,"job",[],[],true),/INPUT_|SOURCE_/);assert.equal(f.pathAdds(),0);assert.equal(f.calls.some(c=>c.args.includes("update-ref")),false);
});

test("40MiB safe stdin payload is valid with original 32MiB stdout cap; wrong OID still rejects",t=>{
 const f=setup(t);fs.writeFileSync(join(f.cwd,"source.txt"),Buffer.alloc(40*1024*1024,97));assert.equal(captureTree(f.cwd,f.state,"large",[],[],true).tree,"b".repeat(40));assert.equal(f.calls.find(c=>c.args.includes("hash-object")).stdin.length,40*1024*1024);assert.equal(f.calls.some(c=>c.args.includes("cat-file")),false);
});
test("original capture source classification excludes secret bytes from fixed stdin and any path git reads",t=>{
 const f=setup(t),secret=join(f.cwd,".env"),sentinel="not-an-account secret sentinel";fs.writeFileSync(secret,sentinel);f.setTracked([".env","source.txt"]);
 assert.equal(captureTree(f.cwd,f.state,"secret",[],[secret],true).tree,"b".repeat(40));assert.equal(f.pathAdds(),0);assert.equal(f.calls.some(c=>c.stdin?.includes(Buffer.from(sentinel))),false);assert.equal(f.entries.some(e=>e.name===".env"),false);
});
