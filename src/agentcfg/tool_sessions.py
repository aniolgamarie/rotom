"""Pi/OMP 官方 CLI 精确路径恢复；请求、派发与实际加载分别记录。"""
from dataclasses import replace
from pathlib import Path
import sys

from . import dsh_process, run_owners, runtime
from .dsh_sessions import scope_key
from .process import DependencyError
from .resume_attempts import ResumeAttempts
from .schema import ConfigError
from .secrets import CredentialError
from .sessions import HandoffResumeBackend, KnownSession, LaunchReceipt, SessionError, _resume_target, session_capability
from .storage import Conflict, StateError
from .tool_session_headers import lookup, recheck


class OmpResumeCandidate(HandoffResumeBackend):
  """原生首次写入按 session ID 取得 writer；只读打开不代表持有写锁。"""

  def __init__(self, workspace, *, expected_deployment=None):
    self.workspace = workspace
    self.expected_deployment = expected_deployment

  def resume_session(self, target, *, location, before_dispatch, after_dispatch):
    workspace = self.workspace
    _resume_target(target, location, None)
    if (type(target) is not KnownSession or workspace.agent != "omp" or target.ref.agent != "omp"
        or target.ref.backend != "managed" or target.profile != workspace.profile
        or target.scope != scope_key(workspace.binding)):
      raise SessionError(2, "omp_resume_scope_mismatch")
    if sys.platform != "linux":
      raise SessionError(5, "omp_resume_platform_unavailable")
    header = lookup(workspace, target.ref.native_ref)
    if header.known.ref != target.ref or header.known.cwd != target.cwd:
      raise SessionError(4, "omp_resume_target_changed")

    def launch(selected, spec, env, lease, contract, *, run_id, lifecycle_fd, package_fd, owner_registry=None):
      lock = selected.backend.read_lock(selected.repository)
      capability = session_capability(agent="omp", backend="managed", runtime_identity=lock.identity,
        observer_identity="none", platform=sys.platform, location=location)
      if (lock.metadata["tag"] != "v18.12.6"
          or lock.metadata["commit"] != "45c35e40c46166dc726ccc52f5d27f40f2449f99"
          or lock.identity != contract["lock_identity"]
          or capability.handoff != "admitted"
          or owner_registry is None or type(owner_registry) is run_owners.Registry
          or str(spec.cwd) != target.cwd or list(spec.argv) != [*contract["argv"], "--no-title"]):
        raise SessionError(5, "omp_resume_combination_unavailable")
      recheck(selected, header)
      # 精确路径的公开 CLI 分支使用 throwIfMissing；不走 ID 前缀或跨目录回退。
      resumed = replace(spec, argv=(*spec.argv, "--resume", str(header.path)))
      owner = owner_registry.snapshot()[run_id]
      attempt = ResumeAttempts(selected.state_root / "resume-attempts", selected.binding).begin(target, owner)
      fds = tuple(fd for fd in (lifecycle_fd, lease, package_fd) if type(fd) is int)
      from .dsh_stop_control import default_factory
      control = default_factory(selected, owner, instance_fd=lifecycle_fd, state_fd=lease)
      def before(run):
        recheck(selected, header)
        before_dispatch(run)
      code = dsh_process.launch(resumed, env, fds, run_id=run_id,
        owner_registry=owner_registry, manager_identity=owner["manager_identity"],
        before_dispatch=before, after_dispatch=after_dispatch, attempt=attempt,
        resume=True, control_factory=control)
      return LaunchReceipt(run_id=run_id, exit_code=code)

    try:
      options = {"expected_deployment": self.expected_deployment} if self.expected_deployment is not None else {}
      return runtime.run(workspace, cwd=Path(target.cwd), arguments=(), resume_operation=launch, **options)
    except Conflict:
      raise SessionError(4, "omp_resume_conflict") from None
    except ConfigError:
      raise SessionError(2, "omp_resume_configuration_invalid") from None
    except DependencyError:
      raise SessionError(5, "omp_resume_runtime_unavailable") from None
    except CredentialError:
      raise SessionError(3, "omp_resume_credentials_unavailable") from None
    except StateError:
      raise SessionError(6, "omp_resume_state_unavailable") from None


