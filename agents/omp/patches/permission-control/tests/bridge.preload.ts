import { mock } from "bun:test";
import * as childProcess from "node:child_process";
import * as fs from "node:fs";

type RunRequest = {
	command: string;
	cwd?: string;
	env?: Record<string, string>;
	timeoutMs?: number;
	signal?: AbortSignal;
};

const counters = {
	shellConstruct: 0,
	shellRun: 0,
	shellAbort: 0,
	process: 0,
	worker: 0,
	network: 0,
	mkdir: 0,
	snapshot: 0,
	envLoad: 0,
	service: 0,
	job: 0,
	requests: [] as RunRequest[],
};

const kernelEvidence = {
	snapshotMode: "blocked" as "blocked" | "ready",
	snapshotPath: "/virtual/omp-shell-snapshot",
	snapshotDigest: "3".repeat(64),
	generationInputsDigest: "4".repeat(64),
	optionsDigest: "5".repeat(64),
	optionsKnownSafe: true,
	shadowedNames: [] as string[],
	continuityTracked: true,
	mutationGeneration: 0,
	direnvSearchComplete: false,
	direnvHasEffectiveConfig: false,
	direnvSearchChainFingerprint: "6".repeat(64),
	deferRun: false,
	outputChunk: "native-output\n",
};

Object.assign(globalThis, {
	__ompBridgeNativeMock: counters,
	__ompBridgeKernelEvidence: kernelEvidence,
	__ompBridgeFetchMock: undefined,
});

globalThis.fetch = (async (input: Parameters<typeof fetch>[0], init?: Parameters<typeof fetch>[1]) => {
	const handler = (
		globalThis as typeof globalThis & {
			__ompBridgeFetchMock?: (
				input: Parameters<typeof fetch>[0],
				init?: Parameters<typeof fetch>[1],
			) => Promise<Response> | Response;
		}
	).__ompBridgeFetchMock;
	if (handler) {
		counters.service += 1;
		return handler(input, init);
	}
	counters.network += 1;
	throw new Error("NETWORK_DISABLED_BY_PERMISSION_CONTROL_TEST");
}) as typeof fetch;

globalThis.Worker = class DisabledWorker {
	constructor(..._args: ConstructorParameters<typeof Worker>) {
		counters.worker += 1;
		throw new Error("WORKER_DISABLED_BY_PERMISSION_CONTROL_TEST");
	}
} as unknown as typeof Worker;

const originalSpawn = Bun.spawn;
const originalSpawnSync = Bun.spawnSync;
const originalWrite = Bun.write;
Bun.spawn = ((..._args: Parameters<typeof Bun.spawn>) => {
	counters.process += 1;
	throw new Error("PROCESS_DISABLED_BY_PERMISSION_CONTROL_TEST");
}) as unknown as typeof Bun.spawn;
Bun.spawnSync = ((..._args: Parameters<typeof Bun.spawnSync>) => {
	counters.process += 1;
	throw new Error("PROCESS_DISABLED_BY_PERMISSION_CONTROL_TEST");
}) as unknown as typeof Bun.spawnSync;
Bun.write = ((..._args: Parameters<typeof Bun.write>) => {
	counters.mkdir += 1;
	throw new Error("WRITE_DISABLED_BY_PERMISSION_CONTROL_TEST");
}) as unknown as typeof Bun.write;

const disabledChildProcess = (..._args: unknown[]) => {
	counters.process += 1;
	throw new Error("CHILD_PROCESS_DISABLED_BY_PERMISSION_CONTROL_TEST");
};
mock.module("node:child_process", () => ({
	...childProcess,
	exec: disabledChildProcess,
	execFile: disabledChildProcess,
	execFileSync: disabledChildProcess,
	execSync: disabledChildProcess,
	fork: disabledChildProcess,
	spawn: disabledChildProcess,
	spawnSync: disabledChildProcess,
}));

