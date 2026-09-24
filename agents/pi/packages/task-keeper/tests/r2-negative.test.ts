import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {cpSync,readFileSync,writeFileSync,symlinkSync,mkdirSync} from "node:fs";
import {join,relative} from "node:path";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";
import {isolatedDirectory} from "./helpers.ts";
const cases=[
  {variant:"duplicate-usage",file:"src/usage/ledger.ts",needle:'this.store.list<UsageFact>("usage-generations")',replacement:'this.store.list<{fact:UsageFact}>("usage-facts").map(row=>({id:row.value.fact.generationId,value:row.value.fact}))',testFile:"tests/r2-usage.test.ts",name:"usage revisions and reassignment",failure:/30 !== 20/},
  {variant:"cache-double-count",file:"src/usage/ledger.ts",needle:'  const sdkCost=usage.cost',replacement:'  if(tokens.input!==null)tokens.input+=(tokens.cacheRead??0)+(tokens.cacheWrite??0);\n  const sdkCost=usage.cost',testFile:"tests/pi-rpc.test.ts",name:"cache-usage uses",failure:/10 !== 4/},
  {variant:"retry-floor-cut",file:"src/reliability/incidents.ts",needle:'notBefore: Math.max(open ? old.notBefore : 0, failure.retryAt ?? 0)',replacement:'notBefore: 0',testFile:"tests/r2-recovery.test.ts",name:"same quota pool preserves",failure:/fast/},
  {variant:"owner-guard-cut",file:"src/contracts/ownership.ts",needle:'  return current?.active === true && current.scopeId === expected.scopeId\n    && current.token === expected.token && current.epoch === expected.epoch;',replacement:'  return true;',testFile:"tests/cases-ownership-u.test.ts",name:"every independent ownership mismatch",failure:/true !== false/},
  {variant:"stale-agreement",file:"src/verification/reuse.ts",needle:'return digest({ ...contract, artifacts:',replacement:'return digest({ ...contract, spec:{...contract.spec,version:1}, artifacts:',testFile:"tests/gap-g29-u.test.ts",name:"stale incomplete or writer-owned",failure:/reviewer/},
  {variant:"exchange-cap-cut",file:"src/orchestration/service.ts",needle:'job.opinion.exchanges >= job.opinion.maxExchanges',replacement:'false',testFile:"tests/workflows-policy.test.ts",name:"opinion-zero reaches",failure:/second_opinion_disagreement_exchange_limit/},
  {variant:"auto-flag-bypass",file:"src/policies/selection.ts",needle:'if(!input.automatic)',replacement:'if(false)',testFile:"tests/r2-scheduling.test.ts",name:"automatic rules remain inert",failure:/backup/},
];
for(const row of cases)test(`[V] R2 negative control ${row.variant} fails its specific predicate`,{timeout:150000},t=>{
  const root=isolatedDirectory(t),source=fileURLToPath(new URL("..",import.meta.url)),copy=join(root,"package");
  cpSync(source,copy,{recursive:true,filter:path=>!relative(source,path).split("/").some(part=>["node_modules","test-results","coverage","docs"].includes(part))});symlinkSync(join(source,"node_modules"),join(copy,"node_modules"));
  const path=join(copy,row.file),original=readFileSync(path,"utf8");assert.equal(original.split(row.needle).length,2,`cut moved: ${row.variant}`);
  const run=(name:string)=>{const records=join(root,name,"records");mkdirSync(records,{recursive:true});return spawnSync(process.execPath,["--experimental-strip-types","--test","--test-reporter=tap","--test-name-pattern",row.name,row.testFile],{cwd:copy,encoding:"utf8",timeout:100000,env:{...process.env,NODE_TEST_CONTEXT:undefined,TASK_KEEPER_TEST_RECORD_DIR:records}});};
  const good=run("good");assert.equal(good.status,0,good.stdout+good.stderr);assert.ok(good.stdout.includes(row.name));assert.match(good.stdout,/# pass [1-9]/);
  writeFileSync(path,original.replace(row.needle,row.replacement));const bad=run("bad");
  writeFileSync(join(root,"bad.tap"),bad.stdout+bad.stderr);writeFileSync(path,original);
  acceptance("AC34",row.variant,{level:"V",observer:"private-mutant-and-unmodified-control",predicate:row.variant,artifact:observerArtifact(`negative-${row.variant}`,{file:row.file,needle:row.needle,replacement:row.replacement,good:{status:good.status,output:good.stdout},bad:{status:bad.status,signal:bad.signal,output:bad.stdout,stderr:bad.stderr}})},()=>{
    assert.equal(bad.signal,null);assert.equal(bad.status,1,bad.stdout+bad.stderr);assert.match(bad.stdout,/AssertionError|ERR_ASSERTION/);assert.match(bad.stdout,row.failure);
    assert.doesNotMatch(bad.stdout+bad.stderr,/ERR_MODULE_NOT_FOUND|SyntaxError|test timed out|MODULE_NOT_FOUND/);assert.equal(readFileSync(join(source,row.file),"utf8"),original);
  });
});
