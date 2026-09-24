import { readFileSync, writeFileSync, mkdirSync, lstatSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { ContractError, digest, identifier } from "../contracts/primitives.ts";
import { Store } from "./database.ts";

export interface Artifact {
  id: string; jobId: string; snapshot: string; contentDigest: string; bytes: number;
  source: "runtime" | "verifier" | "claim";
}

export class Artifacts {
  private store: Store;
  private root: string;
  constructor(store: Store) {
    this.store = store; this.root = join(store.root, "artifacts");
    mkdirSync(this.root, { recursive: true, mode: 0o700 });
    if (lstatSync(this.root).isSymbolicLink()) throw new ContractError("ARTIFACT_DIRECTORY_INVALID");
  }
  pin(jobId: string, snapshot: string, content: string | Uint8Array, source: Artifact["source"]): Artifact {
    identifier(jobId); identifier(snapshot);
    const data = Buffer.from(content);
    const contentDigest = createHash("sha256").update(data).digest("hex");
    const artifact: Artifact = { id: `artifact-${digest([jobId, snapshot, source, contentDigest])}`,
      jobId, snapshot, contentDigest, bytes: data.length, source };
    const path = join(this.root, artifact.id);
    try { writeFileSync(path, data, { flag: "wx", mode: 0o600 }); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      if (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink()
        || createHash("sha256").update(readFileSync(path)).digest("hex") !== contentDigest) throw new ContractError("ARTIFACT_CONFLICT");
    }
    this.store.put("artifacts", artifact.id, artifact);
    return artifact;
  }
  read(id: string, jobId: string, snapshot: string): { artifact: Artifact; content: Buffer } {
    identifier(id);
    const artifact = this.store.get<Artifact>("artifacts", id);
    if (!artifact || artifact.jobId !== jobId || artifact.snapshot !== snapshot) throw new ContractError("ARTIFACT_SCOPE_MISMATCH");
    const path = join(this.root, artifact.id);
    try {
      if (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink()) throw new Error();
      const content = readFileSync(path);
      if (content.length !== artifact.bytes || createHash("sha256").update(content).digest("hex") !== artifact.contentDigest) throw new Error();
      return { artifact, content };
    } catch { throw new ContractError("ARTIFACT_MISSING_OR_CHANGED"); }
  }
}