mock.module("node:fs", () => ({
	...fs,
	mkdirSync: (...args: Parameters<typeof fs.mkdirSync>) => {
		counters.mkdir += 1;
		const target = String(args[0]);
		const temporaryHome = process.env.HOME;
		if (temporaryHome && (target === temporaryHome || target.startsWith(`${temporaryHome}/`))) {
			return fs.mkdirSync(...args);
		}
		throw new Error("MKDIR_DISABLED_BY_PERMISSION_CONTROL_TEST");
	},
	promises: {
		...fs.promises,
		mkdir: (...args: Parameters<typeof fs.promises.mkdir>) => {
			counters.mkdir += 1;
			const target = String(args[0]);
			const temporaryHome = process.env.HOME;
			if (temporaryHome && (target === temporaryHome || target.startsWith(`${temporaryHome}/`))) {
				return fs.promises.mkdir(...args);
			}
			return Promise.reject(new Error("MKDIR_DISABLED_BY_PERMISSION_CONTROL_TEST"));
		},
	},
}));

const actualShellSnapshot = await import("../src/utils/shell-snapshot");
mock.module(import.meta.resolve("../src/utils/shell-snapshot"), () => ({
	...actualShellSnapshot,
	getOrCreateSnapshot: async () => {
		counters.snapshot += 1;
		if (kernelEvidence.snapshotMode === "ready") return kernelEvidence.snapshotPath;
		throw new Error("SNAPSHOT_DISABLED_BY_PERMISSION_CONTROL_TEST");
	},
	inspectPermissionControlSnapshot: () => ({
		source: "host-generated",
		snapshotPath: kernelEvidence.snapshotPath,
		snapshotDigest: kernelEvidence.snapshotDigest,
		generationInputsDigest: kernelEvidence.generationInputsDigest,
		optionsDigest: kernelEvidence.optionsDigest,
		optionsKnownSafe: kernelEvidence.optionsKnownSafe,
		shadowedNames: [...kernelEvidence.shadowedNames],
		continuityTracked: kernelEvidence.continuityTracked,
		mutationGeneration: kernelEvidence.mutationGeneration,
	}),
	sanitizeSnapshotForBrush: (content: string) => ({ content, dropped: [] }),
}));
mock.module(import.meta.resolve("../src/exec/direnv"), () => ({
	loadDirenvEnv: async () => {
		counters.envLoad += 1;
		throw new Error("DIRENV_DISABLED_BY_PERMISSION_CONTROL_TEST");
	},
	inspectPermissionControlDirenvSearchChain: () => ({
		complete: kernelEvidence.direnvSearchComplete,
		hasEffectiveConfig: kernelEvidence.direnvHasEffectiveConfig,
		searchChainFingerprint: kernelEvidence.direnvSearchChainFingerprint,
	}),
}));
mock.module(import.meta.resolve("../src/launch/services"), () => ({
	findService: disabledChildProcess,
	hasLiveOwnedService: () => false,
	listServices: disabledChildProcess,
	modeService: disabledChildProcess,
	renderServiceLogTerminalRows: disabledChildProcess,
	sendService: disabledChildProcess,
	serviceLogPath: disabledChildProcess,
	serviceLogs: disabledChildProcess,
	serviceLogsWithRows: disabledChildProcess,
	serviceStatus: disabledChildProcess,
	startService: async () => {
		counters.service += 1;
		throw new Error("SERVICE_DISABLED_BY_PERMISSION_CONTROL_TEST");
	},
	stopService: disabledChildProcess,
	waitForOwnedServiceCompletion: disabledChildProcess,
}));

class FakeShell {
	constructor(_options?: unknown) {
		counters.shellConstruct += 1;
	}

	run(request: RunRequest, onChunk: (error: Error | null, chunk: string) => void) {
		counters.shellRun += 1;
		counters.requests.push({ ...request, env: request.env ? { ...request.env } : undefined });
		onChunk(null, kernelEvidence.outputChunk);
		if (kernelEvidence.deferRun) {
			return new Promise(resolve => {
				request.signal?.addEventListener(
					"abort",
					() => resolve({ exitCode: undefined, cancelled: true, timedOut: false, workingDir: request.cwd }),
					{ once: true },
				);
			});
		}
		return Promise.resolve({
			exitCode: 0,
			cancelled: false,
			timedOut: false,
			workingDir: request.cwd,
		});
	}

