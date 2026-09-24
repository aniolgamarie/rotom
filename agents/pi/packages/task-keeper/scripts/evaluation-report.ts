import { readFileSync } from "node:fs";
import { evaluate, type EvaluationRun } from "../src/evidence/evaluation.ts";
import { object, ContractError } from "../src/contracts/primitives.ts";
// Offline reporting only. The input inventory comes from the task-start log, not a success-filtered result list.
const path = process.argv[2];
if (!path) throw new ContractError("EVALUATION_INPUT_REQUIRED");
const input = object(JSON.parse(readFileSync(path, "utf8")), ["startedRunIds", "runs"]);
if (!Array.isArray(input.startedRunIds) || input.startedRunIds.some(id => typeof id !== "string" || !id.trim()) || !Array.isArray(input.runs))
  throw new ContractError("EVALUATION_START_INVENTORY_REQUIRED");
console.log(JSON.stringify(evaluate(input.runs as EvaluationRun[], input.startedRunIds as string[]), null, 2));
