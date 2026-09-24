import { cpSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join, relative } from "node:path";
import { createHash } from "node:crypto";

/** Replay request facts inside the actual child transport callbacks in a private copy. */
export function settlementReplay(source: string, root: string) {
  const copy=join(root,"settlement-runtime");
  cpSync(source,copy,{recursive:true,filter:path=>!relative(source,path).split("/").some(part=>["node_modules","test-results","coverage",".git"].includes(part))});
  symlinkSync(join(source,"node_modules"),join(copy,"node_modules"));
  const path=join(copy,"src/adapters/child-reporter.ts"),original=readFileSync(path,"utf8");
  const reserve='store!.reserveRequest(descriptor!.owner, leaseId, attempt.id, descriptor!.budgetLimits);';
  const terminal='if (descriptor!.protected) store!.settleRequest(attempt.id, "sent");';
  if(original.split(reserve).length!==2||original.split(terminal).length!==2)throw new Error("Request settlement boundary changed");
  const snapshot='descriptor!.budgetLimits.map(limit=>store!.bucket(limit.id))';
  const append=(phase:string)=>`replayAppend(${JSON.stringify(join(root,"settlement-observer.jsonl"))},JSON.stringify({phase:${JSON.stringify(phase)},requestId:attempt.id,before,after:${snapshot}})+"\\n");`;
  const modified='import {appendFileSync as replayAppend} from "node:fs";\n'+original.replace(reserve,reserve+`
            { const before=${snapshot};store!.settleRequest(attempt.id,"unknown");store!.settleRequest(attempt.id,"unknown");${append("unknown-duplicate")} }
          `).replace(terminal,terminal+`
        if(descriptor!.protected){const before=${snapshot};store!.settleRequest(attempt.id,"sent");store!.settleRequest(attempt.id,"sent");${append("sent-duplicate")} }
      `);
  writeFileSync(path,modified);
  const hash=(s:string)=>createHash("sha256").update(s).digest("hex");
  writeFileSync(join(root,"settlement-fault-manifest.json"),JSON.stringify({original:hash(original),instrumented:hash(modified),path}));
  return copy;
}
