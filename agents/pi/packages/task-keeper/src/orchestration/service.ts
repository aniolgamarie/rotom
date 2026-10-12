// legacy入口保原默认adapter与资格；业务workflow只有service-core一份源码。
import { readFileSync } from "node:fs";
import { TaskServiceCore } from "./service-core.ts";
import { SubagentsAdapter } from "../adapters/subagents.ts";
import { runtimeIdentity } from "../adapters/runtime-identity.ts";
import { taskKeeperRuntimeIdentity } from "../adapters/task-keeper-identity.ts";
export type { ManagedJob } from "./service-core.ts";
export class TaskService extends TaskServiceCore {
  constructor(pi: any, store: any, config: any, ctx: any, notify: any = () => {}, currentConfig: any = () => config,
    sessionOrigin: { fork?: boolean; parentFile?: string } = {}) {
    super(pi, store, config, ctx, notify, currentConfig, sessionOrigin,
      ({ owner }: any) => new SubagentsAdapter(pi, store, config, owner),
      () => [runtimeIdentity(), taskKeeperRuntimeIdentity(), readFileSync(new URL("../adapters/subagents-lock.json", import.meta.url), "utf8")]);
  }
}
