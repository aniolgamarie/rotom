// 仅自有临时import-only假SDK，真实自有Worker；不加载官方SDK或发送网络请求。
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync, readFileSync } from "node:fs";
import { tmpdir, release } from "node:os";
import { join } from "node:path";
import { runReviewerProbe } from "../../../../scripts/pi-probe-reviewer-sdk.mjs";
function fixture(t, mode = "normal") {
  const root = mkdtempSync(join(tmpdir(), "own-reviewer-probe-"));
  t.after(() => rmSync(root, {recursive:true,force:true}));
  const anchor = join(root,"package.json"), pkg=join(root,"node_modules/@earendil-works/pi-ai");
  mkdirSync(join(pkg,"api"),{recursive:true}); mkdirSync(join(pkg,"utils"));
  writeFileSync(anchor,'{"type":"module"}');
  writeFileSync(join(pkg,"package.json"),JSON.stringify({type:"module",exports:{"./api/*":{import:"./api/*.mjs"},"./utils/*":{import:"./utils/*.mjs"}}}));
  writeFileSync(join(pkg,"utils/transcript.mjs"),'export const normalizeContext = value => value;');
  writeFileSync(join(pkg,"api/openai-completions.mjs"), `
    import { appendFileSync } from 'node:fs';
    appendFileSync(${JSON.stringify(join(root,"imported"))},'x');
    if (Object.keys(process.env).join(',') !== 'OPENAI_LOG' || process.env.OPENAI_LOG !== 'off') throw Error('own-private-env');
    export async function* streamSimple(model,context,options) {
      const headers = {authorization:'Bearer '+options.apiKey,accept:'application/json','content-type':'application/json',
        'user-agent':${JSON.stringify(`pi (linux ${release()}; x64)`)},'x-stainless-lang':'js','x-stainless-package-version':'7.19.0',
        'x-stainless-os':'Linux','x-stainless-arch':'x64','x-stainless-runtime':'node','x-stainless-runtime-version':'v24.14.0',
        'x-stainless-retry-count':'0','x-stainless-timeout':String(Math.trunc(options.timeoutMs/1000))};
      const response=await options.fetch(model.baseUrl+'/chat/completions',{method:'POST',headers,
        body:JSON.stringify({model:model.id,messages:[{role:'system',content:context.systemPrompt},{role:'user',content:context.messages[0].content}],
          stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:options.maxTokens}),signal:options.signal});
      let text='';
      for (const line of (await response.text()).split('\\n')) {
        if (!line.startsWith('data: ') || line==='data: [DONE]') continue;
        const chunk=JSON.parse(line.slice(6));
        if (${JSON.stringify(mode)} === 'bad-model') chunk.model='own-wrong';
        await options.onProviderStreamEvent(chunk);
        text+=chunk.choices[0]?.delta?.content ?? '';
      }
      yield {type:'done',message:{api:model.api,provider:model.provider,model:model.id,stopReason:'stop',content:[{type:'text',text}]}};
    }
  `);
  return {anchor,root,platform:'linux',arch:'x64',release:release(),runtimeVersion:'v24.14.0',sdkVersion:'7.19.0'};
}
const ids=['allow','ask','deny','missing-usage','wrong-model','canceled','response-limit','hard-deny','human-required'];
test('all nine cases observed with only own fake SDK and no sensitive metadata', {timeout:30000}, async t => {
  const {root,...options}=fixture(t); const result=await runReviewerProbe(options);
  assert.deepEqual(Object.keys(result).sort(),['cases','probe_id','product_gate','schema_version','status']);
  assert.equal(result.status,'observed'); assert.equal(result.product_gate,false);
  assert.deepEqual(result.cases.map(x=>x.case_id),ids);
  for (const row of result.cases) {
    assert.equal(row.outcome,'observed');
    assert.deepEqual(Object.keys(row).sort(),['case_id','decision','outcome','requests','transport_outcome','usage','worker_started','worker_terminated']);
    assert.equal(row.requests, ['hard-deny','human-required'].includes(row.case_id)?0:1);
    assert.equal(row.worker_started,row.requests===1); assert.equal(row.worker_terminated,row.requests===1);
    if (['hard-deny','human-required'].includes(row.case_id))
      assert.deepEqual(row.usage,{status:'not-sent',input_tokens:0,output_tokens:0,total_tokens:0});
    if (['missing-usage','wrong-model','canceled','response-limit'].includes(row.case_id))
      assert.deepEqual(row.usage,{status:'unknown',input_tokens:null,output_tokens:null,total_tokens:null});
  }
  assert.equal(result.cases[3].usage.status,'unknown'); assert.equal(result.cases[3].usage.total_tokens,null);
  assert.equal(result.cases[4].decision,null); assert.equal(result.cases[5].transport_outcome,'canceled');
  assert.equal(readFileSync(join(root,'imported'),'utf8'),'x'.repeat(7)); // 两个拒绝资格case不导入SDK。
  const json=JSON.stringify(result); for(const secret of ['SYNTHETIC_PROBE_KEY','synthetic policy',options.anchor,'authorization']) assert.equal(json.includes(secret),false);
});
test('failed proof cannot return observed', {timeout:15000},async t=>{
  const {root,...options}=fixture(t,'bad-model');
  await assert.rejects(runReviewerProbe(options),error=>error.code==='PI_REVIEWER_SDK_PROBE_FAILED' && error.message===error.code);
});
for(const invalid of ['extra','getter','proxy','platform','anchor']) test('closed configuration rejects '+invalid+' without SDK import',async t=>{
  const {root,...options}=fixture(t); let calls=0; let value=options;
  if(invalid==='extra') value={...options,extra:true};
  if(invalid==='getter') Object.defineProperty(value,'release',{get(){calls++;throw Error('secret');},enumerable:true});
  if(invalid==='proxy') value=new Proxy(value,{ownKeys(){calls++;throw Error('secret');}});
  if(invalid==='platform') value.platform='darwin';
  if(invalid==='anchor') value.anchor='relative/package.json';
  await assert.rejects(runReviewerProbe(value),e=>e.code==='PI_REVIEWER_SDK_PROBE_FAILED');
  assert.equal(calls,0); assert.equal(existsSync(join(root,'imported')),false);
});
