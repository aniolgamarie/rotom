import { writeFileSync } from "node:fs";
export default function () {
  writeFileSync("/work/decoy-loaded", "synthetic decoy was loaded\n");
  throw new Error("DECOY_AUTO_LOAD");
}
