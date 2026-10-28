"""锁定 Linux DSH 的官方恢复交接；缺加载回执时保持待确认。

沿用部署启动路径和原生 writer，缺加载回执时只返回派发事实。
只读接受有界配置形状，不解释任意 Cordis patch，也不改用户原生配置。
"""

import hashlib
from contextlib import nullcontext
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from . import deployment, dsh_process, native, run_owners, runtime
from .process import DependencyError
from .resume_attempts import PendingResume, ResumeAttempts
from .schema import ConfigError
from .secrets import CredentialError
from .sessions import HostResumeBackend, KnownSession, LaunchReceipt, SessionError, SessionRef, _resume_target, _token, session_capability
from .storage import Conflict, StateError, Tree, instance_lock


_PROFILE_PATCH = "dsh-home/profiles/agentcfg/cordis.patch.yml"
_PROFILE_ROWS = frozenset({"llm-pi-ai", "agent-default-model", "auto-review", "dsh-tui"})
_PINNED_PACKAGES = {"@deepseek-ai/dsh": "0.2.1-rc.2",
  "@deepseek-harness-tui/dsh-tui": "0.16.1"}


def scope_key(binding):
  """查询 scope 仅绑定 machine/local；配方另作显式过滤，不借用启动默认。"""
  try:
    if type(binding) is not dict or not _token(binding["machine"]):
      raise ValueError()
    run_owners._absolute(binding["local"])
    value = {key: binding[key] for key in ("machine", "local")}
    return hashlib.sha256(deployment.json_bytes(value)).hexdigest()
  except (KeyError, TypeError, ValueError):
    raise SessionError(2, "invalid_session_scope") from None


def _plain(value, stack=None, budget=None):
  # 同时限制逻辑展开量；只缓存 alias 节点会把指数工作留给后续投影/JSON 比较。
  budget = [16384, 1024 * 1024] if budget is None else budget
  budget[0] -= 1
  if budget[0] < 0:
    return False
  if type(value) is str:
    budget[1] -= len(value)
    return budget[1] >= 0
  # 绝不求值原生 !!js；循环引用和过深的 YAML 也不能进入准入检查。
  if value is None or type(value) in (bool, int):
    return True
  if type(value) is float:
    return math.isfinite(value)
  if type(value) not in (dict, list) and not isinstance(value, native.CordisDocument):
    return False
  stack = set() if stack is None else stack
  if id(value) in stack or len(stack) >= 64:
    return False
  stack.add(id(value))
  try:
    if isinstance(value, dict):
      return all(type(key) is str and key != "__jsExpr" and _plain(key, stack, budget)
        and _plain(child, stack, budget)
        for key, child in value.items())
    return all(_plain(child, stack, budget) for child in value)
  finally:
    stack.remove(id(value))


def _covered(value, selectors, path=()):
  if path in selectors:
    return True
  return (isinstance(value, dict) and bool(value)
    and all(any(selector[:len(path) + 1] == (*path, key) for selector in selectors)
      and _covered(child, selectors, (*path, key)) for key, child in value.items()))


def _document(tree, relative, *, required=False):
  raw = tree.read(relative, max_bytes=1024 * 1024)
  if raw is None:
    if required:
      raise Conflict("恢复配置缺失；请检查 plan/apply")
    return native.load_cordis(b"[]")
  try:
    return native.load_cordis(raw[0])
  except Exception:
    raise Conflict("恢复配置不是已核验的公开配置形状") from None


