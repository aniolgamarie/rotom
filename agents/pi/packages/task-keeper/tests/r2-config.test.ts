import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { parseConfig, previewConfigMigration, applyProjectPolicy, DEFAULT_CONFIG } from "../src/config.ts";
import { duration } from "../src/policies/configuration.ts";
import { recipePolicy, type RecipeInput } from "../src/orchestration/policy.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";
import { writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
function credit(id: string, variant: string, observed: unknown, body: () => void, level = "U") {
  acceptance(id, variant, {level,observer:level === "V" ? "config-preview-cli" : "independent-contract-inputs",predicate:`${id}.${variant}`,artifact:observerArtifact(`${id}-${variant}`,observed)},body);
}
function legacyConfig() {
  const value: any=structuredClone(configured());value.schemaVersion=6;
  for(const name of ["usage","timePolicy","modelPolicy","secondOpinion","quotaBindings"])delete value[name];
  delete value.recovery.policies;for(const route of Object.values(value.routes) as any[])delete route.recoveryPolicy;
  return value;
}
test("[V] R2 migration previews preserve legacy bindings and explicitly remove cascade without writing files",t=>{
  const root=isolatedDirectory(t), path=join(root,"input.json"), legacy=legacyConfig();
  const variants=["v6-valid","v6-cascade-enabled","migration-repeat"];
  for(const variant of variants){
    const input=structuredClone(legacy);if(variant==="v6-cascade-enabled")input.workflow.recipes=["direct","cascade"];
    const written=JSON.stringify(variant==="migration-repeat"?previewConfigMigration(input).proposed:input);writeFileSync(path,written);
    const result=spawnSync(process.execPath,["--experimental-strip-types",fileURLToPath(new URL("../scripts/config-preview.ts",import.meta.url)),path],{encoding:"utf8"});
    assert.equal(result.status,0,result.stderr);const output=JSON.parse(result.stdout);
    credit("AC01",variant,{input:JSON.parse(written),output,exitCode:result.status},()=>{
      assert.equal(output.to,7);assert.equal(output.proposed.schemaVersion,7);
      assert.equal(output.proposed.routes.primary.provider,legacy.routes.primary.provider);
      assert.equal(output.proposed.routes.primary.accountBinding,legacy.routes.primary.accountBinding);
      assert.deepEqual(output.proposed.quotaGroups,legacy.quotaGroups);assert.deepEqual(output.proposed.budget,legacy.budget);
      assert.equal(output.proposed.modelPolicy.automaticSelection,false);assert.equal(output.proposed.secondOpinion.enabled,false);
      assert.equal(readFileSync(path,"utf8"),written);assert.equal(output.requiresUserEdit,variant==="v6-cascade-enabled");
      if(variant==="v6-cascade-enabled"){assert.deepEqual(output.diagnostics,["CASCADE_REMOVED"]);assert.throws(()=>parseConfig(input),{code:"CASCADE_REMOVED"});}
      else assert.deepEqual(previewConfigMigration(output.proposed).proposed,output.proposed);
    },"V");
    if(variant === "v6-cascade-enabled")credit("AC30","legacy-preview",{input,output},()=>{
      assert.equal(output.requiresUserEdit,true);assert.deepEqual(output.diagnostics,["CASCADE_REMOVED"]);assert.equal(output.proposed.workflow.recipes.includes("cascade"),false);assert.equal(readFileSync(path,"utf8"),written);
    },"V");
  }
});
test("[U] v7 switches remain independent and duration boundaries reject invalid policies",()=>{
  assert.deepEqual(parseConfig({}),DEFAULT_CONFIG);
  credit("AC01","invalid-duration",{valid:{oneHour:duration("1h"),twoHours:duration("2h")}},()=>{
    assert.equal(duration("1h"),3600000);assert.equal(duration("2h"),7200000);
    for(const value of ["0h","-1h","1.5h","NaNh","999999999d",3600000])assert.throws(()=>duration(value));
    assert.throws(()=>parseConfig({recovery:{policies:{defaults:{quotaBackoff:["2h"],maxLocalInterval:"1h"}}}}),{code:"BACKOFF_EXCEEDS_LOCAL_MAXIMUM"});
  });
  const config=parseConfig({enabled:true,usage:{enabled:true},modelPolicy:{candidates:["provider/model"]}});
  assert.equal(config.usage.enabled,true);assert.equal(config.modelPolicy.automaticSelection,false);assert.equal(config.secondOpinion.enabled,false);
  credit("AC02","project-expansion",config,()=>{
    for(const patch of [{modelPolicy:{automaticSelection:true}},{secondOpinion:{enabled:true}},{recovery:{policies:{defaults:{maxWait:null}}}}])assert.throws(()=>applyProjectPolicy(config,patch));
    const restricted=applyProjectPolicy(config,{budget:{protectedAttemptsPerWorkScope:1000}});assert.equal(restricted.budget.protectedAttemptsPerWorkScope,12);
  });
});
test("[U] removed cascade cannot be requested or triggered by implementation failure",()=>{
  const input:RecipeInput={enabled:["direct"],qualityFailure:true,environmentFailure:false,upgradeEligible:true,criticEligible:false,upgradesUsed:0,critiquesUsed:0,semanticAttempts:2,maxSemanticAttempts:3,stepsUsed:4,maxSteps:16,remainingRequests:10,requiredReserve:1,finding:null};
  credit("AC01","v7-cascade-request",input,()=>{assert.throws(()=>parseConfig({workflow:{recipes:["direct","cascade"]}}),{code:"CASCADE_REMOVED"});});
  credit("AC30","new-config-reject",input,()=>{assert.throws(()=>parseConfig({schemaVersion:7,workflow:{recipes:["cascade"]}}),{code:"CASCADE_REMOVED"});});
  for(const variant of ["implementation-fail","environment-fail","many-rounds"]){
    const actual={...input,environmentFailure:variant==="environment-fail",stepsUsed:variant==="many-rounds"?16:4};
    assert.notEqual(recipePolicy(actual).action,"upgrade");assert.equal(recipePolicy(actual).action,variant==="implementation-fail"?"direct":"block");
  }
  assert.throws(()=>recipePolicy({...input,enabled:["cascade"]}),{code:"CASCADE_REMOVED"});
});
