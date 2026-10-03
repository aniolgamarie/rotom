import { afterEach, describe, expect, spyOn, test } from "bun:test";
import * as fs from "node:fs";
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { analyzeShell } from "../src/permission-control/core/shell-analysis";
import { buildPermissionReadContext, digestPermissionReadContext } from "../src/permission-control/read-proof";

const DIGEST_A = "1".repeat(64);
const DIGEST_B = "2".repeat(64);
const DIGEST_C = "3".repeat(64);
const roots: string[] = [];

afterEach(() => {
	for (const root of roots.splice(0)) rmSync(root, { force: true, recursive: true });
});

function fixture(): string {
	const root = mkdtempSync(join(tmpdir(), "omp-read-proof-"));
	roots.push(root);
	mkdirSync(join(root, "docs"));
	writeFileSync(join(root, "docs", "a.txt"), "alpha\nbeta\n");
	writeFileSync(join(root, "docs", "b.txt"), "beta\n");
	return root;
}

function build(command: string, cwd: string, overrides: Record<string, unknown> = {}) {
	return buildPermissionReadContext({
		command,
		cwd,
		shellIdentity: DIGEST_A,
		continuityFingerprint: DIGEST_B,
		targetFingerprint: DIGEST_C,
		utilityBuiltinsEnabled: true,
		...overrides,
	});
}