def _configuration(workspace, contract):
  # 调用方已持运行租约；这里只读取公开配置及已部署摘要，不打开账号或会话。
  with Tree(workspace.state_root) as state, Tree(workspace.instance) as tree:
    current = deployment.read_state(state)["current"]
    if current is None or current["binding"] != workspace.binding or current["launch"] != contract:
      raise Conflict("恢复部署身份发生变化")
    items = tuple(current["items"].values())
    for relative in ("launch.mjs", "dsh-home/agentcfg.patch.yml"):
      matches = [item for item in items if item["path"] == relative and not item["selector"]]
      if len(matches) != 1 or not deployment.same(deployment.projection(tree, matches[0]), matches[0]["baseline"]):
        raise Conflict("受管恢复启动文件发生漂移；请检查 plan/apply")
    launcher = tree.read("launch.mjs", max_bytes=1024 * 1024)
    if launcher is None or launcher[0] != (workspace.repository / "agents/dsh/templates/launch.mjs").read_bytes():
      raise DependencyError("已部署 launcher 尚未核验该恢复路径")
    home = _document(tree, "dsh-home/cordis.patch.yml")
    if home.rows:
      raise Conflict("原生 HOME patch 尚未核验恢复范围；请在官方 TUI 中人工操作")
    document = _document(tree, _PROFILE_PATCH, required=True)
    if (not _plain(document) or any(type(row) is not str for row in document.rows)
        or set(document) - _PROFILE_ROWS):
      raise Conflict("原生 profile 含未核验的恢复覆盖")
    fields = [item for item in items if item["path"] == _PROFILE_PATCH]
    if (not fields or any(not item["selector"] or item["codec"] != "cordis-yaml"
        or item["ownership"] not in ("fields", "initialize") for item in fields)):
      raise Conflict("受管 profile 字段范围不完整")
    selectors = {deployment.pointer(item["selector"]) for item in fields}
    if not _covered(document, selectors):
      raise Conflict("原生 profile 含未核验的恢复字段")
    for item in fields:
      # 原生 UI 偏好仍由用户拥有；持续受管字段必须等于此次部署基线。
      if item["ownership"] == "fields" and not deployment.same(
          deployment.get_field(document, item["selector"]), item["baseline"]):
        raise Conflict("受管 profile 发生漂移；请检查 plan/apply")
    config = document.get("dsh-tui", {}).get("config", {})
    if (config.get("backend") != "dsh" or config.get("upstreamRetry") is not False
        or any(key in config for key in ("sessionId", "workspace"))):
      raise Conflict("恢复目标、目录或 backend 存在未核验的覆盖")


def _admitted(workspace):
  # 只核准完整锁精确组合；版本相同但其他插件变化也须重新验收。
  if sys.platform != "linux":
    raise DependencyError("当前平台尚未核验该恢复路径")
  lock = workspace.backend.read_lock(workspace.repository)
  capability = session_capability(agent=workspace.agent, backend="managed", runtime_identity=lock.identity,
    observer_identity="none", platform=sys.platform, location="here")
  if capability.handoff != "admitted":
    raise DependencyError("完整运行组合尚未核验该恢复路径")
  return lock


def _contract(workspace, contract):
  """查询与启动共用固定组合/入口边界；不读取凭据或初始化运行包。"""
  lock = _admitted(workspace)
  dependencies = json.loads(lock.package)["dependencies"]
  identity = contract.get("runtime_identity", contract["lock_identity"])
  if (lock.identity != contract["lock_identity"] or identity != lock.identity
      or any(dependencies.get(name) != version for name, version in _PINNED_PACKAGES.items())):
    raise DependencyError("已部署运行组合尚未核验该恢复路径")
  root = workspace.backend.root(workspace, identity)
  expected = ("node", str(workspace.instance / "launch.mjs"), str(root),
    str(workspace.instance / "dsh-home/agentcfg.patch.yml"), "--profile", "agentcfg")
  if tuple(contract["argv"]) != expected or contract.get("environment_policy") != "isolated":
    raise Conflict("恢复启动契约与目标不一致")
  return lock, identity, root, expected


def lookup_metadata(workspace, native_ref):
  """显式 ID 只读核验；不登记 run，不取得 writer，不声称会话已加载。"""
  from .lifecycle import observation_guard
  from .paths import PathError
  if workspace.agent != "dsh" or not _token(native_ref):
    raise SessionError(2, "invalid_metadata_scope")
  try:
    _admitted(workspace)
    # 使用已有物理/状态读租约；查询不能创建目录或锁文件。
    with observation_guard(workspace) as physical, Tree(workspace.state_root) as state:
      if state.fd is None:
        raise Conflict("元数据查询缺少已部署状态")
      try:
        lease = instance_lock(state, shared=True, create=False)
        with lease as state_fd:
          return _lookup_metadata_locked(workspace, state, native_ref, physical, state_fd)
      except FileNotFoundError:
        raise Conflict("元数据查询缺少已有状态租约") from None
  except (Conflict, PathError):
    raise SessionError(4, "metadata_scope_unverified") from None
  except DependencyError:
    raise SessionError(5, "metadata_runtime_unavailable") from None
  except ConfigError:
    raise SessionError(2, "metadata_configuration_invalid") from None
  except (StateError, OSError):
    raise SessionError(6, "metadata_state_unavailable") from None


