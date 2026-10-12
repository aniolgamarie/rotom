import { originalProcessStopped } from "./process-identity.mjs";
export function childTerminationConfirmed(observation, processStopped) {
    return !!observation.process && processStopped === true && Array.isArray(observation.externalWork) && observation.externalWork.length === 0;
}
export function childPhysicallyStopped(observation) {
    return childTerminationConfirmed(observation, observation.process ? originalProcessStopped(observation.process) : null);
}
