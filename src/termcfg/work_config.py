"""work仅消费已校验的普通选择，不解析凭据或安装工具。"""

from dataclasses import dataclass, field
from copy import deepcopy
from contextlib import contextmanager
import os
import hashlib
import json
from pathlib import Path
import re
import shutil

from .errors import TermcfgError


ROOT = Path(__file__).resolve().parents[2]
ROLES = ("shell", "edit", "build", "debug", "pi", "codex", "dsh")
PAYLOAD_ENV = "ROTOM_WORK_LAUNCH_V1"
PAYLOAD_ENV_V2 = "ROTOM_WORK_LAUNCH_V2"
PATH_NAMES = ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
  "XDG_CACHE_HOME", "XDG_RUNTIME_DIR")


def operation_timeout(role=None):
  return 60 if role in ("pi", "dsh") else 30


@dataclass(frozen=True, repr=False)
class WorkSettings:
  local_path: Path
  herdr_binary: str
  session: str
  editor: str | None = None
  pi_profile: str | None = None
  dsh_profile: str | None = None
  codex_binary: str | None = None
  codex_daemon: bool = False
  repo_root: Path = field(default=ROOT)
  model: str | None = None
  structured: dict | None = None

  def __repr__(self):
    return "WorkSettings()"

  @property
  def selectors(self):
    return ("--local", str(self.local_path))

  @property
  def selection_digest(self):
    # 仅限这些普通选择，绝不摘要原始local或secrets文件。
    value = {key: getattr(self, key) for key in ("herdr_binary", "session", "editor",
      "pi_profile", "dsh_profile", "codex_binary", "codex_daemon")}
    value["local"] = str(self.local_path)
    if self.model is not None:
      value.update(model=self.model, structured=self.structured)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
      separators=(",", ":")).encode()).hexdigest()


def literal(value):
  if not isinstance(value, str) or not value or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
    raise TermcfgError(2, "work_invalid_literal", "work --help")
  try:
    value.encode("utf-8")
  except UnicodeError:
    raise TermcfgError(2, "work_invalid_literal", "work --help") from None
  return value


def executable_name(value):
  value = literal(value)
  if value.startswith("~/"):
    value = str(Path(os.environ.get("HOME", "")) / value[2:])
  path = Path(value)
  if path.is_absolute():
    if ".." in path.parts:
      raise TermcfgError(2, "work_invalid_executable", "work --help")
  elif not re.fullmatch(r"[\w.+-]+", value) or value in (".", ".."):
    raise TermcfgError(2, "work_invalid_executable", "work --help")
  return value


def resolve_executable(value):
  value = executable_name(value)
  path = value if Path(value).is_absolute() else shutil.which(value)
  try:
    if path is None or not Path(path).is_file() or not os.access(path, os.X_OK):
      raise OSError()
    return str(Path(path).resolve(strict=True))
  except (OSError, ValueError):
    raise TermcfgError(5, "work_executable_not_prepared", "work --help") from None


def check_config_location(home=None):
  home = Path(home or os.environ.get("HOME", ""))
  if not home.is_absolute():
    raise TermcfgError(2, "work_invalid_home", "work --help")
  expected = home / ".config" / "herdr" / "config.toml"
  xdg = os.environ.get("XDG_CONFIG_HOME")
  override = os.environ.get("HERDR_CONFIG_PATH")
  if ((xdg is not None and Path(xdg) != home / ".config") or
      (override is not None and Path(override) != expected)):
    raise TermcfgError(2, "work_unsupported_config_location", "work --help")
  return expected


def prepared_config():
  """缺文件不能交给原生默认值；启动前另作官方完整加载诊断。"""
  import tomllib
  import stat
  from agentcfg.paths import read_private_file, PathError
  path = check_config_location()
  try:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
      raise TermcfgError(4, "work_unsafe_native_config", "termcfg doctor --component herdr")
    content = read_private_file(path)
    value = tomllib.loads(content.decode("utf-8"))
    if (value.get("terminal", {}).get("default_shell") != "rotom-work-shell" or
        value.get("terminal", {}).get("shell_mode") != "non_login" or
        value.get("session", {}).get("resume_agents_on_restore") is not False):
      raise TermcfgError(5, "work_native_config_not_prepared", "termcfg doctor --component herdr")
    return path, hashlib.sha256(content).hexdigest()
  except TermcfgError:
    raise
  except PathError:
    raise TermcfgError(4, "work_unsafe_native_config", "termcfg doctor --component herdr") from None
  except (OSError, UnicodeError, ValueError, AttributeError):
    raise TermcfgError(5, "work_native_config_not_prepared", "termcfg doctor --component herdr") from None


