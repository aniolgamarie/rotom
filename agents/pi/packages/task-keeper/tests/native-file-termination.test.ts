import { test, assert } from "./recorded-test.ts";
import { createWriteToolDefinition, createEditToolDefinition } from "@earendil-works/pi-coding-agent";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { writeFile, readFile, mkdir, access } from "node:fs/promises";
import { join } from "node:path";
import { setImmediate as flush } from "node:timers/promises";
import { isolatedDirectory, barrier } from "./helpers.ts";

for (const kind of ["write", "edit"] as const) test(`[A] native ${kind} keeps an in-flight file mutation owned until physical completion after abort`, async t => {
  const root = isolatedDirectory(t), path = join(root, "source.txt"); await writeFile(path, "old");
  const started = barrier(), release = barrier(); const effects: string[] = [];
  let calls = 0;
  const operations = { mkdir: async (dir: string) => { await mkdir(dir, { recursive: true }); },
    readFile: (path: string) => readFile(path), access: (path: string) => access(path),
    writeFile: async (path: string, content: string) => {
      calls++; if (calls === 1) { started.resolve(); await release.promise; }
      await writeFile(path, content); effects.push(content);
    } };
  const tool = kind === "write" ? createWriteToolDefinition(root, { operations }) : createEditToolDefinition(root, { operations });
  const abort = new AbortController(); let ended = false;
  const execute = tool.execute as unknown as (id: string, args: unknown, signal: AbortSignal, update: undefined, ctx: ExtensionContext) => Promise<unknown>;
  const first = execute("first", kind === "write" ? { path: "source.txt", content: "first" } : { path: "source.txt", edits: [{ oldText: "old", newText: "first" }] }, abort.signal, undefined, {} as ExtensionContext)
    .then(() => { ended = true; return null; }, error => { ended = true; return error; });
  await started.promise; abort.abort(); await flush();
  assert.equal(ended, false); assert.deepEqual(effects, []);
  const second = execute("second", kind === "write" ? { path: "source.txt", content: "second" } : { path: "source.txt", edits: [{ oldText: "first", newText: "second" }] }, new AbortController().signal, undefined, {} as ExtensionContext);
  await flush(); assert.equal(calls, 1); assert.equal(ended, false);
  release.resolve(); assert.match(String(await first), /abort/i); await second;
  assert.deepEqual(effects, ["first", "second"]); assert.equal(await readFile(path, "utf8"), "second");
});
