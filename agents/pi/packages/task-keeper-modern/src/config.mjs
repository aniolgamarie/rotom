import { fromAgentcfg } from "./agentcfg-config.mjs";
import { resolveRecoveryPolicy } from "./policies/recovery.mjs";
import { DEFAULT_R2, DEFAULT_RETRY_POLICY, R2_SCHEMA, POLICIES_SCHEMA, validateR2, migrateConfigInput } from "./policies/configuration.mjs";
import { Ajv } from "ajv";
import { readFileSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { workflowRequirements } from "./orchestration/workflow-plan.mjs";
import { DEFAULT_SCHEDULING, MAX_BASE_PRIORITY } from "./orchestration/fairness.mjs";
import { ContractError, canonical, digest, object } from "./contracts/primitives.mjs";
const idSchema = {
    type: "string",
    pattern: "^[a-zA-Z0-9_.:-]{1,200}$"
};
const names = {
    type: "array",
    items: idSchema,
    uniqueItems: true
};
const integer = (min = 0, max = Number.MAX_SAFE_INTEGER)=>({
        type: "integer",
        minimum: min,
        maximum: max
    });
const timeout = integer(1, 2_147_483_647);
const shape = (properties, required = Object.keys(properties))=>({
        type: "object",
        properties,
        required,
        additionalProperties: false
    });
const map = (schema)=>({
        type: "object",
        propertyNames: idSchema,
        additionalProperties: schema
    });
const categories = [
    "frequency_limit",
    "resource_pressure",
    "window_quota",
    "network_overload",
    "auth_billing_policy",
    "context_contract",
    "execution_unknown",
    "other"
];
export const CONFIG_SCHEMA = {
    $schema: "http://json-schema.org/draft-07/schema#",
    ...shape({
        ...R2_SCHEMA,
        schemaVersion: {
            const: 7
        },
        enabled: {
            type: "boolean"
        },
        features: shape(Object.fromEntries([
            "interactiveRecovery",
            "managedWorkflows",
            "crossProviderFailover",
            "semanticReplanning"
        ].map((k)=>[
                k,
                {
                    type: "boolean"
                }
            ])), [
            "interactiveRecovery",
            "managedWorkflows",
            "crossProviderFailover"
        ]),
        routes: map(shape({
            provider: idSchema,
            model: {
                type: "string",
                minLength: 1,
                maxLength: 512
            },
            accountBinding: idSchema,
            quotaGroup: idSchema,
            transportDomain: idSchema,
            network: idSchema,
            protected: {
                type: "boolean"
            },
            telemetry: idSchema,
            recoveryPolicy: idSchema
        }, [
            "provider",
            "model",
            "accountBinding",
            "quotaGroup",
            "transportDomain",
            "network",
            "protected"
        ])),
        allowedRoutes: names,
        projectRouteApprovals: {
            type: "object",
            additionalProperties: names
        },
        executionProfiles: map(shape({
            tools: names,
            requiredCapabilities: names,
            timeoutMs: timeout,
            maxModelTurns: integer(1),
            toolTimeoutMs: timeout,
            thinking: {
                enum: [
                    "off",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max"
                ]
            },
            minimumContextTokens: integer(1)
        }, [
            "tools",
            "requiredCapabilities",
            "timeoutMs",
            "maxModelTurns",
            "toolTimeoutMs"
        ])),
        roles: map(shape({
            route: idSchema,
            profileRef: idSchema
        })),
        quotaGroups: map(shape({
            classifier: {
                const: "http"
            },
            rules: {
                type: "array",
                items: {
                    ...shape({
                        code: {
                            type: "string",
                            minLength: 1,
                            maxLength: 512
                        },
                        messageIncludes: {
                            type: "string",
                            minLength: 1,
                            maxLength: 512
                        },
                        category: {
                            enum: categories
                        }
                    }, [
                        "category"
                    ]),
                    anyOf: [
                        {
                            required: [
                                "code"
                            ]
                        },
                        {
                            required: [
                                "messageIncludes"
                            ]
                        }
                    ]
                }
            },
            baseIntervalMs: timeout,
            tailIntervalsMs: {
                type: "array",
                items: timeout,
                minItems: 1
            }
        })),
        network: map(shape({
            type: {
                enum: [
                    "direct",
                    "http",
                    "https",
                    "socks5h"
                ]
            },
            endpoint: {
                type: "string",
                minLength: 1,
                maxLength: 2048
            }
        }, [
            "type"
        ])),
        recovery: shape({
            policies: POLICIES_SCHEMA,
            primaryRoute: {
                anyOf: [
                    idSchema,
                    {
                        type: "null"
                    }
                ]
            },
            profileRef: {
                anyOf: [
                    idSchema,
                    {
                        type: "null"
                    }
                ]
            },
            requestTimeoutMs: timeout,
            maxWaitMs: {
                anyOf: [
                    timeout,
                    {
                        type: "null"
                    }
                ]
            },
            positiveJitterRatio: {
                type: "number",
                minimum: 0,
                maximum: 1
            },
            maxNetworkAttempts: integer(),
            lightCanaryEnabled: {
                type: "boolean"
            },
            chain: {
                type: "array",
                items: shape({
                    id: idSchema,
                    route: idSchema,
                    wait: shape({
                        mode: {
                            enum: [
                                "bounded",
                                "forever"
                            ]
                        },
                        maxMs: timeout
                    }, [
                        "mode"
                    ])
                })
            }
        }),
        limits: shape(Object.fromEntries([
            "activeJobsPerRepository",
            "activeChildrenPerHost",
            "parallelReaders",
            "writersPerJob",
            "heavyVerifiersPerHost",
            "semanticAttemptsPerImplementationTask",
            "semanticReplansPerTask",
            "dispatchedStepsPerJob",
            "jobsPerWorkScope",
            "semanticAttemptsPerWorkScope",
            "dispatchedStepsPerWorkScope"
        ].map((k)=>[
                k,
                integer()
            ]))),
        budget: shape({
            backupAttemptsPerIncident: integer(),
            protectedAttemptsPerWorkScope: integer(),
            minimumRequiredStageAttemptReserves: map(integer())
        }),
        scheduling: shape({
            agingMs: timeout,
            priorities: shape({
                inspect: integer(0, MAX_BASE_PRIORITY),
                fix: integer(0, MAX_BASE_PRIORITY)
            })
        }),
        workflow: shape({
            recipes: {
                type: "array",
                items: {
                    enum: [
                        "direct",
                        "critique"
                    ]
                },
                uniqueItems: true
            },
            requiredChecks: shape({
                inspect: names,
                fix: names
            }),
            optionalChecks: shape({
                inspect: names,
                fix: names
            }),
            allowPartial: {
                type: "boolean"
            },
            risk: {
                enum: [
                    "low",
                    "medium",
                    "high",
                    "unknown"
                ]
            },
            reuseReviews: {
                type: "boolean"
            }
        }),
        verificationBindings: map({
            ...shape({
                sharedMutableDirectories: {
                    type: "array",
                    items: {
                        type: "string",
                        minLength: 1
                    },
                    uniqueItems: true
                },
                executable: {
                    type: "string",
                    minLength: 1
                },
                args: {
                    type: "array",
                    items: {
                        type: "string"
                    }
                },
                environment: {
                    type: "object",
                    additionalProperties: {
                        type: "string"
                    }
                },
                timeoutMs: timeout,
                kind: {
                    enum: [
                        "build",
                        "tests"
                    ]
                },
                parser: {
                    enum: [
                        "exit-code",
                        "json",
                        "tap",
                        "pytest"
                    ]
                },
                minimumTests: integer(1),
                requiredTestIds: {
                    type: "array",
                    minItems: 1,
                    maxItems: 4096,
                    uniqueItems: true,
                    items: idSchema
                },
                read_roots: names,
                trusted_inputs: {
                    type: "array",
                    maxItems: 128,
                    uniqueItems: true,
                    items: shape({
                        root_ref: idSchema,
                        relative_path: {
                            type: "string",
                            minLength: 1,
                            maxLength: 4096
                        }
                    })
                },
                inputs: {
                    type: "array",
                    items: {
                        type: "string",
                        minLength: 1
                    },
                    uniqueItems: true
                },
                supervisorExecutable: {
                    type: "string",
                    minLength: 1
                }
            }, [
                "executable",
                "args",
                "environment",
                "timeoutMs",
                "kind",
                "parser",
                "minimumTests"
            ]),
            allOf: [
                {
                    if: {
                        required: [
                            "requiredTestIds"
                        ]
                    },
                    then: {
                        properties: {
                            kind: {
                                const: "tests"
                            },
                            parser: {
                                const: "json"
                            }
                        }
                    }
                }
            ]
        }),
        telemetryBindings: map(shape({
            path: {
                type: "string",
                minLength: 1
            },
            accountBinding: idSchema,
            bucket: idSchema,
            source: idSchema,
            freshnessMs: timeout,
            minimumRemaining: integer(1)
        })),
        advisor: shape({
            mode: {
                const: "off"
            }
        }),
        evidence: shape({
            packetByteBudget: integer(1, 16 * 1024 * 1024)
        }),
        storage: shape({
            path: {
                type: "string",
                minLength: 1,
                maxLength: 4096
            }
        })
    })
};
export const DEFAULT_CONFIG = {
    ...structuredClone(DEFAULT_R2),
    schemaVersion: 7,
    enabled: false,
    features: {
        interactiveRecovery: false,
        managedWorkflows: false,
        crossProviderFailover: false
    },
    routes: {},
    allowedRoutes: [],
    projectRouteApprovals: {},
    executionProfiles: {
        interactive: {
            tools: [
                "read",
                "write",
                "edit",
                "grep",
                "find",
                "ls"
            ],
            requiredCapabilities: [
                "settled",
                "continuationIdentity",
                "termination"
            ],
            timeoutMs: 600000,
            maxModelTurns: 30,
            toolTimeoutMs: 120000
        }
    },
    roles: {},
    quotaGroups: {},
    network: {},
    recovery: {
        policies: {
            defaults: structuredClone(DEFAULT_RETRY_POLICY),
            providers: {},
            legacy: {}
        },
        primaryRoute: null,
        profileRef: "interactive",
        requestTimeoutMs: 120000,
        positiveJitterRatio: 0.2,
        maxWaitMs: null,
        maxNetworkAttempts: 2,
        lightCanaryEnabled: false,
        chain: []
    },
    limits: {
        activeJobsPerRepository: 1,
        activeChildrenPerHost: 3,
        parallelReaders: 2,
        writersPerJob: 1,
        heavyVerifiersPerHost: 1,
        semanticAttemptsPerImplementationTask: 3,
        semanticReplansPerTask: 1,
        dispatchedStepsPerJob: 16,
        jobsPerWorkScope: 16,
        semanticAttemptsPerWorkScope: 3,
        dispatchedStepsPerWorkScope: 16
    },
    budget: {
        backupAttemptsPerIncident: 4,
        protectedAttemptsPerWorkScope: 12,
        minimumRequiredStageAttemptReserves: {}
    },
    scheduling: structuredClone(DEFAULT_SCHEDULING),
    workflow: {
        recipes: [
            "direct"
        ],
        requiredChecks: {
            inspect: [
                "scope-evidence-review"
            ],
            fix: [
                "build",
                "focused-tests",
                "independent-review"
            ]
        },
        optionalChecks: {
            inspect: [],
            fix: []
        },
        allowPartial: false,
        risk: "unknown",
        reuseReviews: true
    },
    verificationBindings: {},
    telemetryBindings: {},
    advisor: {
        mode: "off"
    },
    evidence: {
        packetByteBudget: 65536
    },
    storage: {
        path: "~/.local/state/pi-task-keeper/runtime.db"
    }
};
const ajv = new Ajv({
    allErrors: true,
    strict: false
});
const check = ajv.compile(CONFIG_SCHEMA);
export function configurationPolicy(config) {
    const { evidence: _evidence, usage: _usage, timePolicy: _timePolicy, scheduling = DEFAULT_SCHEDULING, ...policy } = config;
    const features = {
        ...policy.features
    };
    if (features.semanticReplanning !== true) delete features.semanticReplanning;
    const normalized = {
        ...policy,
        features
    };
    return digest(scheduling) === digest(DEFAULT_SCHEDULING) ? normalized : {
        ...normalized,
        scheduling
    };
}
export const configurationPolicyDigest = (config)=>digest(configurationPolicy(config));
export function comparisonPolicyDigest(config) {
    const { modelPolicy: _selection, routes: _catalog, allowedRoutes: _allowed, projectRouteApprovals: _approvals, roles, ...contract } = configurationPolicy(config);
    return digest({
        ...contract,
        roles: Object.fromEntries(Object.entries(roles).map(([role, binding])=>[
                role,
                {
                    profileRef: binding.profileRef
                }
            ]))
    });
}
export function configurationBindingGaps(config) {
    const roleGaps = (names)=>names.flatMap((name)=>{
            const role = config.roles[name];
            if (!role) return [
                `roles.${name}`
            ];
            return config.allowedRoutes.includes(role.route) ? [] : [
                `allowedRoutes:${role.route}`
            ];
        });
    const checks = (workflow)=>{
        const { required, optional, reviewId } = workflowRequirements(config, workflow);
        return [
            ...required,
            ...optional
        ].filter((id)=>id !== reviewId && !config.verificationBindings[id]).map((id)=>`verificationBindings.${id}`);
    };
    const recovery = config.recovery;
    return {
        interactiveRecovery: [
            ...recovery.primaryRoute && !config.allowedRoutes.includes(recovery.primaryRoute) ? [
                "recovery.primaryRoute"
            ] : [],
            ...!recovery.profileRef || !config.executionProfiles[recovery.profileRef] ? [
                "recovery.profileRef"
            ] : []
        ],
        inspect: [
            ...roleGaps([
                "scout",
                "reviewer"
            ]),
            ...checks("inspect")
        ],
        fix: [
            ...roleGaps([
                "worker",
                "reviewer",
                ...config.features.semanticReplanning && config.limits.semanticReplansPerTask > 0 ? [
                    "scout"
                ] : []
            ]),
            ...checks("fix"),
            ...config.limits.writersPerJob === 0 ? [
                "limits.writersPerJob"
            ] : []
        ]
    };
}
function merge(base, patch) {
    if (patch && typeof patch === "object" && !Array.isArray(patch) && base && typeof base === "object" && !Array.isArray(base)) {
        const result = {
            ...base
        };
        for (const [key, value] of Object.entries(patch)){
            if ([
                "__proto__",
                "constructor",
                "prototype"
            ].includes(key)) throw new ContractError("UNKNOWN_FIELD");
            result[key] = merge(result[key], value);
        }
        return result;
    }
    return patch;
}
export function parseConfig(input, validateActivation = true) {
    object(input);
    canonical(input);
    const config = merge(structuredClone(DEFAULT_CONFIG), migrateConfigInput(object(input)));
    if (config.timePolicy?.admissionBoundary === "request-attempt") throw new ContractError("REQUEST_WINDOW_NOT_SUPPORTED");
    if (!check(config)) {
        const requestedMode = config.advisor?.mode;
        if (typeof requestedMode === "string" && [
            "on-demand",
            "shadow",
            "always"
        ].includes(requestedMode)) throw new ContractError("ADVISOR_NOT_IMPLEMENTED");
        throw new ContractError("INVALID_CONFIG", (check.errors ?? []).map((e)=>`${e.instancePath || "/"}: ${e.keyword}`).join("; "));
    }
    validateR2(config);
    for (const id of config.allowedRoutes)if (!config.routes[id]) throw new ContractError("UNKNOWN_ROUTE");
    for (const route of Object.values(config.routes)){
        resolveRecoveryPolicy(config, route, route);
        if (!config.quotaGroups[route.quotaGroup] || !config.network[route.network]) throw new ContractError("INVALID_ROUTE_BINDING");
        if (route.telemetry && !config.telemetryBindings[route.telemetry]) throw new ContractError("INVALID_TELEMETRY_BINDING");
        if (route.accountBinding !== `provider:${route.provider}`) throw new ContractError("UNSUPPORTED_ACCOUNT_BINDING");
    }
    for (const role of Object.values(config.roles)){
        if (!config.routes[role.route] || !config.executionProfiles[role.profileRef]) throw new ContractError("INVALID_ROLE_BINDING");
    }
    const stages = new Set();
    for (const stage of config.recovery.chain){
        if (stages.has(stage.id)) throw new ContractError("INVALID_RECOVERY_CHAIN");
        stages.add(stage.id);
        if (stage.wait.mode === "bounded" !== (stage.wait.maxMs !== undefined)) throw new ContractError("INVALID_STAGE_WAIT");
    }
    for (const kind of [
        "inspect",
        "fix"
    ]){
        if (config.workflow.optionalChecks[kind].some((id)=>config.workflow.requiredChecks[kind].includes(id))) throw new ContractError("OVERLAPPING_CHECKS");
        if (config.workflow.optionalChecks[kind].some((id)=>!config.verificationBindings[id])) throw new ContractError("OPTIONAL_CHECK_BINDING_REQUIRED");
    }
    for (const net of Object.values(config.network)){
        if (net.type === "direct") {
            if (net.endpoint !== undefined) throw new ContractError("INVALID_NETWORK");
        } else {
            try {
                const url = new URL(net.endpoint ?? "");
                if (url.protocol !== `${net.type}:` || url.username || url.password) throw new Error();
            } catch  {
                throw new ContractError("INVALID_NETWORK");
            }
        }
    }
    if (validateActivation && config.enabled && config.features.interactiveRecovery) {
        const { primaryRoute, profileRef } = config.recovery;
        if (primaryRoute && !config.allowedRoutes.includes(primaryRoute) || !profileRef || !config.executionProfiles[profileRef]) {
            throw new ContractError("INTERACTIVE_BINDING_REQUIRED");
        }
    }
    return structuredClone(config);
}
export function applyProjectPolicy(user, input) {
    const patch = object(input, [
        "enabled",
        "features",
        "allowedRoutes",
        "limits",
        "budget",
        "workflow",
        "evidence"
    ]);
    const merged = merge(user, patch);
    for (const kind of [
        "inspect",
        "fix"
    ])if (Array.isArray(merged.workflow?.optionalChecks?.[kind]) && Array.isArray(merged.workflow?.requiredChecks?.[kind])) {
        merged.workflow.optionalChecks[kind] = merged.workflow.optionalChecks[kind].filter((id)=>!merged.workflow.requiredChecks[kind].includes(id));
    }
    const candidate = parseConfig(merged, false);
    const result = structuredClone(user);
    result.enabled = user.enabled && candidate.enabled;
    for (const key of new Set([
        ...Object.keys(user.features),
        ...Object.keys(candidate.features)
    ]))result.features[key] = user.features[key] === true && candidate.features[key] === true;
    result.allowedRoutes = user.allowedRoutes.filter((id)=>candidate.allowedRoutes.includes(id));
    for (const key of Object.keys(user.limits))result.limits[key] = Math.min(user.limits[key], candidate.limits[key]);
    result.budget.backupAttemptsPerIncident = Math.min(user.budget.backupAttemptsPerIncident, candidate.budget.backupAttemptsPerIncident);
    result.budget.protectedAttemptsPerWorkScope = Math.min(user.budget.protectedAttemptsPerWorkScope, candidate.budget.protectedAttemptsPerWorkScope);
    result.evidence.packetByteBudget = Math.min(user.evidence.packetByteBudget, candidate.evidence.packetByteBudget);
    for (const [id, value] of Object.entries(candidate.budget.minimumRequiredStageAttemptReserves)){
        if (![
            ...user.workflow.requiredChecks.inspect,
            ...user.workflow.requiredChecks.fix,
            ...Object.keys(user.verificationBindings)
        ].includes(id)) throw new ContractError("UNTRUSTED_CHECK");
        result.budget.minimumRequiredStageAttemptReserves[id] = Math.max(user.budget.minimumRequiredStageAttemptReserves[id] ?? 0, value);
    }
    result.workflow.allowPartial = user.workflow.allowPartial && candidate.workflow.allowPartial;
    result.workflow.reuseReviews = user.workflow.reuseReviews && candidate.workflow.reuseReviews;
    const riskRank = {
        low: 0,
        medium: 1,
        high: 2,
        unknown: 2
    };
    result.workflow.risk = riskRank[candidate.workflow.risk] > riskRank[user.workflow.risk] ? candidate.workflow.risk : user.workflow.risk;
    result.workflow.recipes = user.workflow.recipes.filter((recipe)=>candidate.workflow.recipes.includes(recipe));
    for (const kind of [
        "inspect",
        "fix"
    ]){
        const trusted = new Set([
            ...user.workflow.requiredChecks.inspect,
            ...user.workflow.requiredChecks.fix,
            ...Object.keys(user.verificationBindings)
        ]);
        if (candidate.workflow.requiredChecks[kind].some((id)=>!trusted.has(id))) throw new ContractError("UNTRUSTED_CHECK");
        result.workflow.requiredChecks[kind] = [
            ...new Set([
                ...user.workflow.requiredChecks[kind],
                ...candidate.workflow.requiredChecks[kind]
            ])
        ];
        if (candidate.workflow.optionalChecks[kind].some((id)=>!trusted.has(id))) throw new ContractError("UNTRUSTED_CHECK");
        result.workflow.optionalChecks[kind] = [
            ...new Set([
                ...user.workflow.optionalChecks[kind],
                ...candidate.workflow.optionalChecks[kind]
            ])
        ].filter((id)=>!result.workflow.requiredChecks[kind].includes(id));
    }
    return result;
}
export function readConfig(userPath, projectPath) {
    const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    if (runtime?.owner?.role === "manager") return parseConfig(fromAgentcfg(DEFAULT_CONFIG, runtime));
    let user;
    try {
        user = existsSync(userPath) ? parseConfig(JSON.parse(readFileSync(userPath, "utf8"))) : structuredClone(DEFAULT_CONFIG);
    } catch (error) {
        if (error instanceof ContractError) throw error;
        throw new ContractError("CONFIG_READ_FAILED");
    }
    if (!projectPath || !existsSync(projectPath)) return user;
    try {
        return applyProjectPolicy(user, JSON.parse(readFileSync(projectPath, "utf8")));
    } catch (error) {
        if (error instanceof ContractError) throw error;
        throw new ContractError("PROJECT_CONFIG_READ_FAILED");
    }
}
export function readConfigForDirectory(userPath, cwd) {
    if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")]?.owner?.role === "manager") return readConfig(userPath);
    const directories = [
        resolve(cwd)
    ];
    let cursor = directories[0];
    while(!existsSync(join(cursor, ".git")) && dirname(cursor) !== cursor){
        cursor = dirname(cursor);
        directories.push(cursor);
    }
    const scope = existsSync(join(cursor, ".git")) ? directories.reverse() : [
        resolve(cwd)
    ];
    let config = readConfig(userPath);
    for (const directory of scope){
        const path = join(directory, ".pi/task-keeper.json");
        if (existsSync(path)) {
            try {
                config = applyProjectPolicy(config, JSON.parse(readFileSync(path, "utf8")));
            } catch (error) {
                if (error instanceof ContractError) throw error;
                throw new ContractError("PROJECT_CONFIG_READ_FAILED");
            }
        }
    }
    return config;
}
export function initializeConfig(path) {
    if (globalThis[Symbol.for("agentcfg.pi.runtime.v1")]) throw new ContractError("AGENTCFG_CONFIGURATION_REQUIRED");
    mkdirSync(dirname(path), {
        recursive: true,
        mode: 0o700
    });
    writeFileSync(path, `${JSON.stringify(DEFAULT_CONFIG, null, 2)}\n`, {
        flag: "wx",
        mode: 0o600
    });
}
export function previewConfigMigration(input) {
    const value = structuredClone(object(input));
    const workflow = value.workflow;
    const removed = workflow?.recipes?.includes("cascade") ? [
        "workflow.recipes:cascade"
    ] : [];
    if (removed.length) workflow.recipes = workflow.recipes.filter((recipe)=>recipe !== "cascade");
    const proposed = parseConfig(value, false);
    return {
        from: object(input).schemaVersion ?? 6,
        to: 7,
        requiresUserEdit: removed.length > 0,
        diagnostics: removed.length ? [
            "CASCADE_REMOVED"
        ] : [],
        removed,
        proposed
    };
}
