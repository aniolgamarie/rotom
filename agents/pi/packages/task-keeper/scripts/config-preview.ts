import { readFileSync } from "node:fs";
import { previewConfigMigration } from "../src/config.ts";
import { ContractError } from "../src/contracts/primitives.ts";
if (process.argv.length !== 3) throw new ContractError("CONFIG_INPUT_REQUIRED");
console.log(JSON.stringify(previewConfigMigration(JSON.parse(readFileSync(process.argv[2], "utf8"))), null, 2));
