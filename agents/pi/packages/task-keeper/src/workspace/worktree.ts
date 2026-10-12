import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { openSync, closeSync, fstatSync, readSync, constants, mkdirSync, readFileSync, lstatSync, realpathSync, readlinkSync, copyFileSync, symlinkSync, existsSync, writeFileSync, chmodSync } from "node:fs";
import { isAbsolute, dirname, join, relative, resolve, sep } from "node:path";
import { ContractError, digest, identifier } from "../contracts/primitives.ts";

import { inputPath, inputCanonical, inputOrder, validateSemanticSource, INPUT_RECORD_LIMIT, INPUT_SOURCE_LIMIT } from "../evidence/context.ts";

export interface SourceFile { path: string; kind: "file" | "symlink" | "missing"; hash: string | null; executable: number }
export interface SourceSnapshot { id: string; root: string; commit: string; files: SourceFile[] }
const git = (cwd: string, args: string[], input?: Buffer): Buffer => execFileSync(process.env.AGENTCFG_GIT_EXECUTABLE ?? "/usr/bin/git", ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-C", cwd, ...args], {
  env: { PATH: "/usr/bin:/bin", HOME: process.env.HOME, LANG: "C.UTF-8", GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" },
  input, maxBuffer: 32 * 1024 * 1024, stdio: ["pipe", "pipe", "pipe"],
});
const listed = (cwd: string, args: string[]): string[] => new TextDecoder("utf8",{fatal:true}).decode(git(cwd, ["ls-files", ...args, "-z"])).split("\0").filter(Boolean);
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