describe("bounded host read proof", () => {
	test("proves a compound builtin-only read without executing it", () => {
		const root = fixture();
		const command = "pwd && ls --color=never docs && head -n 1 docs/a.txt | wc -l";
		let executions = 0;
		const originalSpawn = Bun.spawn;
		Bun.spawn = ((...args: Parameters<typeof Bun.spawn>) => {
			executions++;
			return originalSpawn(...args);
		}) as typeof Bun.spawn;
		const context = build(command, root);
		Bun.spawn = originalSpawn;
		expect(context).toBeDefined();
		expect(executions).toBe(0);
		expect(analyzeShell(new TextEncoder().encode(command), context!)).toMatchObject({
			status: "complete",
			unknowns: [],
		});
		expect(Object.keys(context!.executables).sort()).toEqual(["head", "ls", "pwd", "wc"]);
		expect(context!.targets["docs"]?.targetType).toBe("directory");
		expect(context!.targets["docs/a.txt"]?.targetType).toBe("file");
	});

	test("requires the locked utility builtins but keeps pwd available", () => {
		const root = fixture();
		expect(build("pwd", root, { utilityBuiltinsEnabled: false })).toBeDefined();
		expect(build("pwd && ls docs", root, { utilityBuiltinsEnabled: false })).toBeUndefined();
		expect(build("ls -a docs", root)).toBeUndefined();
		expect(build("ls -l docs", root)).toBeUndefined();
		expect(build("ls -ln docs", root)).toBeDefined();
	});

	test("does not treat a literal filename after -- as an ls option", () => {
		const root = fixture();
		mkdirSync(join(root, "-d"));
		writeFileSync(join(root, "-d", "secret.txt"), "not-read");
		expect(build("ls -- -d", root)).toBeUndefined();
		expect(build("ls docs -d", root)).toBeUndefined();
		rmSync(join(root, "-d", "secret.txt"));
		writeFileSync(join(root, "-d", "visible.txt"), "visible");
		const first = build("ls -- -d", root)!;
		expect(first).toBeDefined();
		writeFileSync(join(root, "-d", "new.txt"), "new");
		expect(digestPermissionReadContext(build("ls -- -d", root)!))
			.not.toBe(digestPermissionReadContext(first));
	});

	test("rejects git and rg directory walks with implicit ignore inputs", () => {
		const root = fixture();
		expect(build("git status --short", root)).toBeUndefined();
		expect(build("rg --fixed-strings beta docs", root)).toBeUndefined();
		expect(build("rg --fixed-strings beta docs/a.txt", root)).toBeDefined();
		expect(build("head -n 1 docs/a.txt | rg --fixed-strings alpha", root)).toBeDefined();
	});

	test("rejects path escape, secrets, symlinks, and unsafe digest input", () => {
		const root = fixture();
		const outside = mkdtempSync(join(tmpdir(), "omp-read-outside-"));
		roots.push(outside);
		writeFileSync(join(outside, "outside.txt"), "outside\n");
		writeFileSync(join(root, ".env.local"), "SECRET=x\n");
		symlinkSync(join(root, "docs", "a.txt"), join(root, "docs", "link.txt"));
		expect(build(`head -n 1 ${join(outside, "outside.txt")}`, root)).toBeUndefined();
		expect(build("head -n 1 .env.local", root)).toBeUndefined();
		expect(build("head -n 1 docs/link.txt", root)).toBeUndefined();
		expect(build("ls docs", root)).toBeUndefined();
		mkdirSync(join(root, "cwd"));
		expect(build("ls cwd", root)).toBeUndefined();
		expect(build("pwd", root, { targetFingerprint: `${DIGEST_C}\n` })).toBeUndefined();
	});

	test("rejects parsed input redirects without mistaking quoted less-than bytes", () => {
		const root = fixture();
		writeFileSync(join(root, "docs", "literal<name"), "literal\n");
		expect(build("pwd < 'cwd'", root)).toBeUndefined();
		expect(build("ls -d < cwd", root)).toBeUndefined();
		expect(build('head -n 1 < "docs/a.txt"', root)).toBeUndefined();
		expect(build("head -n 1 'docs/literal<name'", root)).toBeDefined();
	});

	test("binds directory members and file metadata for final revalidation", () => {
		const root = fixture();
		const command = "ls docs && head -n 1 docs/a.txt";
		const first = build(command, root)!;
		const firstDigest = digestPermissionReadContext(first);
		writeFileSync(join(root, "docs", "c.txt"), "new\n");
		const inserted = build(command, root)!;
		expect(digestPermissionReadContext(inserted)).not.toBe(firstDigest);
		rmSync(join(root, "docs", "c.txt"));
		rmSync(join(root, "docs", "a.txt"));
		expect(build(command, root)).toBeUndefined();
		writeFileSync(join(root, "docs", "a.txt"), "changed-content\n");
		const replaced = build(command, root)!;
		expect(digestPermissionReadContext(replaced)).not.toBe(firstDigest);
	});

	test("bounds recursive trees and marks a small recursive scope", () => {
		const root = fixture();
		mkdirSync(join(root, "tree", "nested"), { recursive: true });
		writeFileSync(join(root, "tree", "nested", "leaf.txt"), "leaf\n");
		const safe = build("ls -Rn tree", root);
		expect(safe?.targets.tree?.recursiveReadVerified).toBe(true);
		for (let index = 0; index < 4100; index++) writeFileSync(join(root, "tree", `entry-${index}`), "x");
		expect(build("ls -Rn tree", root)).toBeUndefined();
	});

	test("shares one operation budget across every target and both scans", () => {
		const root = fixture();
		mkdirSync(join(root, "bulk"));
		const targets: string[] = [];
		for (let index = 0; index < 500; index++) {
			const target = `bulk/file-${index}`;
			writeFileSync(join(root, target), "x");
			targets.push(target);
		}
		expect(build(`head -n 1 ${targets.join(" ")}`, root)).toBeUndefined();
	});

	test("does not bind unrelated ancestor directory timestamps", () => {
		const root = fixture();
		const first = build("pwd", root)!;
		const unrelated = mkdtempSync(join(tmpdir(), "omp-read-unrelated-"));
		roots.push(unrelated);
		const second = build("pwd", root)!;
		expect(digestPermissionReadContext(second)).toBe(digestPermissionReadContext(first));
	});

	test("rejects hidden secret members and control characters", () => {
		const root = fixture();
		writeFileSync(join(root, "docs", "service-credentials.json"), "secret\n");
		expect(build("ls docs", root)).toBeUndefined();
		expect(build("head -n 1 docs/a.txt\u0001", root)).toBeUndefined();
	});

	test("rejects FIFO, socket, and device stat classes without opening them", () => {
		const root = fixture();
		const special = join(root, "docs", "special");
		writeFileSync(special, "fixture");
		const realLstat = fs.lstatSync.bind(fs);
		const statSpy = spyOn(fs, "lstatSync").mockImplementation(((path: fs.PathLike, options?: unknown) => {
			const stat = realLstat(path, options as never);
			if (String(path) !== special) return stat;
			return new Proxy(stat, {
				get(target, property, receiver) {
					if (property === "isFile" || property === "isDirectory" || property === "isSymbolicLink")
						return () => false;
					return Reflect.get(target, property, receiver);
				},
			});
		}) as typeof fs.lstatSync);
		try {
			expect(build("head -n 1 docs/special", root)).toBeUndefined();
		} finally {
			statSpy.mockRestore();
		}
	});
});
