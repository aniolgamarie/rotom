import { ShellEnvRegistry } from "@deepseek-ai/dsh-shell-env";
import { remoteShellEnvironment } from "./filter.mjs";

export default class SshShellEnvRegistry extends ShellEnvRegistry {
  collect(execution) {
    return remoteShellEnvironment(super.collect(execution));
  }
}
