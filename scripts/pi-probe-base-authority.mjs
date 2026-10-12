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
const budget = { sender: 0 }; const LIMITS = { sender_calls: 16 }; let phase;
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
 const supervisor = new SupervisorClient({python:process.env.AGENTCFG_PYTHON,client:process.env.AGENTCFG_SUPERVISOR_CLIENT,endpoint:process.env.AGENTCFG_SUPERVISOR_ENDPOINT,capability:process.env.AGENTCFG_SUPERVISOR_CAPABILITY});
 const calls = [["read",{path:"source.txt"}],["write",{path:"new.txt",content:"own new\n"}],["edit",{path:"source.txt",oldText:"own original",newText:"own edited"}],["write",{path:"blocked.txt",content:"forbidden"}],["write",{path:"/work/outside.txt",content:"forbidden"}],["ls",{path:"."}],["find",{path:".",pattern:"*.txt"}],["grep",{path:".",pattern:"own",literal:true}],["grep",{path:".",pattern:"hard deny sentinel",literal:true}],["ls",{path:"/work"}],["find",{path:"/work",pattern:"*.txt"}],["grep",{path:"/work",pattern:"sentinel",literal:true}]];
 faux.setResponses([...calls.map(([name,args],index)=>ai.fauxAssistantMessage(ai.fauxToolCall(name,args,{id:"own-call-"+index}))),ai.fauxAssistantMessage("OWN_REAL_AUTHORITY_REPLY")]);
 phase="actual-launch";
 const answer=await launch({sdk,ai,manifest,installed,instanceRoot,runtimeRoot:"/source",cwd,engine:"node",supervisor,argv:["--print","own actual authority request"],verifyDeployment(){},
 initializeRuntime:()=>async()=>({modelRuntime:scope.modelRuntime,check:scope.check,configurationDigest:models.declarationDigest}),
 createRuntime:async(...args)=>{
 const runtime=await createOfficialFileRuntime(...args);
 runtime.session.subscribe(event=>{if(event.type==="tool_execution_end")result.events.push({toolName:event.toolName,isError:event.isError,result:event.result});});
 result.synthetic_confirmations=0;
 return runtime;
}});
 assert.equal(answer.code,0); assert.deepEqual(result.events.map(row=>row.isError),[false,false,false,true,true,false,false,false,false,true,true,true]);
 for(const event of result.events.slice(5,8)){const text=JSON.stringify(event.result);assert(text.includes("source.txt"));assert(!text.includes("blocked.txt"));}
 assert(JSON.stringify(result.events[8].result).includes("No matches")); result.status="observed";
}catch(error){result.status="failed";result.phase=phase;result.error=String(error.message).slice(0,192);process.exitCode=2;}
finally{result.budget=budget;fs.writeFileSync("/work/sdk-result.json",JSON.stringify(result));}

}
if (process.argv[2] === "--guest-manager") await guestManager();