export function sourceSnapshot(cwd: string, extraInputs: string[] = [], privatePaths: string[] = [], semantic=false): SourceSnapshot {
  const root = realpathSync(git(cwd, ["rev-parse", "--show-toplevel"]).toString("utf8").replace(/\r?\n$/, ""));
  const commit = git(root, ["rev-parse", "--verify", "HEAD"]).toString("utf8").trim();
  const committed = new TextDecoder("utf8",{fatal:true}).decode(git(root, ["ls-tree", "-r", "--name-only", "-z", "HEAD"])).split("\0").filter(Boolean);
  const paths = [...new Set([...committed, ...listed(root, ["--cached", "--others", "--exclude-standard"]), ...extraInputs.map((p) => relativeInput(root, p)), ...ownedPaths(root)])].sort();
  const protectedRoots = protectedPaths(root, privatePaths);
  if(paths.length>INPUT_RECORD_LIMIT)throw new ContractError("INPUT_SNAPSHOT_LIMIT");
  let sourceBytes=0;
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
    if(info.nlink!==1||(sourceBytes+=info.size)>INPUT_SOURCE_LIMIT)throw new ContractError("INPUT_SNAPSHOT_LIMIT");
    return { path, kind: "file", hash: sha(safeInputBytes(full,root,semantic)), executable: info.mode & 0o111 };
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
export function captureTree(cwd: string, stateRoot: string, jobId: string, extraInputs: string[] = [], privatePaths: string[] = [],semantic=false): { tree: string; gitDir: string } {
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
  const expected=sourceSnapshot(cwd,extraInputs,privatePaths,semantic),records=expected.files.filter(file=>file.kind!=="missing"),files=records.map(row=>row.path);
  git(cwd, [...args, "read-tree", "--empty"]);
  const indexed:Array<{mode:string;oid:string;name:string}>=[];let total=0;
  if(semantic){
    for(const row of records){
      const path=join(realpathSync(cwd),row.path);let body:Buffer,mode:string;
      if(row.kind==="symlink"){
        const before=lstatSync(path,{bigint:true}),target=readlinkSync(path);inputPath(target);
        const covered=relative(realpathSync(cwd),resolve(dirname(path),target));inputPath(covered);
        if(!records.some(v=>v.path===covered&&v.kind==="file"))throw new ContractError("INPUT_SNAPSHOT_SYMLINK");
        const after=lstatSync(path,{bigint:true});if(["dev","ino","uid","ctimeNs","mtimeNs"].some(key=>before[key]!==after[key])||readlinkSync(path)!==target)throw new ContractError("INPUT_SNAPSHOT_DRIFT");
        body=Buffer.from(target);mode="120000";
      }else{body=safeInputBytes(path,realpathSync(cwd),true);mode=row.executable?"100755":"100644";}
      if((total+=body.length)>INPUT_SOURCE_LIMIT||sha(body)!==row.hash)throw new ContractError("INPUT_SNAPSHOT_DRIFT");
      // 固定stdin不经过业务path/filter；保原Git命令接口/私有object store，不再git add重读。
      const oid=git(cwd,[...args,"hash-object","-w","--stdin"],body).toString().trim();
      if(!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(oid)||createHash(oid.length===40?"sha1":"sha256").update(`blob ${body.length}\0`).update(body).digest("hex")!==oid)throw new ContractError("INPUT_SNAPSHOT_GIT_BLOB");
      git(cwd,[...args,"update-index","--add","--cacheinfo",mode,oid,row.path]);indexed.push({mode,oid,name:row.path});
    }
  }else for (let offset = 0; offset < files.length; offset += 100) git(cwd, [...args, "add", "-f", "--", ...files.slice(offset, offset + 100)]);
  const tree = git(cwd, [...args, "write-tree"]).toString("utf8").trim();
  if(semantic){
    if(!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(tree))throw new ContractError("INPUT_SNAPSHOT_GIT_TREE");
    const actual=new TextDecoder("utf8",{fatal:true}).decode(git(cwd,[...args,"ls-tree","-r","-z",tree])).split("\0").filter(Boolean).map(value=>{const row=/^([0-9]{6}) blob ([a-f0-9]{40}|[a-f0-9]{64})\t(.+)$/.exec(value);if(!row)throw new ContractError("INPUT_SNAPSHOT_GIT_TREE");return {mode:row[1],oid:row[2],name:row[3]};}).sort((a,b)=>inputOrder(a.name,b.name));
    if(inputCanonical(actual)!==inputCanonical(indexed.sort((a,b)=>inputOrder(a.name,b.name)))||sourceSnapshot(cwd,extraInputs,privatePaths,true).id!==expected.id)throw new ContractError("INPUT_SNAPSHOT_GIT_TREE");
  }
  git(cwd, [...args, "update-ref", `refs/task-keeper/${tree}`, tree]);
  return { tree, gitDir: directory };
}

export function treeDiff(cwd: string, gitDir: string, from: string, to: string): string {
  if (!/^[a-f0-9]{40,64}$/.test(from) || !/^[a-f0-9]{40,64}$/.test(to)) throw new ContractError("INVALID_TREE_ID");
  return git(cwd, ["--git-dir", gitDir, "diff", "--binary", from, to, "--"]).toString("utf8");
}

/** Copies a stable source snapshot into a persistent worktree; it never stashes or resets the source. */
export function createWorkspace(repository: string, stateRoot: string, jobId: string, extraInputs: string[] = [], privatePaths: string[] = [],semantic=false) {
  identifier(jobId);
  if (jobId === "." || jobId === "..") throw new ContractError("INVALID_WORKSPACE_ID");
  const before = sourceSnapshot(repository, extraInputs, privatePaths,semantic), source = before.root;
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
        if(semantic){const content=safeInputBytes(from,source,true),expected=before.files.find(row=>row.path===input);if(sha(content)!==expected?.hash)throw new ContractError("SOURCE_CHANGED_DURING_WORKSPACE_CREATION");writeFileSync(to,content,{flag:"wx",mode:info.mode&0o777});chmodSync(to,info.mode&0o777);}
        else copyFileSync(from, to);
      } else throw new ContractError("UNBOUND_DIRECTORY_INPUT");
    }
    const after = sourceSnapshot(source, extraInputs, privatePaths,semantic), candidate = sourceSnapshot(path, extraInputs, candidateHidden,semantic);
    if (after.id !== before.id || candidate.id !== before.id) throw new ContractError("SOURCE_CHANGED_DURING_WORKSPACE_CREATION");
    return { path, cwd: join(path, relative(source, realpathSync(repository))), protectedRoots: candidateHidden, sourceSnapshot: before, snapshot: candidate,
      resourceId: workspaceResource(path), repositoryId: repositoryResource(path) };
  } catch (error) {
    // The incomplete worktree is deliberately preserved for reconciliation, not removed/reset.
    throw new ContractError("WORKSPACE_CREATION_FAILED", `${error instanceof ContractError ? error.code : "git_or_copy_failed"}; retained=${path}`);
  }
}

