import {cpSync,readFileSync,writeFileSync,symlinkSync} from "node:fs";
import {join,relative} from "node:path";
import {createHash} from "node:crypto";
/** Test-only cuts in the actual dispatcher. No production fault switches are installed. */
export function nativeDispatchCut(source:string,root:string,family:"start"|"verify",point:string){
  const copy=join(root,"native-cut-runtime");cpSync(source,copy,{recursive:true,filter:path=>!relative(source,path).split("/").some(part=>["node_modules","test-results","coverage",".git"].includes(part))});symlinkSync(join(source,"node_modules"),join(copy,"node_modules"));
  const path=join(copy,"src/orchestration/service.ts"),original=readFileSync(path,"utf8"),target=family==="start"?"implement":"baseline:build";
  const marker=join(root,"native-cut.json");
  writeFileSync(join(copy,"src/contracts/native-cut.ts"),`import {writeFileSync,renameSync,existsSync} from "node:fs";
export function hit(data:unknown){const path=${JSON.stringify(marker)};if(existsSync(path))return;writeFileSync(path+".tmp",JSON.stringify({family:${JSON.stringify(family)},point:${JSON.stringify(point)},at:Date.now(),data}),{mode:0o600});renameSync(path+".tmp",path);Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,60000);throw new Error("Native cut supervisor did not stop the process");}
`);
  let changed='import {hit as nativeCut} from "../contracts/native-cut.ts";\n'+original;
  const insert=(needle:string,text:string)=>{if(changed.split(needle).length!==2)throw new Error(`Native ${family}.${point} boundary changed`);changed=changed.replace(needle,text+needle);};
  if(point==="C0")insert('        intent = this.scheduler.dispatch(',`        if(next.stepId===${JSON.stringify(target)})nativeCut({jobId:job.id,snapshot:job.snapshot});\n`);
  else if(point==="C1")insert('      const controller = new AbortController();\n      const promise = this.runStep',`      if(next.stepId===${JSON.stringify(target)})nativeCut({jobId:job.id,intentId:intent.id});\n`);
  else if(point==="C3")insert(family==="start"?'        if(!reusedReview && !result.notSent && result.nativeRunId)':'        if(!verification.notSent && verification.supervisor.namespaceInit)',family==="start"?`        if(stepId===${JSON.stringify(target)})nativeCut({jobId,intentId:intent.id,nativeId:result.nativeRunId,terminated:result.terminationConfirmed});\n`:`        if(stepId===${JSON.stringify(target)})nativeCut({jobId,intentId:intent.id,supervisor:verification.supervisor,terminated:verification.terminationConfirmed});\n`);
  else if(point==="C4")insert('      this.scheduler.finish(jobId, stepId, { terminated, passed: passed && !revoked',`      if(stepId===${JSON.stringify(target)})nativeCut({jobId,intentId:intent.id,terminated,nativeId:this.store.intent(intent.id)?.nativeId});\n`);
  else if(point==="C5")insert('      this.save(job);\n      if (revoked) return;',`      if(stepId===${JSON.stringify(target)})nativeCut({jobId,intentId:intent.id,terminated,nativeId:this.store.intent(intent.id)?.nativeId,snapshot:job.snapshot});\n`);
  else if(point!=="C2")throw new Error("Unsupported native cut");
  writeFileSync(path,changed);const hash=(value:string)=>createHash("sha256").update(value).digest("hex");
  writeFileSync(join(root,"native-cut-manifest.json"),JSON.stringify({family,point,target,sourceHash:hash(original),instrumentedHash:hash(changed),C2:"actual receiver/file effect held before terminal ACK"}));return copy;
}
