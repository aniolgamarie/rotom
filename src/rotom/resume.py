"""恢复交接及可信 Python 测试接缝；实际后端按精确组合逐次核验。"""
from dataclasses import replace
from pathlib import Path
import shlex

from agentcfg.presentation import _text
from agentcfg.sessions import KnownSession, ResumeCoordinator, SessionError, SessionIndex, from_run_records


def _local_path(scope):
  from agentcfg.cli import local_path
  from agentcfg.paths import xdg_config_home
  return local_path(scope.local) if scope.local is not None else (
    xdg_config_home() / "agentcfg" / "machines" / ((scope.machine or "default") + ".toml"))


def load_known(scope):
  """只读所选机器的受管归属记录，不读取原生会话或模型/凭据。"""
  from agentcfg.lifecycle import observation_guard
  from agentcfg.dsh_sessions import scope_key
  from agentcfg.local import available_profiles
  from agentcfg.run_owners import Registry
  from agentcfg.storage import Tree
  from agentcfg.workspace import load_instance_workspaces
  local = _local_path(scope)
  selected = {profile: agent for profile, agent in available_profiles()
    if scope.agent in (None, agent) and scope.profile in (None, profile)}
  workspaces = load_instance_workspaces(Path(local), list(selected))
  rows = []
  exact_scope = None
  for workspace in workspaces:
    if (workspace.agent != selected.get(workspace.profile)
        or scope.agent not in (None, workspace.agent)):
      raise SessionError(4, "session_profile_source_changed")
    machine_ref = {key: workspace.binding[key] for key in ("machine", "local")}
    key = scope_key(machine_ref)
    if exact_scope is not None and key != exact_scope:
      raise SessionError(4, "session_scope_changed")
    exact_scope = key
    with Tree(workspace.instance) as instance:
      if instance.fd is None:
        if workspace.state_root.exists() or workspace.state_root.is_symlink():
          raise SessionError(4, "session_instance_missing")
        continue
    with observation_guard(workspace):
      records = Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()
    rows.extend(from_run_records(records, scope=key, machine_ref=machine_ref, profile=scope.profile))
    if workspace.agent == "pi":
      from agentcfg.pi_session_observation import from_records
      rows.extend(from_records(workspace, records))
  if exact_scope is None:
    raise SessionError(2, "invalid_session_scope")
  return exact_scope, tuple(rows)


class CandidateResume:
  """回调由可信调用方提供；不从用户参数、环境或配置启用。"""

  def __init__(self, load_known, backend_for, *, lookup_explicit=None, lookup_profiles=None):
    if (not callable(load_known) or not callable(backend_for)
        or lookup_explicit is not None and not callable(lookup_explicit)
        or lookup_profiles is not None and not callable(lookup_profiles)):
      raise ValueError("invalid candidate callbacks")
    self._load_known = load_known
    self._backend_for = backend_for
    self._lookup_explicit = lookup_explicit
    self._lookup_profiles = lookup_profiles

  def dispatch(self, invocation, args):
    context = invocation.context
    gateway, policy, scope = context.input_gateway, context.input_policy, context.scope

    def show(message):
      try:
        print(_text(message), file=gateway.stderr, flush=True)
      except Exception:
        # 展示异常不改变已经派发的进程或原生退出结果。
        pass

    def command(target):
      tokens = [context.display_prefix, "resume", target.ref.agent]
      tokens += ["--local", scope.local] if scope.local is not None else ["--machine", scope.machine]
      return shlex.join([*tokens, "--profile", target.profile, "--session", target.ref.native_ref, "--here"])

    def description(target):
      status = "不可自动恢复" if (target.confirmation == "unknown" or target.cwd_status == "unknown" or target.cwd is None) else "历史候选"
      return _text(f"{target.ref.agent} / {target.profile} / {target.ref.backend} / {target.ref.native_home_ref} / {target.ref.native_ref} / cwd={target.cwd} / {status}")

    try:
      key, known = self._load_known(scope)
      index = SessionIndex(known)
      agent = scope.agent
      if agent is None and scope.profile is not None:
        from .cli import _profile_tool
        agent = _profile_tool(scope.profile)
      rows = index.candidates(scope=key, agent=agent, profile=scope.profile, native_ref=args.session)
      explicit_id = args.session
      if not rows:
        if agent is None and self._lookup_explicit is not None:
          # 只列公开配方提供的工具；选择不改变 machine/local 或授予恢复能力。
          from agentcfg.local import available_profiles
          public_tools = {tool for _, tool in available_profiles()}
          labels = {"dsh": "DSH（受完整运行组合约束）", "pi": "Pi（受完整运行组合约束；保护限 Rotom 合作实例）",
            "omp": "OMP（受完整运行组合约束）"}
          choices = [(tool, labels[tool]) for tool in ("dsh", "pi", "omp") if tool in public_tools]
          if not choices:
            raise SessionError(5, "lookup_tool_unavailable")
          agent = gateway.choose(choices, policy=policy, label="选择恢复工具")
        if explicit_id is None:
          gateway.require_input(policy)
          if agent is None:
            show("没有已知候选；请输入明确工具和会话 ID 后重试")
            return 5
          explicit_id = gateway.text("明确 session ID（需公开查询核验）", policy=policy)
          from agentcfg.cli import selection_id
          explicit_id = selection_id(explicit_id)
        if agent is None or self._lookup_explicit is None:
          show("未知会话缺少公开归属核验能力；请在官方 TUI 人工选择目标")
          return 5
        effective_scope = scope
        if scope.profile is None and self._lookup_profiles is not None:
          profiles = tuple(self._lookup_profiles(scope, agent))
          from agentcfg.cli import selection_id
          if not profiles or any(selection_id(profile) != profile for profile in profiles) or len(set(profiles)) != len(profiles):
            raise SessionError(5, "lookup_profile_unavailable")
          profile = profiles[0] if len(profiles) == 1 else gateway.choose(
            [(profile, _text(profile)) for profile in profiles], policy=policy, label="选择明确恢复配方")
          effective_scope = replace(scope, profile=profile, agent=agent)
        target = self._lookup_explicit(effective_scope, agent, explicit_id)
        if (type(target) is not KnownSession or target.scope != key or target.ref.agent != agent
            or target.ref.native_ref != explicit_id or effective_scope.profile is not None and target.profile != effective_scope.profile):
          raise SessionError(5, "explicit_session_unverified")
      elif len(rows) == 1 and explicit_id is not None:
        target = rows[0]
      else:
        selected = gateway.choose([(str(i), description(row)) for i, row in enumerate(rows)],
          policy=policy, label="选择完整恢复目标")
        target = rows[int(selected)]
      show("请求恢复：" + description(target))
      show("同范围当前终端恢复命令：" + command(target))
      if args.original or args.new_tab:
        show("所选终端位置能力尚未准入；可在现有官方 TUI 人工选择目标")
        return 5
      if target.confirmation == "unknown" or target.cwd_status == "unknown" or target.cwd is None:
        show("会话归属或 cwd 未知，不可自动恢复；请在官方 TUI 人工检查")
        return 5
      if target.ref.agent == "omp":
        show("OMP 在原生写入冲突时可能生成分叉 session；请核对界面实际 ID 后手动继续。")

      from .manual_continue import offer
      offer(context, description(target))

      pending_shown = False
      def notice(outcome):
        nonlocal pending_shown
        if outcome.status == "launch_dispatched" and outcome.exit_code is None and not pending_shown:
          pending_shown = True
          show("已发起恢复，加载待确认；请在 TUI 检查；未发送继续")
          show("人工继续：先核对会话 ID、原目录和历史；确认后自行聚焦输入框，"
            "手工输入或复制所需指令（例如：继续）。Rotom 不操作剪贴板或发送按键。")
      outcome = ResumeCoordinator(self._backend_for(target), notice=notice).resume(target, location="here")
      if outcome.exit_code is not None:
        show(f"原生进程已退出（退出码 {outcome.exit_code}）；加载未确认；未发送继续")
        return outcome.exit_code
      if outcome.status == "unknown":
        show("恢复结果未知；请在 TUI 检查；未发送继续；不自动重试")
        return 4
      if outcome.status == "restored":
        show("实际加载已确认；未发送继续")
      return 0 if outcome.status in ("launch_dispatched", "restored") else 4
    except SessionError as error:
      show("恢复请求未能确认；未发送继续；请检查所选范围与官方 TUI")
      return error.code



