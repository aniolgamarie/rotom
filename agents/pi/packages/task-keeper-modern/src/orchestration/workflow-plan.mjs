import { assertWriterAllowed } from "../contracts/writers.mjs";
import { allSharedWriteResources } from "../workspace/shared-resources.mjs";
import { ContractError } from "../contracts/primitives.mjs";
export const MAX_FIXED_SEMANTIC_REPLANS = 2;
export function fixedWorkflowAttemptLimit(configured, planned = configured) {
    return Math.min(3, configured, planned);
}
export function workflowRequirements(config, workflow) {
    const reviewId = workflow === "fix" ? "independent-review" : "scope-evidence-review";
    const required = [
        ...new Set([
            ...config.workflow.requiredChecks[workflow],
            reviewId
        ])
    ];
    return {
        reviewId,
        required,
        optional: config.workflow.optionalChecks[workflow].filter((id)=>!required.includes(id))
    };
}
export function fixedWorkflowPlan(config, input) {
    if (config.workflow.recipes.includes("cascade")) throw new ContractError("CASCADE_REMOVED");
    if (input.workflow === "fix") assertWriterAllowed(config.limits.writersPerJob);
    const attempts = fixedWorkflowAttemptLimit(config.limits.semanticAttemptsPerImplementationTask);
    if (attempts === 0) throw new ContractError("SEMANTIC_ATTEMPTS_DISABLED");
    const { reviewId, required, optional } = workflowRequirements(config, input.workflow);
    const opinion = input.secondOpinion ?? config.secondOpinion.enabled;
    if (opinion) required.push("second-opinion");
    const spec = {
        id: input.id,
        workScope: input.workScope,
        version: 1,
        objective: input.goal,
        workflow: input.workflow,
        required,
        optional,
        allowPartial: config.workflow.allowPartial,
        risk: config.workflow.risk,
        policyDigest: input.policyDigest,
        snapshot: input.snapshot,
        maxSteps: config.limits.dispatchedStepsPerJob,
        maxSemanticAttempts: attempts,
        ...config.features.semanticReplanning ? {
            maxSemanticReplans: Math.min(MAX_FIXED_SEMANTIC_REPLANS, config.limits.semanticReplansPerTask)
        } : {}
    };
    const base = (id, kind, role, dependencies)=>({
            id,
            kind,
            role,
            dependencies,
            allowedSkippedDependencies: [],
            optional: false,
            resources: []
        });
    const steps = [];
    const workspaceLock = input.workspaceLock;
    if (input.workflow === "fix") {
        const build = required.find((id)=>config.verificationBindings[id]?.kind === "build");
        if (!build || !required.some((id)=>config.verificationBindings[id]?.kind === "tests")) throw new ContractError("BUILD_AND_TEST_BINDINGS_REQUIRED");
        const baseline = base("baseline:" + build, "verify", "baseline", []);
        baseline.resources = [
            {
                id: "heavy-verifiers",
                capacity: config.limits.heavyVerifiersPerHost,
                units: 1
            },
            {
                id: workspaceLock,
                capacity: 1,
                units: 1
            }
        ];
        steps.push(baseline, base("implement", "write", "worker", [
            baseline.id
        ]));
    } else steps.push(base("inspect", "read", "scout", []));
    const implementationId = input.workflow === "fix" ? "implement" : "inspect";
    const verifications = [
        ...required.filter((id)=>id !== reviewId && id !== "second-opinion"),
        ...spec.optional
    ];
    for (const id of verifications){
        if (!config.verificationBindings[id]) throw new ContractError("CHECK_BINDING_REQUIRED", id);
        const step = base(id, "verify", "verify", [
            implementationId
        ]);
        step.optional = spec.optional.includes(id);
        step.resources = [
            {
                id: "heavy-verifiers",
                capacity: config.limits.heavyVerifiersPerHost,
                units: 1
            },
            {
                id: workspaceLock,
                capacity: 1,
                units: 1
            }
        ];
        steps.push(step);
    }
    let reviewDependencies = verifications.length ? verifications : [
        implementationId
    ];
    if (opinion) {
        steps.push(base("second-opinion", "review", "reviewer", reviewDependencies));
        reviewDependencies = [
            "second-opinion"
        ];
    }
    steps.push(base(reviewId, "review", "reviewer", reviewDependencies));
    for (const step of steps)if (step.kind !== "verify") step.resources = [
        {
            id: "model-dispatch-slots",
            capacity: config.limits.activeChildrenPerHost,
            units: 1
        }
    ];
    for (const step of steps){
        if (step.kind === "read" || step.kind === "review") step.resources.push({
            id: "managed-readers",
            capacity: 1,
            units: 1
        });
        if (step.kind === "write") step.resources.push({
            id: workspaceLock,
            capacity: 1,
            units: 1
        }, {
            id: "writer-job-" + input.id,
            capacity: 1,
            units: 1
        });
    }
    for (const step of steps)if (step.kind === "review") step.allowedSkippedDependencies = [
        ...new Set([
            ...step.allowedSkippedDependencies,
            ...spec.optional.filter((id)=>step.dependencies.includes(id))
        ])
    ];
    for (const step of steps){
        const shared = input.sharedWriteResources ?? {};
        if (step.kind === "write") step.resources.push(...allSharedWriteResources(shared));
        if (step.kind === "verify") step.resources.push(...shared[step.id.startsWith("baseline:") ? step.id.slice("baseline:".length) : step.id] ?? []);
    }
    return {
        spec,
        steps
    };
}
