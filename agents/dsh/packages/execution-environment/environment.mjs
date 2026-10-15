import { isAbsolute } from "node:path";

const PAYLOAD = "AGENTCFG_DEVELOPMENT_ENV";
const PATH_NAMES = ["HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"];
const CONTROL_NAMES = new Set(["BASH_ENV", "ENV", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
  "PYTHONSTARTUP", "PYTHONINSPECT", "NODE_OPTIONS", "NODE_PATH",
  "NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG", "npm_config_userconfig", "npm_config_globalconfig"]);
const CREDENTIAL_NAME = /(?:^|_)(?:API_KEY|APIKEY|ACCESS_TOKEN|REFRESH_TOKEN|TOKEN|PASSWORD|PASSWD|SECRET|CLIENT_SECRET|AUTHORIZATION|CREDENTIAL|CREDENTIAL_REF)$/;
const invalid = () => { throw new Error("Invalid development environment payload"); };
const mapping = value => value !== null && typeof value === "object" && !Array.isArray(value)
  && Object.getPrototypeOf(value) === Object.prototype;
const text = value => typeof value === "string" && !value.includes("\0");

function validName(name) {
  if (typeof name !== "string" || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) return false;
  const normalized = name.toUpperCase();
  return !name.startsWith("DSH_") && !name.startsWith("AGENTCFG_")
    && !CONTROL_NAMES.has(name) && !CREDENTIAL_NAME.test(normalized);
}

function validate(payload) {
  if (!mapping(payload) || Object.keys(payload).sort().join(",") !== "unset,values,version"
      || payload.version !== 1 || !mapping(payload.values) || !Array.isArray(payload.unset)) invalid();
  for (const [name, value] of Object.entries(payload.values)) {
    if (!validName(name) || !text(value)) invalid();
    if (PATH_NAMES.includes(name) && (!value || !isAbsolute(value))) invalid();
  }
  if (!Object.hasOwn(payload.values, "HOME") || payload.unset.includes("HOME")
      || new Set(payload.unset).size !== payload.unset.length) invalid();
  for (const name of payload.unset) {
    if (!validName(name) || Object.hasOwn(payload.values, name)) invalid();
  }
  return Object.freeze({ version: 1, values: Object.freeze({ ...payload.values }),
    unset: Object.freeze([...payload.unset]) });
}

export function readDevelopmentEnvironment(environment = process.env) {
  let payload;
  try {
    if (typeof environment[PAYLOAD] !== "string") invalid();
    payload = JSON.parse(environment[PAYLOAD]);
  } catch {
    invalid();
  }
  return validate(payload);
}

export function subprocessEnvironment(environment = {}, development = readDevelopmentEnvironment()) {
  const snapshot = validate(development);
  // 显式工具环境优先；身份路径始终来自调用者快照，不恢复宿主的私有 HOME。
  const result = Object.assign(Object.create(null), snapshot.values, environment);
  for (const name of PATH_NAMES) result[name] = snapshot.values[name];
  if (!Object.hasOwn(result, "PATH")) result.PATH = undefined;
  for (const name of snapshot.unset) result[name] = undefined;
  // undefined 是公开 Node 环境删除语义；delete 会让宿主的 ambient merge 补回。
  result[PAYLOAD] = undefined;
  result.AGENTCFG_MCP_ENV_ARGS = undefined;
  // 上游按 KEY/TOKEN 等模式过滤，不覆盖内部 MCP 哈希凭据名；只枚举名称。
  for (const name of Object.keys(process.env)) {
    if (name.startsWith("AGENTCFG_")) result[name] = undefined;
  }
  return result;
}

export function mcpArguments(command, args = [], development = readDevelopmentEnvironment()) {
  if (!text(command) || !command || command.includes("=") || !Array.isArray(args) || args.some(arg => !text(arg))) invalid();
  const environment = subprocessEnvironment({}, development);
  if (!command.includes("/") && !environment.PATH) invalid();
  const removed = Object.keys(environment).filter(name => environment[name] === undefined).sort();
  const values = Object.entries(environment).filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0);
  return ["/usr/bin/env", ...removed.flatMap(name => ["-u", name]), "--",
    ...values.map(([name, value]) => `${name}=${value}`), command, ...args];
}