	abort() {
		counters.shellAbort += 1;
		return Promise.resolve();
	}

	liveBackgroundJobCount() {
		return Promise.resolve(0);
	}
}

class DisabledNative {
	constructor(..._args: unknown[]) {
		throw new Error("NATIVE_PATH_DISABLED_BY_PERMISSION_CONTROL_TEST");
	}
}

const noNative = () => {
	throw new Error("NATIVE_PATH_DISABLED_BY_PERMISSION_CONTROL_TEST");
};

const nativeExports = {
	Shell: FakeShell,
	PtySession: DisabledNative,
	Process: DisabledNative,
	ProcessStatus: Object.freeze({}),
	FileLock: DisabledNative,
	TtyWriter: DisabledNative,
	AudioCapture: DisabledNative,
	AudioPlayback: DisabledNative,
	LiveWebRtcPeer: DisabledNative,
	DiffStream: DisabledNative,
	EditStore: DisabledNative,
	PowerAssertion: DisabledNative,
	AstMatchStrictness: Object.freeze({}),
	Encoding: Object.freeze({}),
	FileType: Object.freeze({}),
	GrepOutputMode: Object.freeze({}),
	DiffSide: Object.freeze({}),
	Ellipsis: Object.freeze({}),
	glob: noNative,
	grep: noNative,
	fuzzyFind: noNative,
	executeShell: noNative,
	execReplace: noNative,
	editInspect: noNative,
	astMatch: noNative,
	astEdit: noNative,
	astGrep: noNative,
	countTokens: noNative,
	diffWords: noNative,
	diffLineRuns: noNative,
	editDiffString: noNative,
	structuredPatchHunks: noNative,
	summarizeCode: noNative,
	renderMermaidAscii: noNative,
	rasterizeSvg: noNative,
	encodeSixel: noNative,
	decodeSixelToPng: noNative,
	invalidateFsScanCache: noNative,
	listWorkspace: noNative,
	extractInlineSloppyRegions: noNative,
	editAutoGeneratedMessage: noNative,
	notebookToEditableText: noNative,
	htmlToMarkdown: noNative,
	pdfToMarkdown: noNative,
	getWorkProfile: noNative,
	deviceCheckGenerateToken: noNative,
	detectMacOSAppearance: noNative,
	MacAppearanceObserver: DisabledNative,
	appleFmAvailability: noNative,
	appleFmCancel: noNative,
	appleFmGenerate: noNative,
	NativeOAuthCallback: DisabledNative,
	matchesKey: noNative,
	parseKey: noNative,
	parseKittySequence: noNative,
	setHangulCompatJamoWidthOverride: noNative,
	extractSegments: noNative,
	hashlineFileHash: noNative,
	hashlineFormatHeader: noNative,
	hashlineFormatNumberedLines: noNative,
	hashlineIsReadTruncationNotice: noNative,
	hashlineStripPrefixes: noNative,
	highlightCode: noNative,
	supportsLanguage: noNative,
	warmHighlighter: noNative,
	sliceByColumn: noNative,
	sliceWithWidth: noNative,
	truncateToWidth: noNative,
	truncateVisualWidth: noNative,
	visibleWidth: (value: string) => value.length,
	wrapTextWithAnsi: noNative,
	HighlightStream: DisabledNative,
	Hasher: DisabledNative,
	renderSnapcompactPng: noNative,
	snapcompactSupportedChars: noNative,
};

mock.module("@oh-my-pi/pi-natives", () => nativeExports);
mock.module(import.meta.resolve("@oh-my-pi/pi-natives"), () => nativeExports);

process.on("exit", () => {
	Bun.spawn = originalSpawn;
	Bun.spawnSync = originalSpawnSync;
	Bun.write = originalWrite;
});
