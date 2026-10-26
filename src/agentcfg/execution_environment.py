"""普通开发环境、显式覆盖及无值诊断；不读取凭据或修改父进程环境。"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import sys

from .adapter import SecretRef
from .schema import ConfigError
from .storage import Conflict


DEVELOPER_NAMES = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
  "ZDOTDIR", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH",
  "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONPATH", "NVM_DIR", "JAVA_HOME", "CC", "CXX",
  "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CPATH", "LIBRARY_PATH", "PKG_CONFIG_PATH",
  "CMAKE_PREFIX_PATH"})
PATH_NAMES = ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR")
CONTROL_NAMES = frozenset({"BASH_ENV", "ENV", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
  "PYTHONSTARTUP", "PYTHONINSPECT"})
# 命名代理一次注入的标准变量（大小写全集）；不默认透传调用者代理，须显式选择配置。
PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
  "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def proxy_variables(profile):
  url = profile["url"]
  values = {"HTTP_PROXY": url, "HTTPS_PROXY": url, "http_proxy": url, "https_proxy": url,
    "ALL_PROXY": profile.get("all_proxy", url), "all_proxy": profile.get("all_proxy", url)}
  if profile.get("no_proxy"):
    values["NO_PROXY"] = values["no_proxy"] = profile["no_proxy"]
  return values


@dataclass
class EnvironmentResult:
  values: dict = field(repr=False)
  removed: set = field(default_factory=set)
  sources: dict = field(default_factory=dict)


def declarations(machine):
  settings = machine.get("environment", {})
  return {"inherit": list(settings.get("inherit", [])), "values": dict(settings.get("values", {})),
    "unset": list(settings.get("unset", [])), "editor": machine.get("editor"),
    "proxy": settings.get("proxy"), "proxies": dict(machine.get("proxies", {}))}


def caller_paths(caller=None):
  caller = os.environ if caller is None else caller
  result = {name: caller.get(name) for name in PATH_NAMES}
  for name, value in result.items():
    if value is None and name != "HOME":
      continue
    if not isinstance(value, str) or not value or "\0" in value or not Path(value).is_absolute():
      raise ConfigError("execution-environment-path")
  return result


def selected_proxy(machine, proxy=None):
  """一次性选择优先于机器持久默认；未选择返回 None。"""
  settings = machine.get("environment", {})
  selected = proxy if proxy is not None else settings.get("proxy")
  if selected is None:
    return None, None
  profile = machine.get("proxies", {}).get(selected)
  if profile is None:
    raise ConfigError("environment-proxy-unknown")
  return selected, profile


def validate_overrides(spec, machine, inherit=(), unset=(), proxy=None):
  from .config import validate_environment_settings
  if len(set(inherit)) != len(inherit) or len(set(unset)) != len(unset) or set(inherit) & set(unset):
    raise ConfigError("environment-override-conflict")
  names = (*inherit, *unset)
  if any(not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None for name in names):
    raise ConfigError("environment-override-name")
  validate_environment_settings({"inherit": list(inherit), "unset": list(unset)})
  if spec.environment_policy == "legacy" and (names or proxy is not None):
    raise Conflict("旧环境契约不支持单次覆盖；请先 plan/apply")
  for name in names:
    if name in CONTROL_NAMES:
      raise ConfigError("environment-protected-control")
  selected, _ = selected_proxy(machine, proxy)
  settings = machine.get("environment", {})
  if selected is not None:
    declared = set(settings.get("inherit", [])) | set(settings.get("values", {})) | set(settings.get("unset", [])) | set(names)
    if declared & set(PROXY_NAMES):
      raise ConfigError("environment-proxy-conflict")
  # 适配器的绑定在最后应用；不能让显式用户请求在此被静默撤销。
  explicit = set(settings.get("inherit", [])) | set(settings.get("values", {}))
  explicit |= set(settings.get("unset", [])) | set(names)
  if selected is not None:
    explicit |= set(PROXY_NAMES)
  for binding in spec.environment:
    if binding.name in explicit and isinstance(binding.value, SecretRef):
      raise ConfigError("environment-credential-target")


def prepare(spec, machine, *, caller=None, inherit=(), unset=(), proxy=None, extra_names=()):
  from .process import BASE_ENV, environment
  caller = os.environ if caller is None else caller
  validate_overrides(spec, machine, inherit, unset, proxy)
  selected, profile = selected_proxy(machine, proxy)
  source = "one-shot-proxy" if proxy is not None else "machine-proxy"
  if spec.environment_policy == "legacy":
    home = next((item.value for item in spec.environment if item.name == "HOME"), None)
    result = EnvironmentResult(environment(machine, home=Path(home) if home else None))
    if selected is not None:
      result.values.update(proxy_variables(profile))
      result.sources.update({name: source for name in proxy_variables(profile)})
    return result
  names = (BASE_ENV | DEVELOPER_NAMES | set(extra_names)
    | {name for name in caller if name.startswith("LC_")})
  values = {name: caller[name] for name in names if name in caller and name not in CONTROL_NAMES}
  sources = {name: "caller" for name in values}
  settings = machine.get("environment", {})
  for name in settings.get("inherit", []):
    if name in caller:
      values[name], sources[name] = caller[name], "machine-inherit"
  for name, value in settings.get("values", {}).items():
    values[name], sources[name] = value, "machine-value"
  if machine.get("editor") is not None:
    for name in ("EDITOR", "VISUAL"):
      values[name], sources[name] = machine["editor"], "machine-editor"
  removed = set(settings.get("unset", []))
  for name in removed:
    values.pop(name, None)
    sources[name] = "machine-unset"
  if selected is not None:
    for name, value in proxy_variables(profile).items():
      values[name], sources[name] = value, source
  for name in inherit:
    if name not in caller:
      raise ConfigError("environment-explicit-inherit-missing")
    values[name], sources[name] = caller[name], "one-shot-inherit"
    removed.discard(name)
  for name in unset:
    values.pop(name, None)
    removed.add(name)
    sources[name] = "one-shot-unset"
  explicit = set(settings.get("inherit", [])) | set(settings.get("values", {})) | set(settings.get("unset", [])) | set(inherit) | set(unset)
  if selected is not None:
    explicit |= set(PROXY_NAMES)
  for binding in spec.environment:
    if isinstance(binding.value, SecretRef):
      continue
    if binding.name in explicit and (binding.name in removed or values.get(binding.name) != binding.value):
      raise ConfigError("environment-adapter-override-unsupported")
  return EnvironmentResult(values, removed, sources)


def apply_bindings(result, spec, store=None, *, secrets=False):
  from .secrets import CredentialError
  values = dict(result.values)
  if spec.environment_policy == "isolated":
    from .process import environment
    home = next((item.value for item in spec.environment if item.name == "HOME"), None)
    isolated = environment({}, home=Path(home))
    for name in PATH_NAMES:
      values.pop(name, None)
      if name in isolated:
        values[name] = isolated[name]
  for binding in spec.environment:
    if isinstance(binding.value, SecretRef):
      if not secrets:
        continue
      value = store.resolve(binding.value, required=binding.required)
    else:
      value = binding.value
    if value is not None:
      if "\0" in value:
        raise CredentialError()
      values[binding.name] = value
  return values


def capture_caller(machine, inherit=(), extra_names=()):
  from .process import BASE_ENV
  settings = machine.get("environment", {})
  # 代理变量只进入诊断（报告"已移除/未继承"），不因此被会话继承；继承由 prepare 的白名单决定。
  names = (BASE_ENV | DEVELOPER_NAMES | set(PROXY_NAMES) | set(extra_names)
    | set(settings.get("inherit", [])) | set(settings.get("values", {})) | set(inherit))
  names |= {name for name in os.environ if name.startswith("LC_")}
  from .config import _credential_name
  return tuple(os.environ), {name: os.environ[name] for name in names
    if name in os.environ and not _credential_name(name) and not name.startswith(("AGENTCFG_", "DSH_"))}


def differences(caller, effective, *, sources=None, names=None):
  from .config import _credential_name
  sources = sources or {}
  items, sensitive = [], 0
  for name in sorted(caller if names is None else names):
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
      sensitive += 1
      continue
    if _credential_name(name) or name.startswith(("AGENTCFG_", "DSH_")):
      # 不读取秘密值来比较；原有受保护输入均提示经过过滤/重新绑定。
      sensitive += 1
      continue
    if name not in effective:
      items.append({"name": name, "status": "removed", "source": sources.get(name, "not-inherited")})
    elif name in caller and caller[name] != effective[name]:
      items.append({"name": name, "status": "overridden", "source": sources.get(name, "adapter-policy")})
  return {"variables": items, "sensitive_excluded": sensitive, "values": "not-disclosed"}


def warn(report, *, channel="host"):
  items = report["variables"]
  if not items and not report["sensitive_excluded"]:
    return
  print(f"environment warning ({channel}): {len(items)} caller variables removed/overridden; "
    f"{report['sensitive_excluded']} protected inputs filtered/rebound (values not compared).", file=sys.stderr)
  for item in items[:12]:
    print(f"  {item['name']}: {item['status']} ({item['source']})", file=sys.stderr)
  if len(items) > 12:
    print("  More names: agentcfg doctor --environment (values are never shown).", file=sys.stderr)


def restricted_environment(home, executable):
  """受限进程不从已覆盖的普通父环境重新继承 PATH/加载路径。"""
  home, executable = Path(home), Path(executable)
  return {"HOME": str(home), "PATH": str(executable.parent) + os.pathsep + os.defpath,
    "TMPDIR": str(home / "tmp"), "TMP": str(home / "tmp"), "TEMP": str(home / "tmp"),
    "LANG": "C.UTF-8", "XDG_CONFIG_HOME": str(home / ".config"),
    "XDG_DATA_HOME": str(home / ".local/share"), "XDG_STATE_HOME": str(home / ".local/state"),
    "XDG_CACHE_HOME": str(home / ".cache")}
