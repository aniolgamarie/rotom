import { cpSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join, relative } from "node:path";
/** Test-only runtime fault: change the actual child thinking level before its contract check. */
export function thinkingCut(source: string, root: string) {
  const copy=join(root,"thinking-runtime");
  cpSync(source,copy,{recursive:true,filter:path=>!relative(source,path).split("/").some(part=>["node_modules","test-results","coverage",".git"].includes(part))});
  symlinkSync(join(source,"node_modules"),join(copy,"node_modules"));
  const path=join(copy,"src/adapters/child-reporter.ts"),text=readFileSync(path,"utf8");
  const target="store = new Store(dirname(dbPath), basename(dbPath)); assertGrant();";
  if(!text.includes(target))throw new Error("thinking fault boundary changed");
  writeFileSync(path,text.replace(target,target+`\n    const beforeThinking=pi.getThinkingLevel();pi.setThinkingLevel("off");\n    writeFileSync(join(store.root,"thinking-cut.json"),JSON.stringify({requested:descriptor.thinking,before:beforeThinking,actual:pi.getThinkingLevel(),descriptorId:descriptor.id}));`));
  return copy;
}
