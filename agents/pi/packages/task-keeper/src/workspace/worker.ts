import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { createWorkspace, sourceSnapshot, captureTree, treeDiff } from "./worktree.ts";

const [inputFile, outputFile] = process.argv.slice(2);
const input = JSON.parse(readFileSync(inputFile, "utf8"));
let result: unknown;
if (input.operation === "create") {
  const workspace = createWorkspace(input.cwd, input.stateRoot, input.jobId, input.extraInputs ?? []);
  result = { ...workspace, baseline: captureTree(workspace.path, input.stateRoot, input.jobId, input.extraInputs ?? []) };
} else if (input.operation === "snapshot") {
  const snapshot = sourceSnapshot(input.cwd, input.extraInputs ?? []);
  const captured = captureTree(input.cwd, input.stateRoot, input.jobId, input.extraInputs ?? []);
  result = { snapshot, captured, patch: input.baselineTree ? treeDiff(input.cwd, captured.gitDir, input.baselineTree, captured.tree) : "" };
} else throw new Error("Unsupported workspace operation");
const temporary = `${outputFile}.writing`;
writeFileSync(temporary, JSON.stringify(result), { flag: "wx", mode: 0o600 });
renameSync(temporary, outputFile);
