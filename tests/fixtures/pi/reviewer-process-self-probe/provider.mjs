// 唯一自有SDK替身：记录实际跨child/Worker收到的非秘密Model及固定参数。
import { writeFileSync } from "node:fs";
import { getEnvironmentData, isMainThread } from "node:worker_threads";
export async function* streamSimple(model, context, options) {
 if(!["self-model","shared-deepseek","shared-text"].includes(model.id))throw Error("SELF_PROBE_INVALID");
 const body={model:model.id,messages:[{role:"system",content:context.systemPrompt},{role:"user",content:context.messages[0].content}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:options.maxTokens,...(model.reasoning?{thinking:{type:"disabled"}}:{})};
 writeFileSync("/work/sdk-observation-"+model.id+".json",JSON.stringify({schema_version:1,is_worker:!isMainThread,ambient_key_absent:process.env.SYNTHETIC_MAIN_KEY===undefined,environment_data_absent:getEnvironmentData("synthetic-main-secret")===undefined,environment_keys:Object.keys(process.env).sort(),log_off:process.env.OPENAI_LOG==="off",key_not_in_argv:!process.argv.some(v=>v.includes(options.apiKey)),injected_node_options_absent:process.env.NODE_OPTIONS===undefined,model,options:{maxRetries:options.maxRetries,maxTokens:options.maxTokens,temperature:options.temperature,reasoning:options.reasoning??null},wire:{model:body.model,max_tokens:body.max_tokens,thinking:body.thinking??null}}),{flag:"wx",mode:0o600});
 process.stdout.write("SELF_FAKE_OUTPUT_DROP".repeat(4096));process.stderr.write("SELF_FAKE_OUTPUT_DROP".repeat(4096));
 const response=await options.fetch(model.baseUrl+"/chat/completions",{method:"POST",headers:{authorization:"Bearer "+options.apiKey,accept:"application/json","content-type":"application/json"},body:JSON.stringify(body),signal:options.signal});await response.text();
 await options.onProviderStreamEvent({model:model.id,usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}});await options.onProviderStreamEvent({model:model.id,usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}});
 yield {type:"done",message:{api:model.api,provider:model.provider,model:model.id,stopReason:"stop",content:[{type:"text",text:context.messages[0].content}]}};
}
