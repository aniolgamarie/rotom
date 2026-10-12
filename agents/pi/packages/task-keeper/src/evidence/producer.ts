import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { digest } from "../contracts/primitives.ts";
import { compileInputSnapshot } from "./context.ts";
import { createEvidenceRecord, reduceEvidence, evidenceReasonCodes, type EvidenceOrigin, type EvidenceRecord,
  type EvidenceView, type VerifiedArtifactFact, type CurrentEvidenceContext } from "./records.ts";
import { evaluateVerification, type VerificationResult } from "../verification/runner.ts";
import { verifierSupervisor } from "../verification/supervisor.ts";
import type { VerificationBinding } from "../config.ts";
import type { Artifact, Artifacts } from "../store/artifacts.ts";
import type { DelegationResult } from "../adapters/delegate-contract.ts";
import { strictJson } from "@agentcfg/pi-runtime/strict-json";

export interface EvidencePointer {
  stepId: string; attemptId: string; checkId: string; layer: EvidenceRecord["layer"];
  recordRef: string; snapshot: string; rawArtifactId: string; observedAt: number;
}
const sha=(bytes:Buffer|string)=>createHash("sha256").update(bytes).digest("hex");
export function evidenceReason(value:unknown):EvidenceRecord["result"]["reason"] {
  return evidenceReasonCodes.includes(value as never)?value as EvidenceRecord["result"]["reason"]:"execution_unknown";
}
function origin(snapshot:any,version:number,policyDigest:string,entry:any):EvidenceOrigin|null {
  if(!snapshot)return null;
  const verified=compileInputSnapshot(snapshot.source,snapshot.identities);
  if(verified.digest!==snapshot.digest)throw Error("INPUT_SNAPSHOT_ORIGIN_INVALID");
  const runtime=(globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if(runtime?.installed?.runtime_identity!==snapshot.identities.runtime_identity)return null;
  return {profileId:runtime.installed.profile_id,runtimeIdentity:snapshot.identities.runtime_identity,
    configDigest:snapshot.identities.config_identity,platform:snapshot.identities.environment.platform,
    architecture:snapshot.identities.environment.architecture,snapshot:entry.snapshot,inputSnapshotDigest:snapshot.digest,
    specVersion:version,policyDigest,bindingDigest:entry.bindingDigest,environmentDigest:digest(snapshot.identities.environment),
    contractDigest:entry.contractDigest,cwdIdentity:snapshot.source.workspace_identity,
    entryIdentity:entry.entryIdentity,argvDigest:entry.argvDigest};
}
export function checkerEvidenceOrigin(snapshot:any,version:number,policyDigest:string,binding:VerificationBinding,
  checkId:string,cwd:string,sourceSnapshot:string,contractDigest:string):EvidenceOrigin|null {
  if(!snapshot)return null;
  const helper=verifierSupervisor(binding,cwd);
  return origin(snapshot,version,policyDigest,{snapshot:sourceSnapshot,bindingDigest:digest(binding),contractDigest,
    entryIdentity:digest({kind:"original-check-helper",helper:helper.hash,implementation:contractDigest}),
    argvDigest:digest({executable:binding.executable,args:binding.args,helper:helper.hash,checkId})});
}
export function delegateEvidenceOrigin(snapshot:any,version:number,policyDigest:string,role:string,route:any,profile:any,
  sourceSnapshot:string):EvidenceOrigin|null {
  if(!snapshot)return null;
  const runtime=(globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  const helperHash=sha(readFileSync(join(runtime.runtimeRoot,"runtime/official-task-keeper-delegate.mjs")));
  // 只取冻结公开验收绑定，不摘要prompt、headers、credential或descriptor nonce。
  const binding={role,provider:route.provider,model:route.model,thinking:profile.thinking,tools:profile.tools,
    timeoutMs:profile.timeoutMs,maxModelTurns:profile.maxModelTurns,toolTimeoutMs:profile.toolTimeoutMs};
  return origin(snapshot,version,policyDigest,{snapshot:sourceSnapshot,bindingDigest:digest(binding),
    contractDigest:digest({roleBinding:binding,checkerContracts:snapshot.identities.checker_contracts}),
    entryIdentity:digest({kind:"original-delegate-adapter",helper:helperHash,runtime:snapshot.identities.runtime_identity}),
    argvDigest:digest({kind:"fixed-delegate-invocation",binding,helper:helperHash})});
}
const artifactRef=(artifact:Artifact)=>({id:artifact.id,source:artifact.source,digest:artifact.contentDigest,bytes:artifact.bytes});
function unknowns(execution:any,countsRequired=false):EvidenceRecord["execution"]["unknowns"] {
  const values:any[]=[];
  if(execution.notSent)return values;
  if(execution.processIdentity===null)values.push("PROCESS_IDENTITY_UNOBSERVED");
  if(execution.startedAt===null)values.push("START_TIME_UNKNOWN");
  if(execution.endedAt===null)values.push("END_TIME_UNKNOWN");
  if(execution.termination==="unknown")values.push("TERMINATION_UNKNOWN");
  if(execution.terminalObserved!==true)values.push("TERMINAL_UNOBSERVED");
  if(execution.exitCode===null)values.push("EXIT_CODE_UNKNOWN");
  if(countsRequired&&execution.counts===null)values.push("TEST_COUNTS_UNKNOWN");
  return values;
}
export function checkerEvidenceRecord(result:VerificationResult,attemptId:string,artifact:Artifact):unknown {
  const facts=result.executionFacts,process=result.supervisor?.namespaceInit;
  const matched=process&&Number.isSafeInteger(process.pid)&&process.pid>0&&typeof process.bootId==="string"
    &&typeof process.startTicks==="string"&&process.executionLeaseId===result.supervisor.executionLeaseId;
  const notSent=result.notSent===true;
  const execution={startedAt:notSent?null:result.invocationWindow?.startedAt??null,
    endedAt:notSent?null:result.invocationWindow?.endedAt??null,
    protocolStatus:notSent?"not_sent":facts?.timedOut?"timed_out":facts?.cancelled?"cancelled":
      result.status==="failed"?"failed":result.terminationConfirmed?"completed":"unknown",
    exitCode:notSent?null:result.exitCode,counts:notSent?null:result.counts,
    terminalObserved:notSent?false:facts?.terminalObserved??null,
    termination:result.terminationConfirmed?"confirmed":"unknown",processIdentity:notSent?null:matched?digest(process):null,
    notSent,unknowns:[] as any[]};
  execution.unknowns=unknowns(execution,result.acceptanceBinding?.kind==="tests");
  if(result.truncated)execution.unknowns.push("OUTPUT_TRUNCATED");
  const status=notSent?"not_run":result.status==="failed"?"failed":execution.unknowns.length?"unknown":result.status;
  return {schemaVersion:1,jobId:result.jobId,attemptId,checkId:result.checkId,layer:"checker",origin:result.evidenceOrigin??null,
    execution,result:{status,reason:notSent?"not_sent":status==="unknown"&&result.status==="passed"?"execution_unknown":evidenceReason(result.reason)},
    artifact:artifactRef(artifact)};
}
export function delegationEvidenceRecord(result:DelegationResult,jobId:string,checkId:string,attemptId:string,
  artifact:Artifact,layer:EvidenceRecord["layer"],review?:{passed:boolean;status:string}):unknown {
  const proof=result.evidence,matched=proof?.schema_version===1&&proof.attempt_id===result.descriptorId
    &&proof.physical_run_id===result.nativeRunId&&proof.terminated===true&&proof.resources_reclaimed===true;
  const notSent=result.notSent===true;
  const execution={startedAt:notSent?null:result.invocationWindow?.startedAt??null,endedAt:notSent?null:result.invocationWindow?.endedAt??null,
    protocolStatus:notSent?"not_sent":result.status==="ended"?"completed":result.status==="failed"?"failed":"unknown",
    exitCode:notSent?null:matched?proof.exit_code:null,counts:null,terminalObserved:notSent?false:matched?true:null,
    termination:result.terminationConfirmed?"confirmed":"unknown",processIdentity:notSent?null:matched?proof.process_identity_digest:null,
    notSent,unknowns:[] as any[]};
  execution.unknowns=unknowns(execution);
  const failed=result.status==="failed"||review?.status==="failed";
  const status=notSent?"not_run":failed?"failed":execution.unknowns.length||review?.status==="unknown"?"unknown":"passed";
  return {schemaVersion:1,jobId,checkId,attemptId,layer,origin:result.evidenceOrigin??null,execution,
    result:{status,reason:notSent?"not_sent":status==="failed"?"oracle_failed":status==="unknown"?"execution_unknown":"oracle_passed"},
    artifact:artifactRef(artifact)};
}
export function readEvidenceView(artifacts:Artifacts,pointer:EvidencePointer,jobId:string,current:CurrentEvidenceContext,
  oracle:(content:Buffer)=>boolean):EvidenceView {
  let record:unknown=null,fact:VerifiedArtifactFact|null=null,oraclePassed=false;
  try {
    const stored=artifacts.read(pointer.recordRef,jobId,pointer.snapshot);
    if(stored.artifact.source!=="runtime")throw Error("RECORD_ARTIFACT_SOURCE");
    record=strictJson(stored.content.toString());
    const closed=createEvidenceRecord(record);
    if(closed.jobId!==jobId||closed.attemptId!==pointer.attemptId||closed.checkId!==pointer.checkId
      ||closed.layer!==pointer.layer||closed.artifact?.id!==pointer.rawArtifactId)throw Error("RECORD_SCOPE");
    const raw=artifacts.read(pointer.rawArtifactId,jobId,pointer.snapshot);
    fact={readable:true,id:raw.artifact.id,jobId:raw.artifact.jobId,snapshot:raw.artifact.snapshot,
      source:raw.artifact.source as any,digest:raw.artifact.contentDigest,bytes:raw.artifact.bytes};
    oraclePassed=oracle(raw.content);
  }catch{
    // 读取/指针资格失败与合法无工件 not-sent 不同；保留已解析事实，禁止降为 current。
    const reduced=reduceEvidence(record,{...current,oraclePassed:false},null);
    return Object.freeze({...reduced,validity:"invalid",supportsPassed:false,
      reasons:Object.freeze(["artifact_read_invalid"])});
  }
  return reduceEvidence(record,{...current,oraclePassed},fact);
}
export function checkerOracle(content:Buffer):boolean {
  try {const result=JSON.parse(content.toString()) as VerificationResult;
    if(!result.executionFacts||!result.acceptanceBinding)return false;
    const evaluated=evaluateVerification(result.acceptanceBinding,result.executionFacts);
    return !result.notSent&&evaluated.status==="passed";
  }catch{return false;}
}
