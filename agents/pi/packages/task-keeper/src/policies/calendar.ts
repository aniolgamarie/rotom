import type { Window } from "./configuration.ts";
import { ContractError } from "../contracts/primitives.ts";
const formatters = new Map<string, Intl.DateTimeFormat>();
const weekdays:Record<string,number>={Mon:1,Tue:2,Wed:3,Thu:4,Fri:5,Sat:6,Sun:7};
const minute=(time:string)=>Number(time.slice(0,2))*60+Number(time.slice(3));
export function localTime(at:number,zone:string) {
  let formatter=formatters.get(zone);
  if(!formatter){try{formatter=new Intl.DateTimeFormat("en-US",{timeZone:zone,weekday:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});}catch{throw new ContractError("INVALID_TIMEZONE");}formatters.set(zone,formatter);}
  const values=Object.fromEntries(formatter.formatToParts(at).map(part=>[part.type,part.value]));
  return{day:weekdays[values.weekday],minute:Number(values.hour)*60+Number(values.minute)};
}
export function windowContains(window:Window,at:number,zone:string):boolean {
  const current=localTime(at,zone),start=minute(window.start),end=minute(window.end);
  return start<end ? window.days.includes(current.day)&&current.minute>=start&&current.minute<end
    : (window.days.includes(current.day)&&current.minute>=start)||(window.days.includes(current.day===1?7:current.day-1)&&current.minute<end);
}
export function inWindows(windows:Window[],at:number,zone:string):boolean {return !windows.length || windows.some(window=>windowContains(window,at,zone));}
export function nextWindow(windows:Window[],notBefore:number,zone:string,deadline:number|null=null):number|null {
  if(!Number.isSafeInteger(notBefore)||notBefore<0)throw new ContractError("INVALID_TIME");
  if(deadline!==null && notBefore>=deadline)return null;
  if(inWindows(windows,notBefore,zone))return notBefore;
  // Scan UTC minutes so both copies of a DST fold exist and skipped local times do not.
  const limit=Math.min(deadline??Infinity,notBefore+9*86400000);
  for(let at=Math.ceil((notBefore+1)/60000)*60000;at<limit;at+=60000)if(inWindows(windows,at,zone))return at;
  return null;
}
export function windowsOverlap(a:Window,b:Window):boolean {
  const occupied=(w:Window)=>{
    const result=new Set<number>(),start=minute(w.start),end=minute(w.end),length=end>start?end-start:1440-start+end;
    for(const day of w.days)for(let m=0;m<length;m++)result.add(((day-1)*1440+start+m)%10080);
    return result;
  };
  const first=occupied(a);return [...occupied(b)].some(m=>first.has(m));
}