def _lookup_metadata_locked(workspace, state, native_ref, physical, state_fd):
  from .execution_environment import caller_paths, declarations
  from .toolchain import ensure_compatible_toolchain
  if state.read("pending.json"):
    raise Conflict("存在待恢复部署")
  current = deployment.read_state(state)["current"]
  if current is None or current["binding"] != workspace.binding:
    raise Conflict("元数据查询部署绑定不匹配")
  contract = current["launch"]
  lock, identity, root, _ = _contract(workspace, contract)
  if (contract.get("environment_version") != 1 or contract.get("caller_paths") != caller_paths()
      or declarations(contract["machine"]) != declarations(workspace.resolved.data["machine"])):
    raise Conflict("元数据查询环境契约发生变化")
  _configuration(workspace, contract)
  session_root = workspace.instance / "dsh-home/sessions"
  # 原生目录可不存在；若存在也必须留在显式受管路径内，不能跟随根链接。
  with Tree(session_root, private=False):
    pass
  guard = getattr(workspace.backend, "runtime_guard", None)
  # DSH 包在物理实例内，由上面的物理租约保护；其它包租约只按后端已有契约取得。
  with (guard(workspace, identity) if guard else nullcontext(None)) as package_fd:
    if workspace.backend.status(workspace, identity) != "installed":
      raise DependencyError("元数据查询运行包缺失或损坏")
    workspace.adapter.validate_runtime(workspace, root)
    spec = runtime.decode(contract, workspace.instance, ())
    env, _ = runtime.prepare_environment(workspace, contract, spec)
    if (env.get("DSH_HOME") != str(workspace.instance / "dsh-home")
        or env.get("HOME") != str(workspace.instance / "user-home")
        or env.get("AGENTCFG_DSH_EXECUTION") not in (None, "local")):
      raise Conflict("元数据查询不支持该原生存储归属")
    # 仅保留只读 helper 必需的路径环境，不传 provider 凭据、Node 注入或用户插件参数。
    allowed = {"PATH", "HOME", "LANG", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"}
    env = {key: value for key, value in env.items() if key in allowed}
    if not env.get("PATH"):
      raise DependencyError("元数据查询缺少明确工具链路径")
    fds = tuple(fd for fd in (physical, state_fd, package_fd) if type(fd) is int)
    options = {"cwd": workspace.instance, "env": env, "stdin": subprocess.DEVNULL,
      "capture_output": True, "text": True, "encoding": "utf-8", "timeout": 10, "pass_fds": fds}
    try:
      version = subprocess.run(["node", "--version"], **options)
      if version.returncode != 0:
        raise DependencyError("元数据工具链不可用")
      ensure_compatible_toolchain("Node", lock.metadata["node"], version.stdout.strip())
      script = workspace.repository / "agents/dsh/templates/session-metadata.mjs"
      result = subprocess.run(["node", str(script), str(root), str(session_root), native_ref], **options)
      if result.returncode != 0 or type(result.stdout) is not str or len(result.stdout) > 16384:
        raise ValueError()
      value = json.loads(result.stdout, object_pairs_hook=run_owners._pairs,
        parse_constant=run_owners._invalid_constant)
      if (type(value) is not dict or set(value) != {"status", "session_id", "cwd", "source"}
          or value["status"] != "metadata" or value["source"] != "session-persistence-stat"
          or value["session_id"] != native_ref):
        raise ValueError()
      run_owners._absolute(value["cwd"])
      if os.path.normpath(value["cwd"]) != value["cwd"]:
        raise ValueError()
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError, RecursionError):
      # 10秒预算仅用于无 Agent 的只读 helper；绝不终止或重试恢复宿主。
      raise SessionError(5, "session_metadata_unavailable") from None
    return KnownSession(SessionRef("dsh", "managed", run_owners.native_home_key(
        {"kind": "dsh-home", "path": str(workspace.instance / "dsh-home")}), native_ref),
      scope_key(workspace.binding), workspace.profile, value["cwd"], "historical", "historical",
      time.time_ns(), None)


