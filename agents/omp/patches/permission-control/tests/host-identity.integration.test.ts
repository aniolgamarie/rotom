import { afterEach, describe, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as path from "node:path";
import { registerPermissionControllerCandidate, resolvePermissionController,
	type HostPermissionRegistration } from "../src/permission-control/host";
import { reviewWithFallback } from "../src/permission-control/core/reviewer";
import { handleSessionCommand } from "../src/permission-control/core/session-commands";
import type { NativePermissionControl } from "../src/permission-control/core/types";

const roots: string[] = [];
const identity = "omp-v18.3.0-permission-control-v1-linux-x64-test";

function fixture() {
	const runtime = fs.mkdtempSync(path.join(process.env.HOME!, "permission-runtime-"));
	roots.push(runtime);
	const plugin = path.join(runtime, "packages/omp-permission-control");
	fs.mkdirSync(path.dirname(plugin), { recursive: true, mode: 0o700 });
	const fixtureRoot = path.resolve(import.meta.dir, "../../../permission-test-fixtures");
	fs.cpSync(path.join(fixtureRoot, "plugin"), plugin, { recursive: true, preserveTimestamps: false });
	const entry = path.join(plugin, "index.ts");
	const pluginDigest = fs.readFileSync(path.join(fixtureRoot, "digest.txt"), "utf8").trim();
	const receipt = path.join(runtime, ".agentcfg-receipt.json");
	fs.writeFileSync(receipt, JSON.stringify({
		runtime_variant: "permission-control-v1",
		bridge_abi: "permission-control/v1",
		plugin_digest: pluginDigest,
		identity,
	}), { mode: 0o600 });
	const registration: HostPermissionRegistration = {
		pluginId: "omp-permission-control",
		bridgeAbi: "permission-control/v1",
		review: reviewWithFallback,
		command: handleSessionCommand,
		resolvedPath: entry,
	};
	const config = {
		schemaVersion: 1,
		defaultMode: "smart",
		reviewer: "session",
		bridgeAbi: "permission-control/v1",
		pluginId: "omp-permission-control",
		pluginDigest,
		runtimeIdentity: identity,
		policyVersion: "2".repeat(64),
	} as const satisfies NativePermissionControl;
	return { runtime, plugin, entry, receipt, registration, config, extension: { permissionControllers: [registration] } };
}

afterEach(() => {
	for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

describe("permission controller host identity", () => {
	test("loader helper stores one candidate with host-owned resolved-path provenance", () => {
		const value = fixture();
		const extension = { permissionControllers: [] } as never;
		const { resolvedPath: _, ...registration } = value.registration;
		registerPermissionControllerCandidate(extension, registration, value.entry);
		expect((extension as { permissionControllers: HostPermissionRegistration[] }).permissionControllers).toEqual([
			value.registration,
		]);
		expect(() => registerPermissionControllerCandidate(extension, registration, value.entry))
			.toThrow("PERMISSION_CONTROLLER_REGISTRATION_INVALID");
		const fresh = { permissionControllers: [] } as never;
		expect(() => registerPermissionControllerCandidate(fresh, { ...registration, pluginDigest: "forged" } as never,
			value.entry)).toThrow("PERMISSION_CONTROLLER_REGISTRATION_INVALID");
	});

	test("binds exactly one candidate to the installed entry, complete tree, and receipt", () => {
		const value = fixture();
		expect(resolvePermissionController([value.extension] as never, value.config)).toBe(value.registration);
		expect(resolvePermissionController([value.extension, value.extension] as never, value.config)).toBeUndefined();
		fs.writeFileSync(value.entry, "export default () => 'damaged';\n", { mode: 0o600 });
		expect(resolvePermissionController([value.extension] as never, value.config)).toBeUndefined();
	});

	test("rejects a suffix lookalike, symlinked entry, and symlinked receipt", () => {
		const value = fixture();
		expect(resolvePermissionController([{ permissionControllers: [{ ...value.registration,
			resolvedPath: `${value.entry}.bak` }] }] as never, value.config)).toBeUndefined();
		const linkedEntry = path.join(value.plugin, "linked.ts");
		fs.symlinkSync(value.entry, linkedEntry);
		expect(resolvePermissionController([{ permissionControllers: [{ ...value.registration,
			resolvedPath: linkedEntry }] }] as never, value.config)).toBeUndefined();
		const realReceipt = `${value.receipt}.real`;
		fs.renameSync(value.receipt, realReceipt);
		fs.symlinkSync(realReceipt, value.receipt);
		expect(resolvePermissionController([value.extension] as never, value.config)).toBeUndefined();
	});
});
