import type { Config } from "../config.ts";
import { ContractError, digest } from "../contracts/primitives.ts";
import type { ModelReference } from "./configuration.ts";
export function routeReference(config:Config,reference:ModelReference|string):string {
  if(typeof reference === "string" && Object.hasOwn(config.routes,reference))return reference;
  const ref=typeof reference === "string"?{provider:reference.slice(0,reference.indexOf("/")),model:reference.slice(reference.indexOf("/")+1)}:reference;
  const candidates=Object.entries(config.routes).filter(([id,route])=>config.allowedRoutes.includes(id)&&route.provider===ref.provider&&route.model===ref.model);
  if(candidates.length!==1)throw new ContractError("MODEL_ROUTE_NOT_UNAMBIGUOUS");return candidates[0][0];
}
export function opinionBinding(config:Config) {
  const defaults=config.roles.reviewer, settings=config.secondOpinion;
  const route=settings.model===null?defaults?.route:routeReference(config,settings.model);
  const profileRef=settings.profileRef??defaults?.profileRef,profile=profileRef?config.executionProfiles[profileRef]:null;
  if(!route||!config.allowedRoutes.includes(route)||!profile||!profileRef)throw new ContractError("SECOND_OPINION_BINDING_REQUIRED");
  if(!profile.tools.length||profile.tools.some(tool=>!["read","grep","find","ls"].includes(tool)))throw new ContractError("SECOND_OPINION_READONLY_REQUIRED");
  return{route,profileRef,maxExchanges:settings.maxExchanges,reviewTask:settings.reviewTask,focus:settings.focus,
    contractDigest:digest([route,profileRef,profile,settings.reviewTask,settings.focus,settings.maxExchanges])};
}
