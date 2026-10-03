import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const FROZEN_DIGEST = "4e7df262ccefc32c816317d47ffdf9336fb880c15f7c7a87e3b68ac2f0d127b6";
// 保留原生成器真实顺序；FROZEN.md 的 lexicographic 字样有误，见验收记录勘误。
export const FROZEN_PATHS = ["fixture-schema.json", "cases.jsonl", "labels.json"] as const;
export function verifyFrozenBytes(files: Readonly<Record<typeof FROZEN_PATHS[number], Uint8Array>>): string {
  const hash = createHash("sha256");
  for (const name of FROZEN_PATHS) {
    hash.update(name); hash.update("\0"); hash.update(files[name]); hash.update("\0");
  }
  const digest = hash.digest("hex");
  if (digest !== FROZEN_DIGEST) throw new Error("FROZEN_FIXTURE_IDENTITY_CHANGED");
  return digest;
}

/** 仅读取固定文件，不执行任何 action.command；身份先于 JSON 解析。 */
export function readFrozenFixture(directory: string): { digest: string; cases: readonly unknown[]; labels: unknown } {
  const files = {
    "fixture-schema.json": readFileSync(join(directory, "fixture-schema.json")),
    "cases.jsonl": readFileSync(join(directory, "cases.jsonl")),
    "labels.json": readFileSync(join(directory, "labels.json")),
  };
  const digest = verifyFrozenBytes(files);
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const lines = decoder.decode(files["cases.jsonl"]).trimEnd().split("\n");
  if (lines.length !== 240) throw new Error("FROZEN_FIXTURE_IDENTITY_CHANGED");
  return { digest, cases: lines.map(line => JSON.parse(line)), labels: JSON.parse(decoder.decode(files["labels.json"])) };
}