def validate_native_config(binary, deadline):
  import subprocess
  path, digest = prepared_config()
  environment = dict(os.environ, HERDR_CONFIG_PATH=str(path))
  try:
    result = subprocess.run([binary, "config", "check"], env=environment,
      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      timeout=deadline.remaining(5), check=False)
    if result.returncode != 0 or prepared_config() != (path, digest):
      raise TermcfgError(5, "work_native_config_diagnostics_failed", "termcfg doctor --component herdr")
  except (OSError, subprocess.TimeoutExpired):
    raise TermcfgError(5, "work_native_config_diagnostics_failed", "termcfg doctor --component herdr") from None


def settings_from_document(document, *, local, repo_root=ROOT, adapter_schemas=None):
  """校验普通文档；编辑与文件读取复用，不解析秘密或归一运行路径。"""
  from agentcfg.config import validate_work_input
  from agentcfg.schema import ConfigError, validate_document
  try:
    validate_document("local", document, adapter_schemas=adapter_schemas)
    validate_work_input(document)
    data = document["machine"]
    work = data.get("work")
    if not work:
      raise TermcfgError(2, "work_configuration_required", "work --help")
    session = work["session"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", session):
      raise TermcfgError(2, "work_invalid_session", "work --help")
    model = work.get("model")
    structured = None
    if model == "structured-v1":
      from .work_projects import normalize_work
      structured = normalize_work(work, local_path=local)
    return WorkSettings(Path(local).absolute(), executable_name(work["herdr_binary"]), session,
      executable_name(data["editor"]) if "editor" in data else None,
      work.get("pi_profile"), work.get("dsh_profile"),
      executable_name(work["codex_binary"]) if "codex_binary" in work else None,
      work.get("codex_daemon", False), Path(repo_root), model,
      structured)
  except TermcfgError:
    raise
  except (ConfigError, OSError, ValueError, KeyError, TypeError):
    raise TermcfgError(2, "work_invalid_configuration", "work --help") from None


def read_settings(*, machine=None, local=None, repo_root=ROOT):
  from agentcfg.cli import local_path
  from agentcfg.config import load_local
  from agentcfg.paths import xdg_config_home, safe_id
  from agentcfg.schema import ConfigError
  from agentcfg.storage import Conflict
  if machine is not None and local is not None:
    raise TermcfgError(2, "work_selector_conflict", "work --help")
  try:
    if local is None:
      identifier = machine or "default"
      safe_id(identifier)
      path = xdg_config_home() / "agentcfg" / "machines" / (identifier + ".toml")
    else:
      path = local_path(local)
    adapter_schemas = None
    try:
      config, _ = load_local(path, load_credentials=False)
    except ConfigError as error:
      if error.code != "adapter-schema":
        raise
      # 只有原生覆盖确需上下文时才加载完整公共目录，再走同一严格校验。
      from agentcfg.workspace import load_public_catalog
      catalog, _ = load_public_catalog(repository=repo_root)
      adapter_schemas = catalog.adapter_schemas
      config, _ = load_local(path, adapter_schemas=adapter_schemas, load_credentials=False)
    return settings_from_document(config.data, local=path, repo_root=repo_root, adapter_schemas=adapter_schemas)
  except TermcfgError:
    raise
  except Conflict:
    raise TermcfgError(4, "work_unsafe_local_configuration", "work --help") from None
  except (ConfigError, OSError, ValueError, KeyError):
    raise TermcfgError(2, "work_invalid_configuration", "work --help") from None


def shell_command():
  value = os.environ.get("SHELL") or "/bin/sh"
  executable = resolve_executable(value)
  if Path(executable) == (ROOT / "rotom-work-shell").resolve():
    raise TermcfgError(2, "work_recursive_shell", "work --help")
  return [executable]


def _prepared_agent(settings, role, profile):
  from agentcfg.workspace import load_workspace
  from agentcfg.storage import Tree, Conflict, StateError
  from agentcfg.deployment import read_state
  from agentcfg.schema import ConfigError
  from agentcfg.paths import PathError
  from agentcfg.execution_environment import declarations, caller_paths
  try:
    workspace = load_workspace(settings.local_path, profile=profile, repository=settings.repo_root)
    if workspace.agent != role:
      raise TermcfgError(2, "work_profile_agent_mismatch", "work --help")
    with Tree(workspace.state_root) as state:
      if state.read("pending.json"):
        raise conflict_error()
      current = read_state(state)["current"]
      if not current or current["binding"] != workspace.binding:
        raise TermcfgError(5, "work_agent_not_deployed", "agentcfg plan")
      contract = current["launch"]
      if (declarations(contract["machine"]) != declarations(workspace.resolved.data["machine"]) or
          ("environment_version" in contract and (contract["environment_version"] != 1 or
            contract.get("caller_paths") != caller_paths()))):
        raise TermcfgError(4, "work_agent_environment_changed", "agentcfg plan")
      validate_runtime_binding = getattr(workspace.adapter, "validate_runtime_binding", None)
      if validate_runtime_binding is not None:
        validate_runtime_binding(workspace, contract.get("adapter_binding"))
    identity = contract.get("runtime_identity", contract["lock_identity"])
    if workspace.backend.status(workspace, identity) != "installed":
      raise TermcfgError(5, "work_agent_runtime_not_prepared", "agentcfg sync")
    # 旧入口忽略返回值；结构化入口另行校验完整性，不保存原始 launch 正文。
    return {"generation": current.get("generation"), "identity": identity,
      "policy": contract.get("environment_policy", "legacy")}
  except TermcfgError:
    raise
  except ConfigError:
    raise TermcfgError(2, "work_profile_invalid", "agentcfg validate") from None
  except Conflict:
    raise TermcfgError(4, "work_agent_deployment_conflict", "agentcfg plan") from None
  except StateError as error:
    raise TermcfgError(error.exit_code, "work_agent_preparation_failed", "agentcfg plan") from None
  except (OSError, ValueError, PathError):
    raise TermcfgError(5, "work_agent_not_prepared", "agentcfg plan") from None


def conflict_error():
  return TermcfgError(4, "work_agent_recovery_pending", "agentcfg plan")


def prepare_tool(settings, role, root):
  if role in ("shell", "build", "debug"):
    return shell_command()
  if role == "edit":
    if settings.editor is None:
      raise TermcfgError(2, "work_editor_choice_required", "work --help")
    return [resolve_executable(settings.editor)]
  if role in ("pi", "dsh"):
    profile = getattr(settings, role + "_profile")
    if not profile:
      raise TermcfgError(2, "work_agent_profile_required", "work --help")
    _prepared_agent(settings, role, profile)
    entry = resolve_executable(str(settings.repo_root / "agentcfg"))
    return [entry, *settings.selectors, "--profile", profile, "run", role, "--cwd", str(root)]
  if role == "codex":
    if settings.codex_binary is None:
      raise TermcfgError(2, "work_codex_choice_required", "work --help")
    return [resolve_executable(settings.codex_binary), *([] if settings.codex_daemon else ["--no-daemon"])]
  raise TermcfgError(2, "work_invalid_role", "work --help")


def _existing_directory(value):
  try:
    path = Path(literal(os.fspath(value)))
    if not path.is_absolute():
      raise ValueError()
    path = path.resolve(strict=True)
    if not path.is_dir():
      raise ValueError()
    return path
  except TermcfgError:
    raise
  except (OSError, ValueError, TypeError, RuntimeError):
    raise TermcfgError(2, "work_start_directory_invalid", "work --help") from None


def resolve_type_start(definition, workspace_start, caller_home):
  """类型目录只从固定工作区与捕获 HOME 解析，不求值或创建目录。"""
  if (not isinstance(definition, dict) or set(definition) - {"label", "launcher", "cwd"}
      or not {"label", "launcher"} <= set(definition)
      or definition["launcher"] not in ("shell", "editor", "pi", "dsh", "codex")):
    raise TermcfgError(2, "work_invalid_type_definition", "work --help")
  literal(definition["label"])
  start = _existing_directory(workspace_start)
  home = _existing_directory(caller_home)
  cwd = definition.get("cwd", {"from": "workspace_start"})
  if not isinstance(cwd, dict):
    raise TermcfgError(2, "work_invalid_type_cwd", "work --help")
  if cwd == {"from": "workspace_start"}:
    return start
  if set(cwd) != {"path"}:
    raise TermcfgError(2, "work_invalid_type_cwd", "work --help")
  value = literal(cwd["path"])
  target = home / value[2:] if value.startswith("~/") else Path(value)
  return _existing_directory(target if target.is_absolute() else start / target)


def _checked_paths(paths):
  if not isinstance(paths, dict) or set(paths) - set(PATH_NAMES) or "HOME" not in paths:
    raise TermcfgError(2, "work_invalid_launch_paths", "work --help")
  result = {}
  for name in PATH_NAMES:
    value = paths.get(name)
    if value is None and name != "HOME":
      result[name] = None
      continue
    if value is None:
      raise TermcfgError(2, "work_invalid_launch_paths", "work --help")
    value = literal(value)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
      raise TermcfgError(2, "work_invalid_launch_paths", "work --help")
    if name == "HOME":
      _existing_directory(value)
    # 不 resolve：已部署的 caller_paths 使用原始环境字面值。
    result[name] = value
  return result


def capture_paths(home=None):
  paths = {name: os.environ.get(name) for name in PATH_NAMES}
  if home is not None:
    try:
      paths["HOME"] = os.fspath(home)
    except TypeError:
      raise TermcfgError(2, "work_invalid_launch_paths", "work --help") from None
  return _checked_paths(paths)


@contextmanager
def bound_paths(paths):
  """仅临时恢复标准路径边界；其它变量与原生 HERDR 身份保持原状。"""
  selected = _checked_paths(paths)
  before = {name: os.environ.get(name) for name in PATH_NAMES}
  try:
    for name, value in selected.items():
      if value is None:
        os.environ.pop(name, None)
      else:
        os.environ[name] = value
    yield
  finally:
    for name, value in before.items():
      if value is None:
        os.environ.pop(name, None)
      else:
        os.environ[name] = value


def prepare_launch(settings, definition, workspace_start, *, home=None, fixed=None):
  """返回当前请求的安全启动契约；固定绑定的漂移由父流程比较。"""
  from jsonschema import Draft202012Validator
  from .work_state import TYPE_SCHEMA, launch_digest
  if fixed is None:
    paths = capture_paths(home)
  else:
    if not Draft202012Validator(TYPE_SCHEMA).is_valid(fixed):
      raise TermcfgError(4, "work_type_binding_invalid", "work status")
    paths = _checked_paths(fixed["launch"]["paths"])
    if (fixed["captured_home"] != paths["HOME"] or
        fixed["digest"] != launch_digest(fixed["cwd"], fixed["captured_home"], fixed["launch"])):
      raise TermcfgError(4, "work_type_binding_invalid", "work status")
  captured_home = paths["HOME"]
  cwd = resolve_type_start(definition, workspace_start, captured_home)
  launcher = definition["launcher"]
  runtime = None
  with bound_paths(paths):
    if launcher in ("pi", "dsh"):
      profile = getattr(settings, launcher + "_profile")
      if not profile:
        raise TermcfgError(2, "work_agent_profile_required", "work --help")
      runtime = _prepared_agent(settings, launcher, profile)
      if (not isinstance(runtime, dict) or set(runtime) != {"generation", "identity", "policy"}
          or not isinstance(runtime["generation"], str)
          or re.fullmatch(r"[a-f0-9]{64}", runtime["generation"]) is None
          or runtime["policy"] not in ("legacy", "caller", "isolated")
          or not isinstance(runtime["identity"], str) or not runtime["identity"]):
        raise TermcfgError(5, "work_agent_runtime_receipt_invalid", "agentcfg plan")
      try:
        literal(runtime["identity"])
      except TermcfgError:
        raise TermcfgError(5, "work_agent_runtime_receipt_invalid", "agentcfg plan") from None
      entry = resolve_executable(str(settings.repo_root / "agentcfg"))
      argv = [entry, *settings.selectors, "--profile", profile, "run", launcher, "--cwd", str(cwd)]
    elif launcher == "shell" and fixed is not None and fixed["launch"]["launcher"] == "shell":
      argv = [resolve_executable(fixed["launch"]["argv"][0])]
      if Path(argv[0]) == (ROOT / "rotom-work-shell").resolve():
        raise TermcfgError(2, "work_recursive_shell", "work --help")
    else:
      argv = prepare_tool(settings, "edit" if launcher == "editor" else launcher, cwd)
  launch = {"launcher": launcher, "argv": argv, "runtime": deepcopy(runtime), "paths": paths}
  for item in argv:
    literal(item)
  result = {"cwd": str(cwd), "captured_home": captured_home, "launch": launch,
    "digest": launch_digest(cwd, captured_home, launch), "default": None, "sequence": 0, "instances": {}}
  if not Draft202012Validator(TYPE_SCHEMA).is_valid(result):
    raise TermcfgError(2, "work_invalid_launch_contract", "work --help")
  return result