class PiResumeCandidate(HandoffResumeBackend):
  """公开扩展保护 Rotom 合作写入；不推导外部 Pi 排他或实际加载事实。"""

  def __init__(self, workspace, *, expected_deployment=None):
    self.workspace = workspace
    self.expected_deployment = expected_deployment

  def resume_session(self, target, *, location, before_dispatch, after_dispatch):
    workspace = self.workspace
    _resume_target(target, location, None)
    if (type(target) is not KnownSession or workspace.agent != "pi" or target.ref.agent != "pi"
        or target.ref.backend != "managed" or target.profile != workspace.profile
        or target.scope != scope_key(workspace.binding)):
      raise SessionError(2, "pi_resume_scope_mismatch")
    if sys.platform != "linux":
      raise SessionError(5, "pi_resume_platform_unavailable")
    header = lookup(workspace, target.ref.native_ref)
    if header.known.ref != target.ref or header.known.cwd != target.cwd:
      raise SessionError(4, "pi_resume_target_changed")

    def launch(selected, spec, env, lease, contract, *, run_id, lifecycle_fd, package_fd):
      lock = selected.backend.read_lock(selected.repository)
      from .pi_session_guard import source_identity
      capability = session_capability(agent="pi", backend="managed", runtime_identity=lock.identity,
        observer_identity=source_identity(), platform=sys.platform, location=location)
      if (lock.metadata["host"]["package"] != "@earendil-works/pi-coding-agent"
          or lock.metadata["host"]["version"] != "1.3.0"
          or lock.identity != contract["lock_identity"]
          or capability.handoff != "admitted"
          or str(spec.cwd) != target.cwd or list(spec.argv) != contract["argv"]):
        raise SessionError(5, "pi_resume_combination_unavailable")
      registry = run_owners.Registry(selected.state_root / "run-owners", selected.binding)
      owner = registry.snapshot()[run_id]
      fds = tuple(fd for fd in (lifecycle_fd, lease, package_fd) if type(fd) is int)
      # --resume 是原生 picker；--session 精确文件路径才绑定已核验的目标。
      resumed = replace(spec, argv=(*spec.argv, "--session", str(header.path)))
      from .pi_session_guard import prepare
      with prepare(selected, resumed, env, fds, run_id=run_id, target=header) as prepared:
        guarded_spec, guarded_env, guarded_fds = prepared
        attempt = ResumeAttempts(selected.state_root / "resume-attempts", selected.binding).begin(target, owner)
        from .dsh_stop_control import default_factory
        control = default_factory(selected, owner, instance_fd=lifecycle_fd, state_fd=lease)
        def before(run):
          recheck(selected, header)
          before_dispatch(run)
        code = dsh_process.launch(guarded_spec, guarded_env, guarded_fds, run_id=run_id,
          owner_registry=registry, manager_identity=owner["manager_identity"],
          before_dispatch=before, after_dispatch=after_dispatch, attempt=attempt,
          resume=True, control_factory=control)
      return LaunchReceipt(run_id=run_id, exit_code=code)

    try:
      options = {"expected_deployment": self.expected_deployment} if self.expected_deployment is not None else {}
      return runtime.run(workspace, cwd=Path(target.cwd), arguments=(), resume_operation=launch, **options)
    except Conflict:
      raise SessionError(4, "pi_resume_conflict") from None
    except ConfigError:
      raise SessionError(2, "pi_resume_configuration_invalid") from None
    except DependencyError:
      raise SessionError(5, "pi_resume_runtime_unavailable") from None
    except CredentialError:
      raise SessionError(3, "pi_resume_credentials_unavailable") from None
    except StateError:
      raise SessionError(6, "pi_resume_state_unavailable") from None
