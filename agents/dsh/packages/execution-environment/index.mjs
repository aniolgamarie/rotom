import { LocalSubprocessRuntime } from "@deepseek-ai/dsh-subprocess-local";
import { readDevelopmentEnvironment, subprocessEnvironment } from "./environment.mjs";

export { readDevelopmentEnvironment, subprocessEnvironment, mcpArguments } from "./environment.mjs";

export default class DevelopmentSubprocessRuntime extends LocalSubprocessRuntime {
  static inject = LocalSubprocessRuntime.inject ?? [];

  constructor(ctx) {
    const development = readDevelopmentEnvironment();
    super(ctx);
    // Cordis 服务方法的 this 是公开代理；私有字段品牌不能穿过该代理。
    Object.defineProperty(this, "developmentEnvironment", { value: development });
  }

  spawn(spec) {
    return super.spawn({ ...spec, env: subprocessEnvironment(spec.env, this.developmentEnvironment) });
  }

  spawnTerminal(spec) {
    return super.spawnTerminal({ ...spec, env: subprocessEnvironment(spec.env, this.developmentEnvironment) });
  }

  resolveExecutable(command, env, signal) {
    const merged = subprocessEnvironment(env, this.developmentEnvironment);
    // 公开查找参数只接受 string；空 PATH 禁止回退到宿主 PATH。
    const lookup = Object.fromEntries(Object.entries(merged).filter(([, value]) => value !== undefined));
    lookup.PATH = merged.PATH ?? "";
    return super.resolveExecutable(command, lookup, signal);
  }

  async terminalEnvironment(signal) {
    const environment = await super.terminalEnvironment(signal);
    const name = environment.platform === "windows" ? "ComSpec" : "SHELL";
    if (this.developmentEnvironment.unset.includes(name)) {
      const { defaultShell, ...rest } = environment;
      return rest;
    }
    if (Object.hasOwn(this.developmentEnvironment.values, name)) {
      const { defaultShell, ...rest } = environment;
      const shell = this.developmentEnvironment.values[name];
      return { ...rest, ...(shell ? { defaultShell: shell } : {}) };
    }
    return environment;
  }
}
