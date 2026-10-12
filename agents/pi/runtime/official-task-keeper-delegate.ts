// 自有TaskService的现代适配：SQL只保业务阶段与core引用，不allocate/dispatch物理进程。
import { realpathSync } from "node:fs";
import { captureOperationInput } from "./private-operation-input.ts";
import { digest } from "./managed-types.ts";
const fail = code => { throw new Error(code); };
export class TaskKeeperDelegateAdapter {
  constructor({ store, owner, config, manifest, installed, supervisor, issuer, policySnapshot, runtimeContract, semanticContext, pause = ms => new Promise(done => setTimeout(done, ms)) }) {
    if (!store || typeof store.assertOwner !== "function" || typeof store.transaction !== "function"
        || typeof runtimeContract !== "function" || typeof issuer?.open !== "function" || typeof issuer?.retire !== "function" || typeof supervisor?.call !== "function"
        || manifest.profile_id !== "pi-full" || !manifest.options?.task_keeper?.enabled) fail("DELEGATE_TASK_SCOPE_UNAVAILABLE");
    this.store = store; this.owner = structuredClone(owner); this.config = config; this.manifest = structuredClone(manifest);
    this.supervisor = supervisor; this.issuer = issuer; this.policySnapshot = policySnapshot; this.pause = pause;
    this.contract = runtimeContract; this.installed=structuredClone(installed); this.semanticProducer=semanticContext;
    this.sources = new Map(); this.retired = false;
  }
  async semanticContext() {
    this.check();if(typeof this.semanticProducer!=="function")fail("INPUT_SNAPSHOT_CONTEXT_REQUIRED");
    const envelope=captureOperationInput(await this.semanticProducer()).value;
    if(!envelope||Object.keys(envelope).sort().join()!=="configuration,models"||!Array.isArray(envelope.models))fail("INPUT_SNAPSHOT_CONTEXT_INVALID");
    const current=envelope.configuration;this.check();const contract=this.runtimeContract();
    const fields=["configIdentity","runtimeIdentity","effectiveConfigDigest","policyDigest","projectConstraintsDigest","resourcesDigest","model","thinking"];
    if(!current||Object.keys(current).sort().join()!==fields.sort().join()||current.runtimeIdentity!==contract.runtime_identity)fail("INPUT_SNAPSHOT_CONTEXT_INVALID");
    const sha=v=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v);
    for(const key of ["configIdentity","effectiveConfigDigest","policyDigest","projectConstraintsDigest","resourcesDigest"])if(!sha(current[key]))fail("INPUT_SNAPSHOT_CONTEXT_INVALID");
    const routes=[];
    for(const [role,binding] of Object.entries(this.manifest.model_bindings??{}).sort(([a],[b])=>Buffer.compare(Buffer.from(a),Buffer.from(b)))){
      const provider=this.manifest.model_configuration?.providers?.[binding.provider];
      if(!provider||!["api-key","oauth"].includes(provider.auth_kind)||typeof provider.owner!=="string")fail("INPUT_SNAPSHOT_PROVIDER_INVALID");
      // 原已验证manifest只投影公开配置；原始SDK headers/认证正文不进入此路径。
      const selected=envelope.models.filter(v=>v.role_id===role);
      if(selected.length!==1||Object.keys(selected[0]).sort().join()!=="description,model_id,provider_id,role_id"||selected[0].provider_id!==binding.provider||selected[0].model_id!==binding.model)fail("INPUT_SNAPSHOT_MODEL_METADATA_UNAVAILABLE");
      const publicConfig=selected[0].description;
      const safeFields=["id","provider","api","name","baseUrl","reasoning","input","cost","contextWindow","maxTokens","thinkingLevelMap","compat","promptCache","inputLimits","samplingParams","samplingParamsByThinkingLevel"];
      if(!publicConfig||Object.keys(publicConfig).some(key=>!safeFields.includes(key))||Object.hasOwn(publicConfig,"headers")||Object.hasOwn(publicConfig,"type")||publicConfig.id!==binding.model||publicConfig.provider!==binding.provider)fail("INPUT_SNAPSHOT_PROVIDER_INVALID");
      if(publicConfig.baseUrl){const url=new URL(publicConfig.baseUrl);if(url.username||url.password||url.search||url.hash)fail("INPUT_SNAPSHOT_PROVIDER_INVALID");}

      routes.push({role_id:role,provider_id:binding.provider,model_id:binding.model,public_configuration_digest:digest(publicConfig),auth:{kind:provider.auth_kind,owner:provider.owner,credential_ref:provider.credential_ref??null}});
    }
    if(envelope.models.length!==routes.length)fail("INPUT_SNAPSHOT_CONTEXT_INVALID");
    const installed=this.installed;if(!installed||installed.runtime_identity!==contract.runtime_identity||process.version!==installed.toolchains.node)fail("INPUT_SNAPSHOT_CONTEXT_INVALID");
    return {config_identity:current.configIdentity,effective_config_digest:current.effectiveConfigDigest,host_manifest_identity:contract.config_identity,policy_digest:current.policyDigest,
      project_constraints_digest:current.projectConstraintsDigest,resources_digest:current.resourcesDigest,runtime_identity:contract.runtime_identity,lock_identity:contract.lock_identity,slice_identity:contract.slice_identity,
      capability_provider_digest:digest(contract.provider_projection),model_routes:routes,environment:{platform:process.platform,architecture:process.arch,node_version:process.version,sdk_version:installed.sdk_version,declared_nonsecret_variables:[{name:"LANG",value:"C.UTF-8"}]}};
  }
  runtimeContract() { this.check(); return this.contract(); }
  check() {
    if (this.retired) fail("DELEGATE_TASK_SOURCE_RETIRED");
    this.store.assertOwner(this.owner); this.policySnapshot();
  }
  capture(input) {
    this.check();
    return this.store.transaction(() => {
      this.check();
      const job = this.store.get("managed-jobs", input.jobId), scheduled = this.store.get("jobs", input.jobId);
      const step = scheduled?.steps?.find(row => row.id === input.stepId);
      if (!job || job.workScope !== this.owner.scopeId || scheduled.spec?.workScope !== this.owner.scopeId
          || !step || step.intentId !== input.parentIntentId || step.status !== "running" || job.cancelRequested
          || job.controlEpoch !== scheduled.spec.controlEpoch && scheduled.spec.controlEpoch !== undefined
          || job.policyDigest !== this.config.policyDigest && this.config.policyDigest !== undefined
          || realpathSync(input.cwd) !== realpathSync(job.cwd)) fail("DELEGATE_TASK_SCOPE_STALE");
      if (input.role === "worker" || step.kind === "write") fail("DELEGATE_TASK_WRITE_UNAVAILABLE");
      const route = this.config.routes[input.routeId ?? this.config.roles[input.role]?.route];
      const role = input.role === "reviewer" ? "task_keeper_reviewer" : "task_keeper_reader";
      const binding = this.manifest.model_bindings?.[role];
      if (!route || !binding || route.provider !== binding.provider || route.model !== binding.model) fail("DELEGATE_TASK_ROLE_UNAVAILABLE");
      return { task_id: job.id, step_id: step.id, store_owner: structuredClone(this.owner), cwd: realpathSync(job.cwd),
        source_cwd: realpathSync(job.sourceCwd), role: input.role, model: { provider_id: binding.provider, model_id: binding.model },
        policy_digest: digest(this.manifest.permission_policy) };
    });
  }
  async source(input, facts) {
    const key = digest([facts.task_id, facts.step_id]);
    if (this.sources.has(key)) return this.sources.get(key);
    const ref = await this.issuer.open(facts);
    try { this.check(); this.capture(input); }
    catch (error) { await this.issuer.retire(ref); throw error; }
    this.sources.set(key, ref); return ref;
  }
  async preflightReview({ model }) {
    this.check();
    const selected = this.manifest.model_bindings?.task_keeper_reviewer;
    if (!selected || model !== selected.provider + "/" + selected.model) fail("DELEGATE_TASK_ROLE_UNAVAILABLE");
    return { role_id: "task-keeper-reviewer", model: selected };
  }
  async execute(input, _ctx, signal, onDispatch) {
    const facts = this.capture(input), key = digest([input.jobId, input.stepId, input.parentIntentId]);
    const prior = this.store.get("delegate-core-links-v3", key);
    if (prior) return this.observe(prior, this.sources.get(digest([facts.task_id, facts.step_id])));
    const startedAt=Date.now(),evidenceOrigin=input.evidenceOrigin?captureOperationInput(input.evidenceOrigin).value:null;
    if(evidenceOrigin){const job=this.store.get("managed-jobs",input.jobId),spec=this.store.get("jobs",input.jobId)?.spec;
      if(evidenceOrigin.specVersion!==spec?.version||evidenceOrigin.policyDigest!==spec?.policyDigest
          ||evidenceOrigin.inputSnapshotDigest!==job?.inputSnapshotDigest)fail("DELEGATE_EVIDENCE_ORIGIN_CHANGED");}
    if (signal?.aborted) fail("DELEGATE_TASK_CANCELED");
    const source = await this.source(input, facts);
    this.check(); this.capture(input);
    const requestId = "tk-" + key;
    const link = { request_id: requestId, logical_run_id: null, physical_attempt_id: null, receipt_ref: null };
    this.store.transaction(() => { this.check(); this.store.put("delegate-core-links-v3", key, link); });
    // 这里只通知业务phase；原core在物理prepare之前持久sending+预算。
    onDispatch?.();
    let result;
    try {
      result = await this.supervisor.call("delegate_action_v3", { source_ref: source, action: {
        schema_version: 3, action: "submit", request_id: requestId, backend: "pi", mode: input.role === "reviewer" ? "review" : "investigate",
        preset: input.role === "reviewer" ? "review" : "general", task: input.task, model: facts.model, cwd: facts.cwd,
        timeout_seconds: this.manifest.options.model_delegate.max_run_seconds, allow_workspace_write: false, worktree_root: null } });
    } catch {
      // 同一request只读定位，不补发、不退款；找不到仍保持不完整关联。
      try { result = await this.supervisor.call("delegate_lookup_v3", { source_ref: source, request_id: requestId }); } catch {}
      if (!result) return this.unknown();
    }
    link.logical_run_id = result.run_id;
    this.store.transaction(() => { this.check(); this.store.put("delegate-core-links-v3", key, link); });
    const deadline = result.budget?.deadline_ms;
    if (!Number.isSafeInteger(deadline)) return this.unknown();
    let cancelSent = false;
    while (Date.now() <= deadline + 5000) {
      this.check();
      if (signal?.aborted && !cancelSent) {
        cancelSent = true;
        await this.supervisor.call("delegate_action_v3", { source_ref: source,
          action: { schema_version: 3, action: "cancel", request_id: requestId + "-cancel", run_id: link.logical_run_id } });
      }
      result = await this.supervisor.call("delegate_status_v3", { source_ref: source, run_id: link.logical_run_id });
      const active = result.actions.find(row => row.attempt_id === result.active_attempt_id && row.physical_run_id);
      if (active) { link.physical_attempt_id = active.attempt_id; link.receipt_ref = active.receipt_ref; }
      this.store.transaction(() => { this.check(); this.store.put("delegate-core-links-v3", key, link); });
      if (active?.termination_verified) return this.result(result, active, source,evidenceOrigin,startedAt,link.logical_run_id);
      if (result.status === "unknown") return this.unknown();
      await this.pause(100);
    }
    return this.unknown();
  }
  unknown() { return { descriptorId: "unassociated", nativeRunId: null, status: "unknown", terminationConfirmed: false,
    content: null, error: "DELEGATE_EXECUTION_UNKNOWN", observations: [] }; }
  async observe(link, source) {
    this.check();
    if (!link.logical_run_id || !source) return this.unknown();
    const result = await this.supervisor.call("delegate_status_v3", { source_ref: source, run_id: link.logical_run_id });
    const active = result.actions.find(row => row.attempt_id === result.active_attempt_id && row.physical_run_id);
    return active?.termination_verified ? this.result(result, active, source,null,null,link.logical_run_id) : this.unknown();
  }
  async result(result, active, source,evidenceOrigin=null,startedAt=null,logicalRunId=result.run_id) {
    if(result.run_id!==logicalRunId||active.physical_run_id!==active.receipt_ref)return this.unknown();
    let evidence=null;
    if(active.execution_evidence){
      try{const value=captureOperationInput(active.execution_evidence).value;
        const fields=["schema_version","physical_run_id","attempt_id","lease_id","grant_generation","process_identity_digest","termination_evidence_digest","terminated","resources_reclaimed","exit_code"];
        if(Object.keys(value).sort().join()!==fields.sort().join()||value.schema_version!==1
            ||value.physical_run_id!==active.physical_run_id||value.attempt_id!==active.attempt_id||value.lease_id!==active.lease_id
            ||!Number.isSafeInteger(value.grant_generation)||value.grant_generation<1||value.terminated!==true||value.resources_reclaimed!==true
            ||![value.process_identity_digest,value.termination_evidence_digest].every(v=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v))
            ||value.exit_code!==null&&!Number.isSafeInteger(value.exit_code))fail("DELEGATE_EVIDENCE_INVALID");
        evidence=value;
      }catch{evidence=null;}
    }
    let text = "", offset = 0;
    if (active.task_succeeded) {
      while (offset < 65536) {
        const chunk = await this.supervisor.call("delegate_artifact_v3", { source_ref: source, run_id: result.run_id, offset, limit: 2048 });
        this.check();
        if (typeof chunk.content !== "string" || chunk.offset !== offset || chunk.total_bytes > 65536) fail("DELEGATE_RESULT_INVALID");
        text += chunk.content;
        if (chunk.next_offset === null) break;
        if (!Number.isSafeInteger(chunk.next_offset) || chunk.next_offset <= offset) fail("DELEGATE_RESULT_INVALID");
        offset = chunk.next_offset;
      }
    }
    return { descriptorId: active.attempt_id, nativeRunId: active.physical_run_id,
      status: active.task_succeeded ? "ended" : "failed", terminationConfirmed: true,
      content: text, error: active.task_succeeded ? null : "DELEGATE_TASK_FAILED", observations: [],evidenceOrigin,evidence,
      invocationWindow:startedAt===null?null:{startedAt,endedAt:Date.now()} };
  }
  async reconcileStep(jobId, stepId, parentIntentId) {
    this.check();
    const link = this.store.get("delegate-core-links-v3", digest([jobId, stepId, parentIntentId]));
    const source = this.sources.get(digest([jobId, stepId]));
    // 旧opaque来源已退休/进程重启时只保持保护，不能注册新来源或补发。
    if (!link?.logical_run_id || !source) return { stopped: false, neverStarted: false };
    const result = await this.supervisor.call("delegate_status_v3", { source_ref: source, run_id: link.logical_run_id });
    this.check();
    if (result.run_id !== link.logical_run_id || !Array.isArray(result.actions)) fail("DELEGATE_TASK_ASSOCIATION_INVALID");
    const active = result.actions.find(row => row.attempt_id === result.active_attempt_id && row.physical_run_id);
    if (!active || link.physical_attempt_id !== null && active.attempt_id !== link.physical_attempt_id
        || link.receipt_ref !== null && active.receipt_ref !== link.receipt_ref) return { stopped: false, neverStarted: false };
    if (active.termination_verified !== true || typeof active.receipt_ref !== "string") return { stopped: false, neverStarted: false };
    // Server的termination_verified来自原v2完整receipt验证与resources_reclaimed，非Task状态。
    this.store.transaction(() => {
      this.check();
      this.store.put("delegate-core-links-v3", digest([jobId, stepId, parentIntentId]),
        { ...link, physical_attempt_id: active.attempt_id, receipt_ref: active.receipt_ref });
    });
    return { stopped: true, neverStarted: false };
  }
  async reconcile() { this.check(); return { protected: true, termination_evidence: { verified: false } }; }
  async close() {
    this.retired = true;
    await Promise.allSettled([...this.sources.values()].map(ref => this.issuer.retire(ref)));
    this.sources.clear();
  }
}
