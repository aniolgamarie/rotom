import { beforeAll, describe, expect, mock, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

type NativeCounters = {
	shellConstruct: number;
	shellRun: number;
	shellAbort: number;
	process: number;
	worker: number;
	network: number;
	mkdir: number;
	snapshot: number;
	envLoad: number;
	service: number;
	job: number;
	requests: Array<Record<string, unknown>>;
};

type KernelEvidence = {
	snapshotMode: "blocked" | "ready";
	snapshotPath: string;
	snapshotDigest: string;
	generationInputsDigest: string;
	optionsDigest: string;
	optionsKnownSafe: boolean;
	shadowedNames: string[];
	continuityTracked: boolean;
	mutationGeneration: number;
	direnvSearchComplete: boolean;
	direnvHasEffectiveConfig: boolean;
	direnvSearchChainFingerprint: string;
	deferRun: boolean;
	outputChunk: string;
};

type RenderedFixture = {
	config: Record<string, unknown>;
	expected: {
		bridgeAbi: string;
		pluginDigest: string;
		runtimeIdentity: string;
	};
};
type SettingsInstance = import("../src/config/settings").Settings;

let fixture: RenderedFixture;
const native = (globalThis as typeof globalThis & { __ompBridgeNativeMock: NativeCounters }).__ompBridgeNativeMock;
let kernelEvidence: KernelEvidence;

// This test must preserve the rendered `bash.direnv=auto` setting without
// running direnv. Replace only the preload's throwing async boundary before
// BashTool imports it; the synchronous search-chain proof remains unchanged.
const preloadDirenv = await import("../src/exec/direnv");
mock.module(import.meta.resolve("../src/exec/direnv"), () => ({
	...preloadDirenv,
	loadDirenvEnv: async () => {
		native.envLoad += 1;
		return null;
	},
}));

const { ExtensionToolWrapper } = await import("../src/extensibility/extensions/wrapper");
const { Settings, validatePermissionControlSetting } = await import("../src/config/settings");
const { BashTool } = await import("../src/tools/bash");
const bridge = await import("../src/permission-control/bridge");

beforeAll(() => {
	fixture = JSON.parse(
		readFileSync(join(process.cwd(), "permission-test-fixtures", "rendered-kernel.json"), "utf8"),
	) as RenderedFixture;
	kernelEvidence = (globalThis as typeof globalThis & { __ompBridgeKernelEvidence: KernelEvidence })
		.__ompBridgeKernelEvidence;
});

function runner(settings: SettingsInstance, approve: () => void) {
	return {
		sessionId: "rendered-kernel-session",
		sessionSettings: settings,
		consumeToolCallEmitted: () => false,
		hasHandlers: () => false,
		hasUI: () => true,
		getUIContext: () => ({
			select: async () => {
				approve();
				return "Approve";
			},
		}),
		runScoped: (call: () => unknown) => call(),
	};
}

describe("manager-rendered kernel permission bridge", () => {
	test("the exact generated object survives host schema and controls native Bash coverage", async () => {
		const permission = validatePermissionControlSetting(fixture.config.permissionControl);
		if (fixture.expected.bridgeAbi !== bridge.BRIDGE_ABI) throw new Error("RENDERED_KERNEL_BRIDGE_ABI_MISMATCH");
		const settings = Settings.isolated(fixture.config as never);
		expect(settings.get("permissionControl")).toEqual(permission);
		expect(permission).toMatchObject({
			defaultMode: "smart",
			reviewer: "session",
			fallback: { provider: "local", model: "lfm2.5-230m", installedOnly: true },
			bridgeAbi: bridge.BRIDGE_ABI,
			pluginId: "omp-permission-control",
			pluginDigest: fixture.expected.pluginDigest,
			runtimeIdentity: fixture.expected.runtimeIdentity,
		});
		expect(fixture.expected.bridgeAbi).toBe(bridge.BRIDGE_ABI);
		expect(permission.pluginDigest).toBe(
			readFileSync(join(process.cwd(), "permission-test-fixtures", "digest.txt"), "utf8").trim(),
		);
		expect(() =>
			Settings.isolated({
				...fixture.config,
				permissionControl: { ...(fixture.config.permissionControl as object), unexpected: true },
			} as never).get("permissionControl"),
		).toThrow("PERMISSION_CONTROL_INVALID:permissionControl:UNKNOWN_FIELD");

		const approvals = settings.get("tools.approval");
		expect(approvals).toMatchObject({ bash: "prompt", task: "prompt", eval: "prompt" });
		expect(settings.get("bash.direnv")).toBe("auto");
		expect(settings.get("bashInterceptor.enabled")).toBe(true);
		expect(settings.get("bash.autoBackground.enabled")).toBe(true);
		expect(settings.get("bash.allowCompoundCommands")).toBe(true);

		const cwd = process.env.HOME!;
		const session = {
			settings,
			cwd,
			getSessionId: () => "rendered-kernel-session",
			getSessionFile: () => undefined,
			getImageAttachments: () => [],
		};
		const tool = new BashTool(session as never);
		expect(
			tool.permissionControlNativeConstraint({ command: "pwd", cwd }, {
				tier: "exec",
				policy: "prompt",
				source: "tool",
			} as never),
		).toEqual({ source: "tool-default", policy: "prompt" });
		expect(
			tool.permissionControlNativeConstraint({ command: "rm -rf /", cwd }, {
				tier: "exec",
				policy: "prompt",
				source: "tool",
			} as never),
		).toEqual({ source: "explicit-deny", policy: "deny" });

		const adapter = tool.permissionControlExecution.adapter;
		const coldRequest = {
			requestId: "rendered-cold",
			sessionId: "rendered-kernel-session",
			generation: tool.permissionControlExecution.generation(),
			args: { command: "pwd", cwd },
			toolNames: ["read"],
		};
		const cold = bridge.prepareBashExecution(adapter, coldRequest as never);
		expect(cold.coverage_state).toBe("manual-required");
		expect(cold.coverage_reasons).toContain("startup-script");
		expect(cold.coverage_reasons).toContain("direnv");
		expect(cold.coverage_reasons).not.toContain("interceptor");
		expect(cold.coverage_reasons).not.toContain("auto-background");
		expect(native).toMatchObject({
			shellConstruct: 0,
			shellRun: 0,
			process: 0,
			worker: 0,
			network: 0,
			snapshot: 0,
			envLoad: 0,
			service: 0,
			job: 0,
		});

		kernelEvidence.snapshotMode = "ready";
		kernelEvidence.direnvSearchComplete = true;
		kernelEvidence.direnvHasEffectiveConfig = false;
		let manualApprovals = 0;
		const wrapper = new ExtensionToolWrapper(
			tool as never,
			runner(settings, () => {
				manualApprovals++;
			}) as never,
		);
		const originalSettingsInit = Settings.init;
		(Settings as unknown as { init: typeof Settings.init }).init = async () => settings;
		try {
			await wrapper.execute("rendered-warm", { command: "pwd", cwd } as never);
		} finally {
			(Settings as unknown as { init: typeof Settings.init }).init = originalSettingsInit;
		}
		expect(manualApprovals).toBe(1);
		expect(native.shellRun).toBe(1);
		expect(native.network).toBe(0);
		expect(native.process).toBe(0);
		expect(native.envLoad).toBe(1);
		expect(settings.get("bash.direnv")).toBe("auto");

		const warm = bridge.prepareBashExecution(adapter, {
			...coldRequest,
			requestId: "rendered-warm-proof",
			generation: tool.permissionControlExecution.generation(),
		} as never);
		expect(warm.coverage_reasons).toEqual([]);
		expect(warm.coverage_state).toBe("eligible");
		expect(native.shellRun).toBe(1);
	});
});
