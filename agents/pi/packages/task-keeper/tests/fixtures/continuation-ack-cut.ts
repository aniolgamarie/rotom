import { cpSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join, relative } from "node:path";
import { createHash } from "node:crypto";

/** Suppress ACK delivery only. Native enqueue, requests, tools, durable entries and reconciliation remain real. */
export function continuationAckCut(source: string, root: string) {
  const copy = join(root, "ack-runtime");
  cpSync(source, copy, {recursive:true,filter:path => !relative(source,path).split("/").some(part => ["node_modules","test-results","coverage",".git"].includes(part))});
  symlinkSync(join(source,"node_modules"),join(copy,"node_modules"));
  const path = join(copy,"src/adapters/pi-interactive.ts"), original = readFileSync(path,"utf8");
  const target = 'if (matches.length === 1) { cleanup(); resolveAck({ nativeId: matches[0].id }); }';
  if (original.split(target).length !== 2) throw new Error("Continuation ACK boundary changed");
  const changed = 'import { appendFileSync as ackCutAppend } from "node:fs";\n' + original.replace(target,
    `if (matches.length === 1) { ackCutAppend(${JSON.stringify(join(root,"ack-observations.jsonl"))},JSON.stringify({intent,nativeId:matches[0].id,at:Date.now(),ackDelivered:false})+"\\n"); return; }`);
  writeFileSync(path,changed);
  const hash = (text: string) => createHash("sha256").update(text).digest("hex");
  writeFileSync(join(root,"ack-cut-manifest.json"),JSON.stringify({source:hash(original),instrumented:hash(changed),changed:"ACK delivery suppressed",nativeEffects:"unchanged",terminalReconciliation:"unchanged"}));
  return copy;
}
