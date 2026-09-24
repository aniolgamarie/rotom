import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, lstatSync, realpathSync, readlinkSync, copyFileSync, symlinkSync, existsSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { ContractError, digest, identifier } from "../contracts/primitives.ts";

export interface SourceFile { path: string; kind: "file" | "symlink" | "missing"; hash: string | null; executable: number }
export interface SourceSnapshot { id: string; root: string; commit: string; files: SourceFile[] }
const git = (cwd: string, args: string[], input?: Buffer): Buffer => execFileSync(process.env.AGENTCFG_GIT_EXECUTABLE ?? "/usr/bin/git", ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-C", cwd, ...args], {
  env: { PATH: "/usr/bin:/bin", HOME: process.env.HOME, LANG: "C.UTF-8", GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" },
  input, maxBuffer: 32 * 1024 * 1024, stdio: ["pipe", "pipe", "pipe"],
});
const listed = (cwd: string, args: string[]): string[] => git(cwd, ["ls-files", ...args, "-z"]).toString("utf8").split("\0").filter(Boolean);
const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");

function inside(root: string, path: string): boolean { return path === root || path.startsWith(root + sep); }
function relativeInput(root: string, input: string): string {
  const absolute = resolve(root, input);
  if (!inside(root, absolute) || absolute === root) throw new ContractError("INPUT_OUTSIDE_WORKSPACE");
  return relative(root, absolute);
}

function protectedPaths(root: string, explicit: string[] = []): string[] {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  const paths = [...explicit, ...(runtime?.owner?.protected_roots ?? [])];
  const state = runtime?.instanceRoot ? join(runtime.instanceRoot, "pi-home/task-keeper") : null;
  if (state && inside(join(state, "worktrees"), root)) {
    const id = relative(join(state, "worktrees"), root).split(sep)[0];
    identifier(id);
    const path = join(state, "workspace-protection", id + ".json");
    if (existsSync(path)) {
      const record = JSON.parse(readFileSync(path, "utf8"));
      if (record.schema_version !== 1 || !inside(record.candidate_root, root) || !Array.isArray(record.paths)) throw new ContractError("WORKSPACE_PROTECTION_INVALID");
      paths.push(...record.paths);
    }
  }
  return [...new Set(paths.map(path => resolve(path)))].filter(path => inside(root, path));
}

function ownedPaths(root: string): string[] {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime?.instanceRoot) return [];
  const state = join(runtime.instanceRoot, "pi-home/task-keeper"), worktrees = join(state, "worktrees");
  if (!inside(worktrees, root)) return [];
  const id = relative(worktrees, root).split(sep)[0]; identifier(id);
  const file = join(state, "workspace-protection", id + ".json");
  if (!existsSync(file)) return [];
  const record = JSON.parse(readFileSync(file, "utf8"));
  return record.owned_paths ?? [];
}

export function sourceSnapshot(cwd: string, extraInputs: string[] = [], privatePaths: string[] = []): SourceSnapshot {
  const root = realpathSync(git(cwd, ["rev-parse", "--show-toplevel"]).toString("utf8").replace(/\r?\n$/, ""));
  const commit = git(root, ["rev-parse", "--verify", "HEAD"]).toString("utf8").trim();
  const committed = git(root, ["ls-tree", "-r", "--name-only", "-z", "HEAD"]).toString("utf8").split("\0").filter(Boolean);
  const paths = [...new Set([...committed, ...listed(root, ["--cached", "--others", "--exclude-standard"]), ...extraInputs.map((p) => relativeInput(root, p)), ...ownedPaths(root)])].sort();
  const protectedRoots = protectedPaths(root, privatePaths);
  const files = paths.filter(path => !protectedRoots.some(secret => inside(secret, join(root, path)))).map((path): SourceFile => {
    const full = join(root, relativeInput(root, path));
    let info;
    try { info = lstatSync(full); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { path, kind: "missing", hash: null, executable: 0 };
      throw error;
    }
    if (info.isSymbolicLink()) {
      const target = realpathSync(full);
      if (!inside(root, target) || !lstatSync(target).isFile()) throw new ContractError("UNBOUND_SYMLINK_INPUT");
      return { path, kind: "symlink", hash: sha(readlinkSync(full)), executable: info.mode & 0o111 };
    }
    if (!info.isFile() || !inside(root, realpathSync(dirname(full)))) throw new ContractError("UNBOUND_DIRECTORY_INPUT");
    return { path, kind: "file", hash: sha(readFileSync(full)), executable: info.mode & 0o111 };
  });
  return { id: `tree-${digest({ commit, files })}`, root, commit, files };
}

export function workspaceResource(cwd: string): string { return `workspace-${digest(realpathSync(cwd))}`; }
export function repositoryResource(cwd: string): string {
  const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).toString("utf8").trim();
  return `repository-${digest(realpathSync(common))}`;
}
export function projectReference(cwd: string): string {
  try { return repositoryResource(cwd); }
  catch { return `directory-${digest(realpathSync(cwd))}`; }
}