/** 仅原已authorize helper消费Host上下文；调用方不能提供文件名单或秘密例外。 */
function physicalWorkspaceIdentity(info: {dev: bigint;ino: bigint;uid: bigint}): string {
  // 原Python root_identity沿deployment.json_bytes带终结LF；独立于语义DTO无LF摘要。
  return sha(inputCanonical({device:String(info.dev),inode:String(info.ino),uid:String(info.uid)})+"\n");
}
export function semanticSource(cwd: string, scope: any, extraInputs: string[] = [], sourceSecrets: any[] = []) {
  validateInputScope(scope);
  const root=realpathSync(cwd);
  if(root!==scope.candidate_root)throw new ContractError("INPUT_SNAPSHOT_ROOT");
  const rootInfo=lstatSync(root,{bigint:true}), identity=physicalWorkspaceIdentity(rootInfo);
  if(scope.root_identity!==null&&identity!==scope.root_identity)throw new ContractError("ROOT_IDENTITY");
  const policy=scope.policy, excluded=(name:string)=>policy.artifact_exclusions.some((r:any)=>name===r.relative_path||r.kind==="directory"&&name.startsWith(r.relative_path+"/"));
  const secret=(name:string)=>scope.protected_inputs.some((r:any)=>name===r.relative_path||name.startsWith(r.relative_path+"/"));
  const discover=()=>{
    const tracked=[...new Set([...new TextDecoder("utf8",{fatal:true}).decode(git(root,["ls-tree","-r","--name-only","-z","HEAD"])).split("\0").filter(Boolean),...listed(root,["--cached"])])].sort(inputOrder);
    for(const name of tracked){inputPath(name);if(excluded(name))throw new ContractError("INPUT_ARTIFACT_TRACKED_OVERLAP");}
    const all=[...new Set([...tracked,...listed(root,["--others","--exclude-standard"]),...extraInputs,...policy.explicit_inputs,...ownedPaths(root)])].sort(inputOrder);
    if(all.length>INPUT_RECORD_LIMIT)throw new ContractError("INPUT_SNAPSHOT_LIMIT");
    for(const name of all){inputPath(name);if(name.split("/").includes(".git"))throw new ContractError("INPUT_SNAPSHOT_PATH");}
    return all.filter(name=>!excluded(name)&&!secret(name));
  };
  const names=discover(),files:any[]=[],observed=new Map<string,any>();let bytes=0;
  const same=(a:any,b:any)=>["dev","ino","uid","size","mtimeNs","ctimeNs","mode","nlink"].every(k=>a[k]===b[k]);
  inputFiles: for(const name of names){
    const path=join(root,name);
    // 每个父路径canonical核验；NOFOLLOW同时阻止最后一段替换。
    let parent=root;for(const part of name.split("/").slice(0,-1)){parent=join(parent,part);try{if(lstatSync(parent).isSymbolicLink()||realpathSync(parent)!==parent)throw new ContractError("INPUT_SNAPSHOT_SYMLINK");}catch(e){if((e as NodeJS.ErrnoException).code==="ENOENT"){files.push({relative_path:name,kind:"missing"});continue inputFiles;}throw e;}}
    let info;try{info=lstatSync(path,{bigint:true});}catch(e){if((e as NodeJS.ErrnoException).code==="ENOENT"){files.push({relative_path:name,kind:"missing"});continue;}throw e;}
    observed.set(name,info);
    if(info.isSymbolicLink()){
      const target=readlinkSync(path);inputPath(target);if(isAbsolute(target)||target.split(/[\\/]/).some(x=>["..",""].includes(x)))throw new ContractError("INPUT_SNAPSHOT_SYMLINK");
      const relativeTarget=relative(root,resolve(dirname(path),target));inputPath(relativeTarget);
      if(!names.includes(relativeTarget)||!lstatSync(join(root,relativeTarget)).isFile())throw new ContractError("INPUT_SNAPSHOT_SYMLINK");
      if(readlinkSync(path)!==target||!same(info,lstatSync(path,{bigint:true})))throw new ContractError("INPUT_SNAPSHOT_DRIFT");
      files.push({relative_path:name,kind:"symlink",target:relativeTarget});continue;
    }
    if(!info.isFile()||info.nlink!==1n||(bytes+=Number(info.size))>INPUT_SOURCE_LIMIT)throw new ContractError("INPUT_SNAPSHOT_LIMIT");
    const content=safeInputBytes(path,root,true);
    if(!same(info,lstatSync(path,{bigint:true})))throw new ContractError("INPUT_SNAPSHOT_DRIFT");
    files.push({relative_path:name,kind:"file",sha256:sha(content),executable:Number(info.mode)&0o111});

  }
  const finalNames=discover(),currentRoot=lstatSync(root,{bigint:true});
  if(inputCanonical(names)!==inputCanonical(finalNames)||["dev","ino","uid"].some(key=>rootInfo[key]!==currentRoot[key]))throw new ContractError("INPUT_SNAPSHOT_DRIFT");
  for(const row of files){try{const now=lstatSync(join(root,row.relative_path),{bigint:true});if(row.kind==="missing"||!same(observed.get(row.relative_path),now))throw new ContractError("INPUT_SNAPSHOT_DRIFT");}catch(e){if(row.kind!=="missing"||(e as NodeJS.ErrnoException).code!=="ENOENT")throw e;}}
  const sensitive=[...sourceSecrets,...secretStates(root,scope,"candidate")].sort((a,b)=>inputOrder(a.actor+":"+a.reference,b.actor+":"+b.reference));
  return validateSemanticSource({schema_version:1,workspace_identity:identity,scope:{relative_roots:["."],...policy,outside_exclusions:scope.outside_exclusions},files,sensitive_inputs:sensitive});
}
export function validateInputScope(scope:any){
  if(!scope||Object.keys(scope).sort().join()!==["schema_version","source_root","candidate_root","root_identity","creating","policy","protected_inputs","outside_exclusions"].sort().join()||scope.schema_version!==1
      ||!isAbsolute(scope.source_root)||!isAbsolute(scope.candidate_root)||typeof scope.creating!=="boolean")throw new ContractError("INPUT_SNAPSHOT_SCOPE");
  inputCanonical(scope);
  if(!scope.policy||Object.keys(scope.policy).sort().join()!=="artifact_exclusions,explicit_inputs"||!Array.isArray(scope.policy.explicit_inputs)||!Array.isArray(scope.policy.artifact_exclusions)||!Array.isArray(scope.protected_inputs)||!Array.isArray(scope.outside_exclusions))throw new ContractError("INPUT_SNAPSHOT_SCOPE");
  for(const name of scope.policy.explicit_inputs)inputPath(name);
  for(const row of scope.policy.artifact_exclusions){if(Object.keys(row).sort().join()!=="kind,relative_path"||!["file","directory"].includes(row.kind))throw new ContractError("INPUT_SNAPSHOT_SCOPE");inputPath(row.relative_path);}
  for(const row of scope.protected_inputs){if(Object.keys(row).sort().join()!=="category,owner,provider,reference,relative_path")throw new ContractError("INPUT_SNAPSHOT_SCOPE");inputPath(row.relative_path);}
}
export function secretStates(root:string,scope:any,actor:"source"|"candidate"){
  return scope.protected_inputs.map((r:any)=>{let state="present";try{lstatSync(join(root,r.relative_path));}catch(e){state=(e as NodeJS.ErrnoException).code==="ENOENT"?"missing":"unreadable";}return {reference:r.reference,category:r.category,owner:r.owner,provider:r.provider,actor,state};});
}
export function semanticScopeAdmission(cwd:string,scope:any){
  validateInputScope(scope);
  const tracked=[...new TextDecoder("utf8",{fatal:true}).decode(git(cwd,["ls-tree","-r","--name-only","-z","HEAD"])).split("\0").filter(Boolean),...listed(cwd,["--cached"])];
  for(const name of tracked)if(scope.policy.artifact_exclusions.some((r:any)=>name===r.relative_path||r.kind==="directory"&&name.startsWith(r.relative_path+"/")))throw new ContractError("INPUT_ARTIFACT_TRACKED_OVERLAP");
}

