// 原SupervisorClient与原launch连接真实Python authority；没有FakeSupervisor。
import fs from "node:fs";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";
const hash = value => createHash("sha256").update(value).digest("hex");
export const syntheticCredentialReference = () => "$AGENTCFG_PI_CREDENTIAL_" + hash("synthetic").slice(0,16).toUpperCase();
async function guestManager() {
const sourcePlan=JSON.parse(fs.readFileSync("/probe/source-plan.json"));
const {verifyCandidateInventory}=await import("/probe/candidate-inventory.mjs");
const receipt=sourcePlan.candidate_inventory;
verifyCandidateInventory({candidateRoot:"/candidate",receiptPath:"/probe/"+receipt.fixture,receiptSha256:receipt.sha256,receiptRootName:receipt.receipt_root_name});
for(const row of sourcePlan.source_inventory){const bytes=fs.readFileSync("/source/"+row.path);assert.equal(bytes.length,row.bytes);assert.equal(hash(bytes),row.sha256);}
const sdk = await import("@earendil-works/pi-coding-agent"), ai = await import("@earendil-works/pi-ai");
const own = name => import(pathToFileURL("/source/agents/pi/runtime/" + name + ".ts").href);
const { launch } = await own("official-launch"), { createOfficialFileRuntime } = await own("official-file-runtime");
const { createOfficialModels } = await own("official-models"), { createOfficialModelScope } = await own("official-model-scope"), { SupervisorClient } = await own("supervisor-client");
const budget = { sender: 0 }; const LIMITS = { sender_calls: 12 }; let phase;
const result = { actual_python_control: true, formal_deployment: false, events: [] };
try {
    const root = "/work", cwd = "/work/project", instanceRoot = "/work/instance", stateRoot = "/work/state";
    for (const dir of [cwd, instanceRoot + "/pi-home", stateRoot, root + "/sessions"]) fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    for (const name of ["AGENTS.md", "APPEND_SYSTEM.md"]) fs.writeFileSync(instanceRoot + "/pi-home/" + name, "Own synthetic Base component probe\n", { mode: 0o600 });
    phase = "synthetic-provider";
    const faux = ai.fauxProvider({ provider: "synthetic-base", api: "synthetic-base", models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] });
    const model = { ...faux.getModel(), baseUrl: "https://synthetic.invalid/unused" };
    const provider = ai.createProvider({ id: model.provider, models: [model], auth: { apiKey: { name: "synthetic", check: async () => ({ type: "api_key" }), resolve: async () => ({ auth: { apiKey: "synthetic" } }) } },
      api: { stream: (...args) => { if (++budget.sender > LIMITS.sender_calls) throw Error("AUTHORITY_SENDER_LIMIT"); return faux.provider.stream(...args); }, streamSimple: (...args) => { if (++budget.sender > LIMITS.sender_calls) throw Error("AUTHORITY_SENDER_LIMIT"); return faux.provider.streamSimple(...args); } } });
    const raw = await sdk.ModelRuntime.create({ credentials: new ai.InMemoryCredentialStore(), modelsStore: new ai.InMemoryModelsStore(), modelsPath: null, allowModelNetwork: false, refreshOnCreate: false }); raw.registerNativeProvider(provider);
    await raw.refresh({ providers: [model.provider], allowNetwork: false });
    const config = { api: model.api, baseUrl: model.baseUrl, models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] }, binding = { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" };

 const manifest = JSON.parse(fs.readFileSync("/probe/manifest.json")), installed = JSON.parse(fs.readFileSync("/probe/installed.json"));
 const modelPath = instanceRoot + "/pi-home/models.json"; fs.writeFileSync(modelPath, JSON.stringify({providers:{[model.provider]:{...config,apiKey:syntheticCredentialReference()}}}),{mode:0o600});
 const models = createOfficialModels({manifest,path:modelPath,modelRuntime:raw}), scope = createOfficialModelScope({modelRuntime:raw,manifest,describe:models.describe});
 const transportOptions = {python:process.env.AGENTCFG_PYTHON,client:process.env.AGENTCFG_SUPERVISOR_CLIENT,endpoint:process.env.AGENTCFG_SUPERVISOR_ENDPOINT,capability:process.env.AGENTCFG_SUPERVISOR_CAPABILITY};
 const originalClient = new SupervisorClient(transportOptions), originalInvoke=originalClient.invoke; result.control_frames=[];
 const supervisor=new SupervisorClient({...transportOptions,invoke:async options=>{const raw=await originalInvoke.call(originalClient,options);try{const frame=JSON.parse(raw);const row={method:options.request.method,schema_version:frame.schema_version,ok:frame.ok};if(frame.ok===false){row.exit_code=frame.exit_code;row.error=/^[A-Z][A-Z0-9_]{0,127}$/.test(frame.error)?frame.error:"UNLISTED_FIXED_ERROR";}if(result.control_frames.length<512)result.control_frames.push(row);}catch{}return raw;}});
 const timeoutCommand="printf 'OWN_TIMEOUT_STARTED\\n' > timeout-marker; /usr/bin/sleep 30";
 const outputCommand="chunk=x; for ((i=0;i<17;i++)); do chunk=\"$chunk$chunk\"; done; for ((i=0;i<12;i++)); do printf '%s' \"$chunk\"; done";
 assert(131072*12<=2*1024*1024);
 phase="actual-launch";
 const answer=await launch({sdk,ai,manifest,installed,instanceRoot,runtimeRoot:"/source",cwd,engine:"node",supervisor,argv:["--print","own actual authority request"],verifyDeployment(){},
 initializeRuntime:()=>async()=>({modelRuntime:scope.modelRuntime,check:scope.check,configurationDigest:models.declarationDigest}),
 createRuntime:async(...args)=>{
 const runtime=await createOfficialFileRuntime(...args);
 runtime.session.subscribe(event=>{if(event.type==="tool_execution_end")result.events.push({toolName:event.toolName,isError:event.isError,result:event.result});});
 result.synthetic_confirmations=0;
 const ui={notify(){},setStatus(){},setWidget(){},setFooter(){},setHeader(){},setTitle(){},setWorkingMessage(){},async confirm(_title,summary){assert(summary.startsWith("Tool: bash\n"));result.synthetic_confirmations++;return true;}};
 const bind=()=>runtime.session.bindExtensions({mode:"tui",uiContext:ui,onError(error){throw error;}});
 runtime.setRebindSession(bind);await bind();phase="actual-timeout";const started=Date.now();
 faux.setResponses([ai.fauxAssistantMessage(ai.fauxToolCall("bash",{command:timeoutCommand,timeout:5},{id:"shell-timeout"})),ai.fauxAssistantMessage("OWN_TIMEOUT_DONE")]);
 const pending=runtime.session.prompt("own bounded timeout request",{expandPromptTemplates:false});pending.catch(()=>{});
 const deadline=Date.now()+10000;
 while(!fs.existsSync(cwd+"/timeout-marker")){assert(Date.now()<deadline);await new Promise(resolve=>setTimeout(resolve,20));}
 const active=fs.readdirSync(stateRoot+"/activity/leases").filter(name=>name.endsWith(".json")).map(name=>JSON.parse(fs.readFileSync(stateRoot+"/activity/leases/"+name))).filter(row=>row.kind==="external"&&row.state==="running");
 assert.equal(active.length,1);result.timeout_started_lease=active[0].lease_id;result.running_before_timeout=true;
 await pending;const timeoutEvent=result.events.at(-1);assert.equal(timeoutEvent.isError,true);assert(JSON.stringify(timeoutEvent.result).includes("ORDINARY_OPERATION_TIMEOUT"),JSON.stringify(timeoutEvent.result).slice(0,192));result.timeout_elapsed_ms=Date.now()-started;
 phase="actual-truncation";
 faux.setResponses([ai.fauxAssistantMessage(ai.fauxToolCall("bash",{command:outputCommand},{id:"shell-truncation"})),ai.fauxAssistantMessage("OWN_TRUNCATION_DONE")]);
 await runtime.session.prompt("own bounded stdout request",{expandPromptTemplates:false});const output=result.events.at(-1);assert.equal(output.isError,false,JSON.stringify(output.result).slice(0,192));assert.equal(output.result.details.exitCode,0);assert.equal(output.result.details.truncated,true);assert.equal(output.result.details.terminationConfirmed,true);assert(output.result.content.some(row=>row.text?.includes("[Output truncated]")));result.requested_stdout_bytes=131072*12;
 phase="actual-fragmented-truncation";
 const small="T020_"+"x".repeat(122)+"\n";assert.equal(Buffer.byteLength(small),128);
 const fragmented="for ((i=0;i<12288;i++)); do printf '%s' '"+small+"'; done";
 faux.setResponses([ai.fauxAssistantMessage(ai.fauxToolCall("bash",{command:fragmented},{id:"shell-fragmented"})),ai.fauxAssistantMessage("OWN_FRAGMENTED_DONE")]);
 await runtime.session.prompt("own fragmented bounded stdout request",{expandPromptTemplates:false});const final=result.events.at(-1);assert.equal(final.isError,false,JSON.stringify(final.result).slice(0,192));assert.equal(final.result.details.exitCode,0);assert.equal(final.result.details.truncated,true);assert.equal(final.result.details.terminationConfirmed,true);
 assert.equal(result.synthetic_confirmations,3);
 faux.setResponses([ai.fauxAssistantMessage("OWN_REAL_SHELL_AUTHORITY_REPLY")]);return runtime;
}});
 assert.equal(answer.code,0);result.status="observed";

}catch(error){result.status="failed";result.phase=phase;result.error=String(error.message).slice(0,192);process.exitCode=2;}
finally{result.budget=budget;fs.writeFileSync("/work/sdk-result.json",JSON.stringify(result));}

}
if (process.argv[2] === "--guest-manager") await guestManager();
