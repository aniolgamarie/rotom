import { Store } from "../store/database.mjs";
import { newId, ContractError, digest } from "../contracts/primitives.mjs";
export const incidentNamespace = (domain)=>domain.kind === "quota" ? "incidents" : "transport-incidents";
export const failureDomain = (route, failure)=>failure.category === "network_overload" ? {
        kind: "transport",
        id: route.transportDomain
    } : {
        kind: "quota",
        id: route.quotaGroup
    };
export function routeIncidents(store, route) {
    return [
        {
            kind: "quota",
            id: route.quotaGroup
        },
        {
            kind: "transport",
            id: route.transportDomain
        }
    ].flatMap((domain)=>{
        const value = store.get(incidentNamespace(domain), domain.id);
        return value && value.status !== "CLOSED" ? [
            {
                ...value,
                domain
            }
        ] : [];
    }).sort((a, b)=>b.notBefore - a.notBefore || a.id.localeCompare(b.id));
}
export const routeNotBefore = (store, route)=>routeIncidents(store, route)[0]?.notBefore ?? 0;
export function recoveryResources(store, route) {
    return [
        {
            id: `quota-${route.quotaGroup}`,
            capacity: 1,
            units: 1
        },
        ...routeIncidents(store, route).filter((incident)=>incident.domain?.kind === "transport").map((incident)=>({
                id: `transport-${digest(incident.domain.id)}`,
                capacity: 1,
                units: 1
            }))
    ];
}
export function ensureExecutionTransportLease(store, owner, descriptorId, jobId, parentIntentId, route, onAdmitted) {
    return store.transaction(()=>{
        const acquire = ()=>{
            store.assertOwner(owner);
            const resource = recoveryResources(store, route).find((demand)=>demand.id.startsWith("transport-"));
            if (!resource) return null;
            const parent = parentIntentId ? store.intent(parentIntentId) : null;
            if (parent && parent.scopeId === owner.scopeId && parent.epoch === owner.epoch && [
                "prepared",
                "sent",
                "acked"
            ].includes(parent.status) && store.claims().some((claim)=>claim.intent_id === parentIntentId && claim.resource_id === resource.id)) return null;
            const id = `domain-lease-${digest([
                descriptorId,
                route.transportDomain
            ])}`;
            const previous = store.intent(id);
            if (previous) {
                if (previous.scopeId !== owner.scopeId || previous.epoch !== owner.epoch || ![
                    "prepared",
                    "sent",
                    "acked"
                ].includes(previous.status) || !store.claims().some((claim)=>claim.intent_id === id && claim.resource_id === resource.id)) throw new ContractError("TRANSPORT_LEASE_NOT_RECONCILED");
                return id;
            }
            try {
                store.prepare(owner, id, "transport-domain", {
                    descriptorId,
                    jobId,
                    domain: route.transportDomain
                }, [
                    resource
                ]);
            } catch (error) {
                if (error instanceof ContractError && error.code === "RESOURCE_DENIED") throw new ContractError("SHARED_DOMAIN_BUSY");
                throw error;
            }
            const leases = store.get("execution-domain-leases", descriptorId) ?? [];
            store.put("execution-domain-leases", descriptorId, [
                ...leases,
                id
            ]);
            return id;
        };
        const result = acquire();
        onAdmitted?.();
        return result;
    });
}
export function admitTransportRequest(store, owner, descriptorId, jobId, parentIntentId, route, requestId, check) {
    if (!requestId) throw new ContractError("REQUEST_ID_REQUIRED");
    if (check.constructor.name === "AsyncFunction") throw new ContractError("ASYNC_ADMISSION_CHECK");
    ensureExecutionTransportLease(store, owner, descriptorId, jobId, parentIntentId, route, ()=>{
        const checked = check();
        if (checked && typeof checked.then === "function") {
            void Promise.resolve(checked).catch(()=>{});
            throw new ContractError("ASYNC_ADMISSION_CHECK");
        }
        if (store.get("request-admissions", requestId)) throw new ContractError("DUPLICATE_REQUEST_ADMISSION");
        store.put("request-admissions", requestId, {
            requestId,
            scopeId: owner.scopeId,
            ownerEpoch: owner.epoch,
            descriptorId,
            jobId,
            parentIntentId,
            transportDomain: route.transportDomain,
            quotaGroup: route.quotaGroup,
            authorizedAt: Date.now(),
            provesSend: false
        });
    });
}
export function settleExecutionTransportLeases(store, descriptorId) {
    for (const id of store.get("execution-domain-leases", descriptorId) ?? []){
        const intent = store.intent(id);
        if (intent?.kind !== "transport-domain" || intent.payload.descriptorId !== descriptorId) throw new ContractError("TRANSPORT_LEASE_IDENTITY_MISMATCH");
        store.settle(id, "terminated");
    }
}
export function closeRouteIncidents(store, route, preserveQuotaIncident, now = Date.now()) {
    for (const incident of routeIncidents(store, route)){
        const resource = incident.domain.kind === "quota" ? `quota-${incident.domain.id}` : `transport-${digest(incident.domain.id)}`;
        const unknownHolder = store.claims().some((claim)=>claim.resource_id === resource && typeof claim.intent_id === "string" && store.intent(claim.intent_id)?.status === "unknown");
        if (unknownHolder || incident.notBefore > now || incident.domain.kind === "quota" && incident.id === preserveQuotaIncident) continue;
        store.put(incidentNamespace(incident.domain), incident.domain.id, {
            ...incident,
            status: "CLOSED"
        });
    }
}
export function recordIncident(store, owner, config, poolId, failure, now, sample = Math.random(), domain = {
    kind: "quota",
    id: poolId
}, persist) {
    if (!Number.isFinite(sample) || sample < 0 || sample > 1) throw new ContractError("INVALID_JITTER_SOURCE");
    const pool = config.quotaGroups[poolId];
    if (!pool) throw new ContractError("UNKNOWN_QUOTA_GROUP");
    return store.transaction(()=>{
        store.assertOwner(owner);
        const namespace = incidentNamespace(domain);
        const old = store.get(namespace, domain.id), open = old && old.status !== "CLOSED";
        const failures = open ? old.failures + 1 : 1;
        const interval = failures === 1 ? pool.baseIntervalMs : pool.tailIntervalsMs[Math.min(failures - 2, pool.tailIntervalsMs.length - 1)];
        const incident = {
            id: open ? old.id : newId("incident"),
            status: "OPEN",
            failures,
            domain,
            notBefore: Math.max(now + interval, failure.retryAt ?? 0, open ? old.notBefore : 0) + Math.ceil(interval * config.recovery.positiveJitterRatio * sample)
        };
        store.put(namespace, domain.id, incident);
        persist?.(incident);
        return incident;
    });
}
export function recordServerFloor(store, owner, route, failure, persist) {
    return store.transaction(()=>{
        store.assertOwner(owner);
        const domain = failureDomain(route, failure), namespace = incidentNamespace(domain);
        const old = store.get(namespace, domain.id), open = old && old.status !== "CLOSED";
        const incident = {
            id: open ? old.id : newId("incident"),
            status: "OPEN",
            domain,
            failures: (open ? old.failures : 0) + 1,
            notBefore: Math.max(open ? old.notBefore : 0, failure.retryAt ?? 0)
        };
        store.put(namespace, domain.id, incident);
        persist?.(incident);
        return incident;
    });
}