/** A private object/index store retains precise input/candidate trees without committing to user branches. */
export function captureTree(cwd: string, stateRoot: string, jobId: string, extraInputs: string[] = [], privatePaths: string[] = []): { tree: string; gitDir: string } {
  identifier(jobId); if (jobId === "." || jobId === "..") throw new ContractError("INVALID_WORKSPACE_ID");
  const directory = join(stateRoot, "snapshots", `${jobId}.git`);
  if (!existsSync(directory)) {
    mkdirSync(dirname(directory), { recursive: true, mode: 0o700 });
    git(cwd, ["init", "--bare", directory]);
    const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]).toString("utf8").replace(/\r?\n$/, "");
    const objects = join(common, "objects");
    if (!/[\r\n]/.test(objects)) writeFileSync(join(directory, "objects/info/alternates"), `${objects}\n`, { mode: 0o600 });
  }
  const args = ["--git-dir", directory, "--work-tree", realpathSync(cwd)];
  const files = sourceSnapshot(cwd, extraInputs, privatePaths).files.filter(file => file.kind !== "missing").map(file => file.path);
  git(cwd, [...args, "read-tree", "--empty"]);
  for (let offset = 0; offset < files.length; offset += 100) git(cwd, [...args, "add", "-f", "--", ...files.slice(offset, offset + 100)]);
  const tree = git(cwd, [...args, "write-tree"]).toString("utf8").trim();
  git(cwd, [...args, "update-ref", `refs/task-keeper/${tree}`, tree]);
  return { tree, gitDir: directory };
}

export function treeDiff(cwd: string, gitDir: string, from: string, to: string): string {
  if (!/^[a-f0-9]{40,64}$/.test(from) || !/^[a-f0-9]{40,64}$/.test(to)) throw new ContractError("INVALID_TREE_ID");
  return git(cwd, ["--git-dir", gitDir, "diff", "--binary", from, to, "--"]).toString("utf8");
}

/** Copies a stable source snapshot into a persistent worktree; it never stashes or resets the source. */
export function createWorkspace(repository: string, stateRoot: string, jobId: string, extraInputs: string[] = [], privatePaths: string[] = []) {
  identifier(jobId);
  if (jobId === "." || jobId === "..") throw new ContractError("INVALID_WORKSPACE_ID");
  const before = sourceSnapshot(repository, extraInputs, privatePaths), source = before.root;
  const parent = join(realpathSync(stateRoot), "worktrees"); mkdirSync(parent, { recursive: true, mode: 0o700 });
  const path = join(parent, jobId);
  if (existsSync(path)) throw new ContractError("WORKSPACE_ALREADY_EXISTS");
  const hidden = protectedPaths(source, privatePaths);
  const candidateHidden = hidden.map(file => join(path, relative(source, file)));
  const copies = before.files.filter(file => file.kind !== "missing").map(file => file.path);
  try {
    // 不 checkout 或生成含秘密的 git diff；仅复制已列入来源快照的文件。
    git(source, ["worktree", "add", "--detach", "--no-checkout", path, before.commit]);
    const protection = join(stateRoot, "workspace-protection"); mkdirSync(protection, { recursive: true, mode: 0o700 });
    writeFileSync(join(protection, jobId + ".json"), JSON.stringify({ schema_version: 1, source_root: source, candidate_root: path, paths: candidateHidden, files: before.files.map(file => file.path), owned_paths: [] }), { flag: "wx", mode: 0o600 });
    for (const input of copies) {
      const from = join(source, input), to = join(path, input);
      if (!existsSync(from)) continue;
      mkdirSync(dirname(to), { recursive: true });
      if (!inside(realpathSync(path), realpathSync(dirname(to)))) throw new ContractError("WORKTREE_PATH_ESCAPE");
      const info = lstatSync(from);
      if (info.isSymbolicLink()) {
        if (existsSync(to)) throw new ContractError("WORKTREE_COPY_CONFLICT");
        symlinkSync(readlinkSync(from), to);
      } else if (info.isFile()) {
        if (existsSync(to) && lstatSync(to).isSymbolicLink()) throw new ContractError("WORKTREE_COPY_CONFLICT");
        copyFileSync(from, to);
      } else throw new ContractError("UNBOUND_DIRECTORY_INPUT");
    }
    const after = sourceSnapshot(source, extraInputs, privatePaths), candidate = sourceSnapshot(path, extraInputs, candidateHidden);
    if (after.id !== before.id || candidate.id !== before.id) throw new ContractError("SOURCE_CHANGED_DURING_WORKSPACE_CREATION");
    return { path, cwd: join(path, relative(source, realpathSync(repository))), protectedRoots: candidateHidden, sourceSnapshot: before, snapshot: candidate,
      resourceId: workspaceResource(path), repositoryId: repositoryResource(path) };
  } catch (error) {
    // The incomplete worktree is deliberately preserved for reconciliation, not removed/reset.
    throw new ContractError("WORKSPACE_CREATION_FAILED", `${error instanceof ContractError ? error.code : "git_or_copy_failed"}; retained=${path}`);
  }
}