def backend_for_workspace(workspace, target, *, expected_deployment=None):
  options = {"expected_deployment": expected_deployment} if expected_deployment is not None else {}
  if workspace.agent == "dsh" and target.ref.agent == "dsh":
    from agentcfg.dsh_sessions import DshResumeCandidate
    return DshResumeCandidate(workspace, **options)
  if workspace.agent == "pi" and target.ref.agent == "pi":
    from agentcfg.tool_sessions import PiResumeCandidate
    return PiResumeCandidate(workspace, **options)
  if workspace.agent == "omp" and target.ref.agent == "omp":
    from agentcfg.tool_sessions import OmpResumeCandidate
    return OmpResumeCandidate(workspace, **options)
  raise SessionError(5, "candidate_tool_unavailable")


def dsh_candidate():
  """保留历史工厂名；三工具的精确组合与现场条件由各后端核验。"""
  from agentcfg.dsh_sessions import scope_key
  from agentcfg.local import available_profiles
  from agentcfg.workspace import load_workspace
  bindings = {}

  def load(scope):
    if scope.agent not in (None, "dsh", "pi", "omp"):
      raise SessionError(5, "candidate_tool_unavailable")
    key, rows = load_known(scope)
    local = _local_path(scope)
    if (key in bindings and bindings[key] != local
        or any(saved == local and old_key != key for old_key, saved in bindings.items())):
      raise SessionError(4, "candidate_scope_rebound")
    bindings[key] = local
    return key, rows

  def workspace(local, profile, key):
    selected = load_workspace(local, profile)
    if (selected.agent not in ("dsh", "pi", "omp") or selected.profile != profile
        or scope_key(selected.binding) != key):
      raise SessionError(4, "candidate_workspace_changed")
    return selected

  def backend(target):
    local = bindings.get(target.scope)
    if local is None:
      raise SessionError(4, "candidate_scope_unverified")
    return backend_for_workspace(workspace(local, target.profile, target.scope), target)

  def lookup(scope, agent, identifier):
    if agent not in ("dsh", "pi", "omp"):
      raise SessionError(5, "candidate_tool_unavailable")
    local = _local_path(scope)
    keys = [key for key, saved in bindings.items() if saved == local]
    if len(keys) != 1 or scope.profile is None:
      raise SessionError(4, "candidate_scope_unverified")
    selected = workspace(local, scope.profile, keys[0])
    if selected.agent != agent:
      raise SessionError(2, "candidate_tool_profile_mismatch")
    from agentcfg.tool_maintenance import lookup_session
    return lookup_session(selected, identifier)

  def profiles(scope, agent):
    if agent not in ("dsh", "pi", "omp"):
      raise SessionError(5, "candidate_tool_unavailable")
    return tuple(profile for profile, tool in available_profiles() if tool == agent)

  return CandidateResume(load, backend, lookup_explicit=lookup, lookup_profiles=profiles)
