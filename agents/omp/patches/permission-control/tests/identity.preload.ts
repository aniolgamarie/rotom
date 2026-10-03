import { mock } from "bun:test";
import * as childProcess from "node:child_process";

globalThis.fetch = (() => {
	throw new Error("NETWORK_DISABLED_BY_PERMISSION_CONTROL_TEST");
}) as unknown as typeof fetch;

globalThis.Worker = class DisabledWorker {
	constructor(..._args: ConstructorParameters<typeof Worker>) {
		throw new Error("WORKER_DISABLED_BY_PERMISSION_CONTROL_TEST");
	}
} as unknown as typeof Worker;

const processDisabled = () => {
	throw new Error("PROCESS_DISABLED_BY_PERMISSION_CONTROL_TEST");
};
Bun.spawn = processDisabled as unknown as typeof Bun.spawn;
Bun.spawnSync = processDisabled as unknown as typeof Bun.spawnSync;
mock.module("node:child_process", () => ({
	...childProcess,
	exec: processDisabled,
	execFile: processDisabled,
	execFileSync: processDisabled,
	execSync: processDisabled,
	fork: processDisabled,
	spawn: processDisabled,
	spawnSync: processDisabled,
}));
