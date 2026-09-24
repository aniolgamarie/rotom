import {tap} from "node:test/reporters";
import {writeFileSync,readdirSync} from "node:fs";
import {join,relative,resolve} from "node:path";
export function coverageView(summary,root){
  const files=summary.files.filter(file=>{const path=relative(root,file.path);return path==="index.ts"||path.startsWith("src/");});
  const counts={totalLineCount:0,coveredLineCount:0,totalBranchCount:0,coveredBranchCount:0,totalFunctionCount:0,coveredFunctionCount:0};
  for(const file of files)for(const key of Object.keys(counts))counts[key]+=file[key];
  const percent=(covered,total)=>total?100*covered/total:null;
  const inventory=[];const walk=path=>{for(const entry of readdirSync(path,{withFileTypes:true})){const file=join(path,entry.name);if(entry.isDirectory())walk(file);else if(file.endsWith(".ts"))inventory.push(relative(root,file));}};walk(join(root,"src"));
  return{scope:"observed-test-workers",complete:false,nativePiSubprocessCoverage:"not-collected",interpretation:"Partial observation; not whole-product coverage or semantic spec verification",
    excludedFiles:summary.files.length-files.length,unobservedProductionFiles:["index.ts",...inventory].filter(path=>!files.some(file=>relative(root,file.path)===path)),
    totals:{...counts,linePercent:percent(counts.coveredLineCount,counts.totalLineCount),branchPercent:percent(counts.coveredBranchCount,counts.totalBranchCount),functionPercent:percent(counts.coveredFunctionCount,counts.totalFunctionCount)},
    files:files.map(file=>({...file,path:relative(root,file.path)}))};
}
export default async function* reporter(source){
  async function* observed(){for await(const event of source){
    if(event.type==="test:coverage"&&process.env.TASK_KEEPER_CODE_COVERAGE_FILE)writeFileSync(process.env.TASK_KEEPER_CODE_COVERAGE_FILE,JSON.stringify(coverageView(event.data.summary,resolve(process.cwd())),null,2)+"\n");
    yield event;
  }}
  yield* tap(observed());
}
