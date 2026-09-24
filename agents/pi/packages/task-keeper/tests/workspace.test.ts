import { test, assert, evidence } from "./recorded-test.ts";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, readFileSync, symlinkSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { createWorkspace, sourceSnapshot, workspaceResource, repositoryResource } from "../src/workspace/worktree.ts";
import { workspaceOperation, WorkspaceOperationError } from "../src/workspace/async-workspace.ts";
import { isolatedDirectory } from "./helpers.ts";

function repository(path: string) {
  mkdirSync(path, { mode: 0o700 });
  const git = (args: string[]) => execFileSync("git", ["-c", "core.hooksPath=/dev/null", "-C", path, ...args], { stdio: "pipe" });
  git(["init"]); writeFileSync(join(path, "source.cpp"), "original\n"); git(["add", "source.cpp"]);
  git(["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "fixture"]);
  return git;
}

test("[P WFL-003 T43] a real workspace worker fails on a blocked destination without falling back to the dirty source", async t => {
  const root=isolatedDirectory(t),source=join(root,"repo"),git=repository(source);
  writeFileSync(join(source,"source.cpp"),"staged\n");git(["add","source.cpp"]);
  writeFileSync(join(source,"source.cpp"),"unstaged\n");writeFileSync(join(source,"untracked.txt"),"keep\n");
  const before={status:git(["status","--porcelain=v1","-z"]),refs:git(["show-ref"]),worktrees:git(["worktree","list","--porcelain"])};
  const obstruction=join(root,"worktrees");writeFileSync(obstruction,"preserve obstruction");let failure:WorkspaceOperationError|undefined;
  try{await workspaceOperation({operation:"create",cwd:source,stateRoot:root,jobId:"failed-create"});}
  catch(error){assert.ok(error instanceof WorkspaceOperationError);failure=error;}
  for(const id of ["WFL-003","T43"])evidence(id,()=>{
    assert.ok(failure);assert.equal(failure.result.status,"failed");assert.equal(failure.result.exitCode,1);
    assert.equal(failure.result.terminationConfirmed,true);assert.equal(failure.result.terminationCoverage,"pid-namespace");
    assert.match(failure.result.stderr,/EEXIST|ENOTDIR/);assert.equal(failure.result.notSent,false);
    assert.deepEqual(git(["status","--porcelain=v1","-z"]),before.status);assert.deepEqual(git(["show-ref"]),before.refs);
    assert.deepEqual(git(["worktree","list","--porcelain"]),before.worktrees);
    assert.equal(readFileSync(join(source,"source.cpp"),"utf8"),"unstaged\n");assert.equal(readFileSync(join(source,"untracked.txt"),"utf8"),"keep\n");
    assert.equal(readFileSync(obstruction,"utf8"),"preserve obstruction");
  });
  unlinkSync(obstruction);
  const created=await workspaceOperation<{path:string}>({operation:"create",cwd:source,stateRoot:root,jobId:"valid-create"});
  for(const id of ["WFL-003","T43"])evidence(id,()=>{
    assert.notEqual(created.path,source);assert.equal(readFileSync(join(created.path,"source.cpp"),"utf8"),"unstaged\n");
    assert.equal(readFileSync(join(created.path,"untracked.txt"),"utf8"),"keep\n");
    assert.deepEqual(git(["status","--porcelain=v1","-z"]),before.status);assert.deepEqual(git(["show-ref"]),before.refs);
  });
});

test("[T41 T43 T45] persistent worktree preserves staged, unstaged and untracked inputs without changing source", (t) => {
  const root = isolatedDirectory(t), source = join(root, "repo"), git = repository(source);
  writeFileSync(join(source, "source.cpp"), "staged\n"); git(["add", "source.cpp"]);
  writeFileSync(join(source, "source.cpp"), "unstaged\n"); writeFileSync(join(source, "new file.cpp"), "new\n");
  const status = git(["status", "--porcelain=v1", "-z"]);
  const before = sourceSnapshot(source);
  const workspace = createWorkspace(source, root, "job-1");
  assert.equal(workspace.snapshot.id, before.id);
  assert.deepEqual(git(["status", "--porcelain=v1", "-z"]), status);
  assert.equal(readFileSync(join(workspace.path, "source.cpp"), "utf8"), "unstaged\n");
  assert.equal(readFileSync(join(workspace.path, "new file.cpp"), "utf8"), "new\n");
  writeFileSync(join(workspace.path, "source.cpp"), "candidate\n");
  assert.equal(readFileSync(join(source, "source.cpp"), "utf8"), "unstaged\n");
  assert.notEqual(sourceSnapshot(workspace.path).id, before.id);
  assert.equal(repositoryResource(workspace.path), repositoryResource(source));
  assert.notEqual(workspaceResource(workspace.path), workspaceResource(source));
  assert.throws(() => createWorkspace(source, root, "job-1"));
});

test("[TK05] resource identity resolves aliases and unknown external symlink inputs are rejected", (t) => {
  const root = isolatedDirectory(t), source = join(root, "repo"); repository(source);
  const alias = join(root, "alias"); symlinkSync(source, alias);
  assert.equal(workspaceResource(alias), workspaceResource(source));
  writeFileSync(join(root, "external.cpp"), "external\n"); symlinkSync(join(root, "external.cpp"), join(source, "link.cpp"));
  assert.throws(() => sourceSnapshot(source));
  unlinkSync(join(source, "link.cpp"));
  assert.throws(() => createWorkspace(source, root, ".."));
  assert.throws(() => sourceSnapshot(source, ["../external.cpp"]));
});

test("staged deletions and a subdirectory invocation retain the same physical source snapshot", (t) => {
  const root = isolatedDirectory(t), source = join(root, "repo space"), git = repository(source);
  git(["rm", "source.cpp"]); mkdirSync(join(source, "module")); writeFileSync(join(source, "module/new.cpp"), "new\n");
  const before = sourceSnapshot(source);
  const workspace = createWorkspace(join(source, "module"), root, "job-delete");
  assert.equal(workspace.snapshot.id, before.id);
  assert.equal(workspace.cwd, join(workspace.path, "module"));
  assert.deepEqual(workspace.snapshot.files.find((file) => file.path === "source.cpp")?.kind, "missing");
});

test("asynchronous workspace snapshots retain an exact private baseline without changing user refs", async (t) => {
  const root = isolatedDirectory(t), source = join(root, "repo"), git = repository(source);
  writeFileSync(join(source, "source.cpp"), "preexisting user edit\n");
  const refs = git(["show-ref"]), status = git(["status", "--porcelain=v1", "-z"]);
  const workspace = await workspaceOperation<{ path: string; baseline: { tree: string } }>({ operation: "create", cwd: source, stateRoot: root, jobId: "async-job" });
  writeFileSync(join(workspace.path, "new.cpp"), "agent added\n");
  const after = await workspaceOperation<{ patch: string }>({ operation: "snapshot", cwd: workspace.path, stateRoot: root, jobId: "async-job", baselineTree: workspace.baseline.tree });
  assert.ok(after.patch.includes("agent added")); assert.equal(after.patch.includes("preexisting user edit"), false);
  assert.deepEqual(git(["show-ref"]), refs); assert.deepEqual(git(["status", "--porcelain=v1", "-z"]), status);
});