_WaitUnconfirmed = dsh_process.WaitUnconfirmed


def _launch(spec, env, pass_fds, *, run_id, before_dispatch, after_dispatch, attempt=None,
    owner_registry=None, manager_identity=None, control_factory=None):
  options = {"control_factory": control_factory} if control_factory is not None else {}
  code = dsh_process.launch(spec, env, pass_fds, run_id=run_id,
    before_dispatch=before_dispatch, after_dispatch=after_dispatch, attempt=attempt,
    owner_registry=owner_registry, manager_identity=manager_identity, resume=True, **options)
  return LaunchReceipt(run_id=run_id, exit_code=code)


class DshResumeCandidate(HostResumeBackend):
  """固定完整组合的当前终端交接；每次仍须核验部署与原生 writer。"""

  def __init__(self, workspace, *, expected_deployment=None):
    self.workspace = workspace
    self.expected_deployment = expected_deployment

  def resume_session(self, target, *, location, before_dispatch, after_dispatch):
    workspace = self.workspace
    _resume_target(target, location, None)
    home = str(workspace.instance / "dsh-home")
    if (type(target) is not KnownSession or workspace.agent != "dsh"
        or target.ref.agent != "dsh" or target.ref.backend != "managed"
        or target.profile != workspace.profile or target.scope != scope_key(workspace.binding)
        or target.ref.native_home_ref != run_owners.native_home_key({"kind": "dsh-home", "path": home})
        or not _token(target.ref.native_ref)):
      raise SessionError(2, "dsh_resume_scope_mismatch")

    def launch(selected, spec, env, lease, contract, *, run_id, lifecycle_fd, package_fd):
      _, _, _, expected = _contract(selected, contract)
      if (spec.argv != (*expected, "--resume", target.ref.native_ref)
          or str(spec.cwd) != target.cwd or spec.environment_policy != "isolated"
          or env.get("DSH_HOME") != home or env.get("HOME") != str(selected.instance / "user-home")
          or env.get("AGENTCFG_DSH_EXECUTION") not in (None, "local")):
        raise Conflict("恢复启动契约与目标不一致")
      _configuration(selected, contract)
      _resume_target(target, location, None)
      launch_env = {**env, "DSH_TUI_BACKEND": "dsh", "DSH_TUI_RESUME_SESSION": target.ref.native_ref,
        "DSH_TUI_SESSION_ROOT": str(selected.instance / "dsh-home/sessions")}
      owner_registry = run_owners.Registry(selected.state_root / "run-owners", selected.binding)
      owner = owner_registry.snapshot()[run_id]
      journal = ResumeAttempts(selected.state_root / "resume-attempts", selected.binding)
      attempt = journal.begin(target, owner)
      # intent 先落盘；原生宿主负责严格打开目标及 writer，父进程不预占原生锁。
      pass_fds = tuple(fd for fd in (lifecycle_fd, lease, package_fd) if type(fd) is int)
      from .dsh_stop_control import default_factory
      control = default_factory(selected, owner, instance_fd=lifecycle_fd, state_fd=lease)
      options = {"control_factory": control} if control is not None else {}
      return _launch(spec, launch_env, pass_fds, run_id=run_id, before_dispatch=before_dispatch,
        after_dispatch=after_dispatch, attempt=attempt,
        owner_registry=owner_registry, manager_identity=owner["manager_identity"], **options)

    try:
      _admitted(workspace)
      options = {"expected_deployment": self.expected_deployment} if self.expected_deployment is not None else {}
      return runtime.run(workspace, cwd=Path(target.cwd), arguments=("--resume", target.ref.native_ref),
        resume_operation=launch, **options)
    except PendingResume as error:
      raise SessionError(4, "resume_pending_unconfirmed", pending_run_ids=error.run_ids) from None
    except Conflict:
      raise SessionError(4, "dsh_resume_preflight_conflict") from None
    except ConfigError:
      raise SessionError(2, "dsh_resume_configuration_invalid") from None
    except DependencyError:
      raise SessionError(5, "dsh_resume_runtime_unavailable") from None
    except CredentialError:
      raise SessionError(3, "dsh_resume_credentials_unavailable") from None
    except StateError:
      raise SessionError(6, "dsh_resume_state_unavailable") from None