function safeInputBytes(path:string,root:string,semantic=false):Buffer {
  if(process.platform!=="linux"){if(semantic)throw new ContractError("INPUT_SNAPSHOT_PLATFORM_UNSUPPORTED");return readFileSync(path);}
  const before=lstatSync(path,{bigint:true}),rootBefore=lstatSync(root,{bigint:true});
  if(!before.isFile()||before.nlink!==1n||before.size>BigInt(INPUT_SOURCE_LIMIT))throw new ContractError("INPUT_SNAPSHOT_FILE");
  const equal=(a:any,b:any)=>["dev","ino","uid","mode","size","mtimeNs","ctimeNs","nlink"].every(k=>a[k]===b[k]);
  const handles:number[]=[],directories:Array<{path:string;info:any}>=[];
  try{
    let directory=openSync(root,constants.O_RDONLY|constants.O_DIRECTORY|constants.O_NOFOLLOW);handles.push(directory);directories.push({path:root,info:fstatSync(directory,{bigint:true})});
    if(fstatSync(directory,{bigint:true}).ino!==rootBefore.ino||fstatSync(directory,{bigint:true}).dev!==rootBefore.dev)throw new ContractError("INPUT_SNAPSHOT_DRIFT");
    const parts=relative(root,path).split("/");inputPath(parts.join("/"));
    let currentPath=root;for(const part of parts.slice(0,-1)){currentPath=join(currentPath,part);const currentBefore=lstatSync(currentPath,{bigint:true});directory=openSync(`/proc/self/fd/${directory}/${part}`,constants.O_RDONLY|constants.O_DIRECTORY|constants.O_NOFOLLOW);handles.push(directory);const current=fstatSync(directory,{bigint:true});if(currentBefore.dev!==current.dev||currentBefore.ino!==current.ino||currentBefore.uid!==current.uid)throw new ContractError("INPUT_SNAPSHOT_DRIFT");directories.push({path:currentPath,info:current});}
    const fd=openSync(`/proc/self/fd/${directory}/${parts.at(-1)}`,constants.O_RDONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);handles.push(fd);
    const opened=fstatSync(fd,{bigint:true});if(!equal(before,opened))throw new ContractError("INPUT_SNAPSHOT_DRIFT");
    const buffer=Buffer.alloc(Number(opened.size)+1);let offset=0,count=0;
    while(offset<buffer.length&&(count=readSync(fd,buffer,offset,buffer.length-offset,offset))>0)offset+=count;
    if(offset!==Number(opened.size)||!equal(opened,fstatSync(fd,{bigint:true}))||!equal(opened,lstatSync(path,{bigint:true})))throw new ContractError("INPUT_SNAPSHOT_DRIFT");
    for(const row of directories){const now=lstatSync(row.path,{bigint:true});if(now.isSymbolicLink()||["dev","ino","uid","ctimeNs"].some(k=>now[k]!==row.info[k]))throw new ContractError("INPUT_SNAPSHOT_DRIFT");}
    return buffer.subarray(0,offset);
  }finally{for(const fd of handles.reverse())closeSync(fd);}
}
