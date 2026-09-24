import { ContractError } from "../contracts/primitives.ts";
import { instant } from "./configuration.ts";
export interface SubmissionOptions { model?:string; automatic?:boolean; secondOpinion?:boolean; comparisonGroup?:string; notBefore?:number; deadline?:number }
/** Flags are parsed only before an explicit separator; ordinary goals remain literal. */
export function submission(text:string):{goal:string;options:SubmissionOptions} {
  const match=/(?:^|\s)--(?:\s|$)/.exec(text);if(!match)return{goal:text,options:{}};
  const prefix=text.slice(0,match.index).trim().split(/\s+/).filter(Boolean),goal=text.slice(match.index+match[0].length).trim(),options:SubmissionOptions={};
  const seen=new Set<string>();
  for(let i=0;i<prefix.length;i++){
    const flag=prefix[i]==="--at"?"--not-before":prefix[i];if(seen.has(flag))throw new ContractError("DUPLICATE_SUBMISSION_OPTION");seen.add(flag);
    if(flag==="--auto-model"){options.automatic=true;continue;}
    if(flag==="--second-opinion"||flag==="--no-second-opinion"){if(options.secondOpinion!==undefined)throw new ContractError("CONFLICTING_OPINION_FLAGS");options.secondOpinion=flag==="--second-opinion";continue;}
    if(!["--model","--group","--not-before","--deadline"].includes(flag))throw new ContractError("UNKNOWN_SUBMISSION_OPTION");
    const value=prefix[++i];if(!value||value.startsWith("--"))throw new ContractError("SUBMISSION_OPTION_VALUE_REQUIRED");
    if(flag==="--model")options.model=value;else if(flag==="--group")options.comparisonGroup=value;
    else if(flag==="--not-before")options.notBefore=instant(value);else options.deadline=instant(value);
  }
  if(options.model&&options.automatic)throw new ContractError("MANUAL_AND_AUTO_MODEL_CONFLICT");
  if(!goal)throw new ContractError("INVALID_GOAL");return{goal,options};
}
