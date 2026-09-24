import {cpSync,readFileSync,writeFileSync,symlinkSync} from "node:fs";
import {join,relative} from "node:path";
import {createHash} from "node:crypto";
/** Private copies only: actual Pi enqueue/HTTP/terminal behavior is retained. */
export function nativeContinuationCut(source:string,root:string,point:string){
  const copy=join(root,"continue-cut-runtime");cpSync(source,copy,{recursive:true,filter:path=>!relative(source,path).split("/").some(part=>["node_modules","test-results","coverage",".git"].includes(part))});symlinkSync(join(source,"node_modules"),join(copy,"node_modules"));
  const marker=join(root,"continue-cut.json"),path=join(copy,"src/reliability/recovery.ts"),original=readFileSync(path,"utf8");
  writeFileSync(join(copy,"src/contracts/continue-cut.ts"),`import {writeFileSync,renameSync,existsSync} from "node:fs";export function hit(data:unknown){const path=${JSON.stringify(marker)};if(existsSync(path))return;writeFileSync(path+".tmp",JSON.stringify({point:${JSON.stringify(point)},at:Date.now(),data}),{mode:0o600});renameSync(path+".tmp",path);Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,60000);throw new Error("Continuation cut supervisor did not stop process");}`);
  let changed='import {hit as continueCut} from "../contracts/continue-cut.ts";\n'+original;
  const insert=(needle:string,text:string)=>{if(changed.split(needle).length!==2)throw new Error(`Continuation ${point} boundary moved`);changed=changed.replace(needle,text+needle);};
  if(point==="C0")insert('      this.store.transaction(()=>{this.store.prepare(this.owner, id, canary ?', '      continueCut({id,record:this.state()});\n');
  else if(point==="C1")insert('    this.ticking = true;','    continueCut({id,record:this.store.get("recovery",this.scopeId)});\n');
  else if(point==="C3")insert('      this.store.acknowledge(id, ack.nativeId);','      continueCut({id,nativeId:ack.nativeId,record:this.state()});\n');
  else if(point==="C4")insert('      this.store.settle(this.record.intentId, snapshot.terminationKnown ?', '      continueCut({id:this.record.intentId,completed,record:this.state()});\n');
  else if(point==="C5")insert('      if (!snapshot.terminationKnown) { this.block("termination_unknown"); return; }','      continueCut({id:this.record.intentId,completed,record:this.store.get("recovery",this.scopeId)});\n');
  else if(point==="C2"){
    const adapter=join(copy,"src/adapters/pi-interactive.ts"),text=readFileSync(adapter,"utf8"),needle='if (matches.length === 1) { cleanup(); resolveAck({ nativeId: matches[0].id }); }';
    if(text.split(needle).length!==2)throw new Error("Native continuation ACK point moved");writeFileSync(adapter,text.replace(needle,'if (matches.length === 1) { return; }'));
  }else throw new Error("Unsupported continuation cut");
  writeFileSync(path,changed);const hash=(value:string)=>createHash("sha256").update(value).digest("hex");writeFileSync(join(root,"continue-cut-manifest.json"),JSON.stringify({point,sourceHash:hash(original),instrumentedHash:hash(changed),C2:"only ACK delivery suppressed; receiver holds actual request"}));return copy;
}
