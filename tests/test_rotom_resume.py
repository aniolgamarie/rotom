"""恢复协调的协议契约；后端全部为合成实现，不调用宿主公开接口。"""

from contextlib import contextmanager
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def sessions():
  # 尚未实现时是明确 RED，不以 importorskip 隐藏未来工作。
  return importlib.import_module("agentcfg.sessions")


def known(sessions, tmp_path, *, agent="dsh", backend="managed", home="home-a",
    native_ref="session-example", scope="scope-a", profile="dsh-default",
    confirmation="confirmed", cwd_status="confirmed"):
  cwd = tmp_path / (scope + "-" + profile)
  cwd.mkdir(mode=0o700, exist_ok=True)
  ref = sessions.SessionRef(agent=agent, backend=backend,
    native_home_ref=home, native_ref=native_ref)
  return sessions.KnownSession(ref=ref, scope=scope, profile=profile,
    cwd=str(cwd), cwd_status=cwd_status, confirmation=confirmation,
    observed_at_ns=1, run_id="a" * 32)


class FakeBackend:
  """只证明协调器使用有生命期的证据；不代表任何真实后端能力已准入。"""

  def __init__(self, sessions):
    self.sessions = sessions
    self.calls = []
    self.live = False
    self.conflict = False
    self.expire_after_verify = False
    self.bad_loaded_ref = None
    self.bad_loaded_cwd = None
    self.loaded = True
    self.input_ready = False
    self.lookup_missing = False
    self.returned_run_id = "b" * 32

  @contextmanager
  def acquire_writer(self, target):
    self.calls.append(("acquire", target.ref))
    if self.conflict:
      raise self.sessions.SessionError(4, "writer_conflict")
    self.live = True
    witness = self.sessions.WriterEvidence(session=target.ref,
      source="synthetic-native-exclusion", coverage="external-writers",
      is_live=lambda: self.live)
    try:
      yield witness
    finally:
      self.live = False
      self.calls.append(("release", target.ref))

  def verify_session(self, target, evidence):
    assert self.live and evidence.session == target.ref
    self.calls.append(("verify", target.ref))
    if self.lookup_missing:
      raise self.sessions.SessionError(2, "session_not_found")
    if self.expire_after_verify:
      self.live = False
    return target

  def launch_session(self, target, evidence, *, location):
    # 协调器应先拒绝已失效证据，不能让这个 spy 替它完成复核。
    self.calls.append(("launch", target.ref, target.cwd, location, self.live))
    assert self.live
    return self.sessions.LoadReceipt(run_id=self.returned_run_id,
      session=self.bad_loaded_ref or target.ref, cwd=self.bad_loaded_cwd or target.cwd,
      loaded=self.loaded, input_ready=self.input_ready)

  def send_input(self, *args, **kwargs):
    pytest.fail("普通 resume 不能发送继续文本")

  def kill(self, *args, **kwargs):
    pytest.fail("普通 resume 不能因未知或超时强杀")


class DispatchOnlyBackend(FakeBackend):
  """有验证和 writer 保护，只返回派发事实，不提供实际加载结果。"""

  exit_code = None

  def launch_session(self, target, evidence, *, location):
    self.calls.append(("launch", target.ref, target.cwd, location, self.live))
    assert self.live
    return self.sessions.LaunchReceipt(run_id=self.returned_run_id, exit_code=self.exit_code)


def assert_pending(outcome, target, *, status):
  assert outcome.status == status
  assert outcome.requested_session == target.ref
  assert outcome.requested_cwd == target.cwd
  assert outcome.session is None and outcome.cwd is None
  assert outcome.input_ready is False
  assert outcome.continue_status == "not_sent"


def test_same_native_id_is_not_a_global_primary_key(sessions, tmp_path):
  first = known(sessions, tmp_path)
  foreign = known(sessions, tmp_path, scope="scope-b", home="home-b")
  index = sessions.SessionIndex([first, foreign])
  assert index.select(scope="scope-a", native_ref="session-example") == first
  assert index.select(scope="scope-b", native_ref="session-example") == foreign


@pytest.mark.parametrize("different", ["backend", "native_home"])
def test_same_bare_id_in_selected_scope_is_ambiguous(sessions, tmp_path, different):
  first = known(sessions, tmp_path)
  second = known(sessions, tmp_path,
    backend="other-backend" if different == "backend" else "managed",
    home="home-b" if different == "native_home" else "home-a")
  with pytest.raises(sessions.SessionError) as caught:
    sessions.SessionIndex([first, second]).select(scope="scope-a", native_ref="session-example")
  assert caught.value.code == 2


def test_tool_inference_requires_unique_candidate_and_profile_is_hard_constraint(sessions, tmp_path):
  first = known(sessions, tmp_path)
  pi = known(sessions, tmp_path, agent="pi", profile="pi-base", native_ref="pi-session")
  index = sessions.SessionIndex([first, pi])
  assert index.select(scope="scope-a", native_ref="session-example") == first
  with pytest.raises(sessions.SessionError):
    index.select(scope="scope-a")
  with pytest.raises(sessions.SessionError):
    index.select(scope="scope-a", agent="pi", native_ref="session-example")
  with pytest.raises(sessions.SessionError):
    index.select(scope="scope-a", profile="pi-base", native_ref="session-example")


def test_unknown_explicit_id_does_not_choose_recent_or_other_scope(sessions, tmp_path):
  recent = known(sessions, tmp_path, native_ref="recent-session")
  foreign = known(sessions, tmp_path, native_ref="requested-session", scope="scope-b")
  with pytest.raises(sessions.SessionError) as caught:
    sessions.SessionIndex([recent, foreign]).select(scope="scope-a", native_ref="requested-session")
  assert caught.value.code == 2


def test_current_terminal_resume_keeps_recorded_cwd_and_allocates_new_run(sessions, tmp_path, monkeypatch):
  target = known(sessions, tmp_path)
  caller = tmp_path / "different-caller"
  caller.mkdir(mode=0o700)
  monkeypatch.chdir(caller)
  backend = FakeBackend(sessions)
  outcome = sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert outcome.status == "restored" and outcome.run_id != target.run_id
  assert outcome.session == target.ref and outcome.cwd == target.cwd
  assert outcome.input_ready is False
  assert outcome.requested_session == target.ref and outcome.requested_cwd == target.cwd
  assert outcome.continue_status == "not_sent"
  assert [call[0] for call in backend.calls] == ["acquire", "verify", "launch", "release"]
  assert backend.calls[2][2:] == (target.cwd, "here", True)


def test_history_with_exact_native_verification_does_not_require_final_stop_seal(sessions, tmp_path):
  target = known(sessions, tmp_path, confirmation="historical")
  outcome = sessions.ResumeCoordinator(FakeBackend(sessions)).resume(target, location="here")
  assert outcome.status == "restored" and outcome.session == target.ref


@pytest.mark.parametrize("failure", ["missing", "unknown", "conflicting_override"])
def test_bad_original_cwd_never_falls_back_to_caller_directory(sessions, tmp_path, failure):
  target = known(sessions, tmp_path, cwd_status="unknown" if failure == "unknown" else "confirmed")
  if failure == "missing":
    Path(target.cwd).rmdir()
  backend = FakeBackend(sessions)
  options = {"cwd_override": str(tmp_path)} if failure == "conflicting_override" else {}
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here", **options)
  assert caught.value.code in (2, 5) and backend.calls == []


@pytest.mark.parametrize("failure", ["occupied", "expired_after_verify", "missing_native"])
def test_writer_conflict_and_missing_native_session_prevent_launch(sessions, tmp_path, failure):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  backend.conflict = failure == "occupied"
  backend.expire_after_verify = failure == "expired_after_verify"
  backend.lookup_missing = failure == "missing_native"
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert caught.value.code == (2 if failure == "missing_native" else 4)
  assert "launch" not in [call[0] for call in backend.calls]


@pytest.mark.parametrize("failure", ["wrong_id", "wrong_cwd", "wrong_backend", "wrong_home"])
def test_restore_requires_matching_actual_load_not_spawn_or_location(sessions, tmp_path, failure):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  if failure == "wrong_id":
    backend.bad_loaded_ref = sessions.SessionRef(agent="dsh", backend="managed",
      native_home_ref="home-a", native_ref="different-session")
  if failure == "wrong_cwd":
    backend.bad_loaded_cwd = str(tmp_path / "different")
  if failure in ("wrong_backend", "wrong_home"):
    backend.bad_loaded_ref = sessions.SessionRef(agent="dsh",
      backend="other" if failure == "wrong_backend" else target.ref.backend,
      native_home_ref="other-home" if failure == "wrong_home" else target.ref.native_home_ref,
      native_ref=target.ref.native_ref)
  coordinator = sessions.ResumeCoordinator(backend)
  with pytest.raises(sessions.SessionError) as caught:
    coordinator.resume(target, location="here")
  assert caught.value.code == 4
  assert_pending(coordinator.snapshot(), target, status="unknown")
  with pytest.raises(sessions.SessionError) as repeated:
    coordinator.resume(target, location="here")
  assert repeated.value.code == caught.value.code
  assert len([call for call in backend.calls if call[0] == "launch"]) == 1
  assert backend.live is False


def test_absent_public_backend_capability_is_five_and_never_fabricates_success(sessions, tmp_path):
  target = known(sessions, tmp_path)
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(None).resume(target, location="here")
  assert caught.value.code == 5


def test_persisted_no_writer_boolean_is_not_live_evidence(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  @contextmanager
  def stale(_):
    yield {"no_writer": True, "session": target.ref}
  backend.acquire_writer = stale
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert caught.value.code == 5 and backend.calls == []


def test_writer_evidence_for_another_native_home_is_not_reusable(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  other = sessions.SessionRef(agent="dsh", backend="managed", native_home_ref="home-b",
    native_ref=target.ref.native_ref)
  @contextmanager
  def foreign(_):
    yield sessions.WriterEvidence(session=other, source="synthetic-native-exclusion",
      coverage="external-writers", is_live=lambda: True)
  backend.acquire_writer = foreign
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert caught.value.code == 4 and backend.calls == []


@pytest.mark.parametrize("coverage", ["rotom-local", ""])
def test_only_cooperative_or_empty_writer_coverage_is_not_external_exclusion(sessions, tmp_path, coverage):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  @contextmanager
  def local(_):
    yield sessions.WriterEvidence(session=target.ref, source="synthetic-local-lock",
      coverage=coverage, is_live=lambda: True)
  backend.acquire_writer = local
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert caught.value.code == 5 and backend.calls == []


def test_resume_receipt_cannot_reuse_the_old_run_identity(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  backend.returned_run_id = target.run_id
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert caught.value.code == 4


@pytest.mark.parametrize("changed", ["session", "cwd"])
def test_native_verification_cannot_replace_the_explicit_target(sessions, tmp_path, changed):
  from dataclasses import replace
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  original = backend.verify_session
  def verify(selected, evidence):
    original(selected, evidence)
    if changed == "cwd":
      return replace(selected, cwd=str(tmp_path))
    return replace(selected, ref=sessions.SessionRef(agent="dsh", backend="managed",
      native_home_ref="different-home", native_ref=selected.ref.native_ref))
  backend.verify_session = verify
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert caught.value.code == 4
  assert "launch" not in [call[0] for call in backend.calls]


@pytest.mark.parametrize("exit_code", [None, 0])
def test_safe_dispatch_without_load_capability_stays_unconfirmed(sessions, tmp_path, exit_code):
  target = known(sessions, tmp_path)
  backend = DispatchOnlyBackend(sessions)
  backend.exit_code = exit_code
  coordinator = sessions.ResumeCoordinator(backend)
  outcome = coordinator.resume(target, location="here")
  assert_pending(outcome, target, status="launch_dispatched")
  assert outcome.run_id == backend.returned_run_id
  assert outcome.exit_code == exit_code
  assert [call[0] for call in backend.calls] == ["acquire", "verify", "launch", "release"]
  assert coordinator.snapshot() == outcome


@pytest.mark.parametrize("input_ready", [False, True])
def test_no_load_evidence_and_ready_only_are_dispatched_not_failure(sessions, tmp_path, input_ready):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  backend.loaded = False
  backend.input_ready = input_ready
  outcome = sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert_pending(outcome, target, status="launch_dispatched")
  assert len([call for call in backend.calls if call[0] == "launch"]) == 1


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
def test_lost_launch_result_is_unknown_and_reentry_never_redispatches(sessions, tmp_path, failure):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  def launch(selected, evidence, *, location):
    backend.calls.append(("launch", selected.ref))
    raise failure("synthetic exception details must not escape")
  backend.launch_session = launch
  coordinator = sessions.ResumeCoordinator(backend)
  first = coordinator.resume(target, location="here")
  assert_pending(first, target, status="unknown")
  assert "synthetic exception details" not in str(first)
  assert coordinator.resume(target, location="here") == first
  assert coordinator.snapshot() == first
  assert [call[0] for call in backend.calls] == ["acquire", "verify", "launch", "release"]


@pytest.mark.parametrize("loaded", [False, True])
def test_one_accepted_coordinator_does_not_repeat_completed_dispatch(sessions, tmp_path, loaded):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  backend.loaded = loaded
  coordinator = sessions.ResumeCoordinator(backend)
  first = coordinator.resume(target, location="here")
  assert first.status == ("restored" if loaded else "launch_dispatched")
  assert coordinator.resume(target, location="here") == first
  assert [call[0] for call in backend.calls] == ["acquire", "verify", "launch", "release"]


@pytest.mark.parametrize("exit_code", [2, 4, 5])
def test_explicit_native_failure_preserves_code_without_claiming_load(sessions, tmp_path, exit_code):
  target = known(sessions, tmp_path)
  backend = DispatchOnlyBackend(sessions)
  backend.exit_code = exit_code
  coordinator = sessions.ResumeCoordinator(backend)
  first = coordinator.resume(target, location="here")
  assert_pending(first, target, status="failed")
  assert first.exit_code == exit_code
  assert coordinator.resume(target, location="here") == first
  assert len([call for call in backend.calls if call[0] == "launch"]) == 1


def test_dispatch_is_marked_before_backend_can_lose_reply(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  coordinator = sessions.ResumeCoordinator(backend)
  def launch(selected, evidence, *, location):
    backend.calls.append(("launch", selected.ref))
    assert_pending(coordinator.snapshot(), target, status="unknown")
    assert coordinator.snapshot().reason == "dispatch_in_progress"
    raise ConnectionError("synthetic lost reply")
  backend.launch_session = launch
  assert_pending(coordinator.resume(target, location="here"), target, status="unknown")
  assert len([call for call in backend.calls if call[0] == "launch"]) == 1


def test_coordinator_cannot_be_reused_for_another_target(sessions, tmp_path):
  target = known(sessions, tmp_path)
  other = known(sessions, tmp_path, native_ref="other-session")
  backend = DispatchOnlyBackend(sessions)
  coordinator = sessions.ResumeCoordinator(backend)
  first = coordinator.resume(target, location="here")
  with pytest.raises(sessions.SessionError) as caught:
    coordinator.resume(other, location="here")
  assert caught.value.code in (2, 4)
  assert coordinator.snapshot() == first
  assert [call[0] for call in backend.calls] == ["acquire", "verify", "launch", "release"]


@pytest.mark.parametrize("run_id", [None, "", "not-a-run", "a" * 32])
def test_dispatch_receipt_requires_a_valid_new_run_identity(sessions, tmp_path, run_id):
  target = known(sessions, tmp_path)
  backend = DispatchOnlyBackend(sessions)
  backend.returned_run_id = run_id
  coordinator = sessions.ResumeCoordinator(backend)
  with pytest.raises(sessions.SessionError) as caught:
    coordinator.resume(target, location="here")
  assert caught.value.code == 4
  assert_pending(coordinator.snapshot(), target, status="unknown")
  assert len([call for call in backend.calls if call[0] == "launch"]) == 1


def host_owned_backend(sessions, *, behavior="launch_only"):
  """合成宿主拥有 writer；对象构造及布尔锁不构成真实能力证据。"""
  class SyntheticHost(sessions.HostResumeBackend):
    def __init__(self):
      self.calls = []
      self.writer_live = False
      self.run_id = "c" * 32
      self.on_dispatched = None

    def acquire_writer(self, *args):
      pytest.fail("宿主事务不要求父进程预抢原生 writer")

    def verify_session(self, *args):
      pytest.fail("宿主事务自行核对实际部署、scope 和目标")

    def launch_session(self, *args, **kwargs):
      pytest.fail("宿主事务必须使用 resume_session 接缝")

    def send_input(self, *args, **kwargs):
      pytest.fail("普通恢复交接不能发送继续")

    def kill(self, *args, **kwargs):
      pytest.fail("恢复未知不能强杀宿主")

    def resume_session(self, target, *, location, before_dispatch, after_dispatch):
      self.calls.append("preflight")
      assert location == "here"
      if behavior == "preflight_error":
        raise sessions.SessionError(4, "synthetic-secret-preflight")
      if behavior != "missing_callback":
        self.calls.append("before_dispatch")
        before_dispatch(self.run_id)
        if behavior == "duplicate_callback":
          before_dispatch(self.run_id)
        if self.on_dispatched is not None:
          self.on_dispatched()
      if behavior == "callback_error":
        raise ConnectionError("synthetic-secret-after-dispatch")
      # 模型顺序：派发边界之后由宿主取得原生 writer 并持有。
      self.calls.append("native_writer")
      after_dispatch(self.run_id)
      if behavior == "writer_conflict":
        return sessions.LaunchReceipt(run_id=self.run_id, exit_code=4)
      self.writer_live = True
      self.calls.append("strict_resume")
      if behavior == "mismatched_run":
        return sessions.LaunchReceipt(run_id="d" * 32)
      if behavior == "loaded":
        return sessions.LoadReceipt(run_id=self.run_id, session=target.ref,
          cwd=target.cwd, loaded=True, input_ready=False)
      return sessions.LaunchReceipt(run_id=self.run_id)

    def close_host(self):
      self.calls.append("host_close")
      self.writer_live = False

  return SyntheticHost()


def test_host_owned_writer_can_handoff_without_load_receipt(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = host_owned_backend(sessions)
  try:
    coordinator = sessions.ResumeCoordinator(backend)
    outcome = coordinator.resume(target, location="here")
    assert_pending(outcome, target, status="launch_dispatched")
    assert outcome.run_id == backend.run_id
    assert coordinator.resume(target, location="here") == outcome
    assert backend.calls == ["preflight", "before_dispatch", "native_writer", "strict_resume"]
    assert backend.writer_live is True
  finally:
    backend.close_host()
  assert backend.writer_live is False and backend.calls[-1] == "host_close"


@pytest.mark.parametrize("behavior", ["missing_callback", "duplicate_callback", "mismatched_run"])
def test_host_owned_protocol_violation_rejects_without_redispatch(sessions, tmp_path, behavior):
  target = known(sessions, tmp_path)
  backend = host_owned_backend(sessions, behavior=behavior)
  try:
    coordinator = sessions.ResumeCoordinator(backend)
    with pytest.raises(sessions.SessionError) as first:
      coordinator.resume(target, location="here")
    assert first.value.code == 4
    assert_pending(coordinator.snapshot(), target, status="unknown")
    before = list(backend.calls)
    with pytest.raises(sessions.SessionError) as repeated:
      coordinator.resume(target, location="here")
    assert repeated.value.code == first.value.code
    assert backend.calls == before and backend.calls.count("preflight") == 1
  finally:
    backend.close_host()


def test_host_owned_callback_exception_keeps_run_and_hides_secret(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = host_owned_backend(sessions, behavior="callback_error")
  coordinator = sessions.ResumeCoordinator(backend)
  outcome = coordinator.resume(target, location="here")
  assert_pending(outcome, target, status="unknown")
  assert outcome.run_id == backend.run_id
  assert "synthetic-secret" not in str(outcome)
  assert coordinator.resume(target, location="here") == outcome
  assert backend.calls == ["preflight", "before_dispatch"]


def test_host_owned_preflight_rejection_has_no_dispatch_and_hides_secret(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = host_owned_backend(sessions, behavior="preflight_error")
  coordinator = sessions.ResumeCoordinator(backend)
  with pytest.raises(sessions.SessionError) as caught:
    coordinator.resume(target, location="here")
  assert caught.value.code == 4
  assert "synthetic-secret" not in str(caught.value)
  assert_pending(coordinator.snapshot(), target, status="unknown")
  assert coordinator.snapshot().run_id is None
  assert "synthetic-secret" not in str(coordinator.snapshot())
  assert backend.calls == ["preflight"] and backend.writer_live is False


def test_host_owned_writer_conflict_is_native_failure_without_load(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = host_owned_backend(sessions, behavior="writer_conflict")
  coordinator = sessions.ResumeCoordinator(backend)
  outcome = coordinator.resume(target, location="here")
  assert_pending(outcome, target, status="failed")
  assert outcome.run_id == backend.run_id and outcome.exit_code == 4
  assert coordinator.resume(target, location="here") == outcome
  assert backend.calls == ["preflight", "before_dispatch", "native_writer"]
  assert backend.writer_live is False


def test_host_owned_reentrant_resume_during_dispatch_cannot_launch_twice(sessions, tmp_path):
  target = known(sessions, tmp_path)
  backend = host_owned_backend(sessions)
  coordinator = sessions.ResumeCoordinator(backend)
  nested = []
  backend.on_dispatched = lambda: nested.append(coordinator.resume(target, location="here"))
  try:
    outcome = coordinator.resume(target, location="here")
    assert_pending(outcome, target, status="launch_dispatched")
    assert len(nested) == 1
    assert_pending(nested[0], target, status="unknown")
    assert nested[0].run_id == backend.run_id
    assert backend.calls == ["preflight", "before_dispatch", "native_writer", "strict_resume"]
  finally:
    backend.close_host()


@pytest.mark.parametrize("loaded", [False, True])
def test_accepted_resume_reuses_prior_fact_after_original_cwd_disappears(sessions, tmp_path, loaded):
  target = known(sessions, tmp_path)
  backend = FakeBackend(sessions)
  backend.loaded = loaded
  coordinator = sessions.ResumeCoordinator(backend)
  first = coordinator.resume(target, location="here")
  Path(target.cwd).rmdir()
  assert coordinator.resume(target, location="here") == first
  assert coordinator.snapshot() == first
  assert [call[0] for call in backend.calls] == ["acquire", "verify", "launch", "release"]


def test_native_only_target_dispatches_with_a_real_new_run(sessions, tmp_path):
  from dataclasses import replace
  target = replace(known(sessions, tmp_path, confirmation="historical", cwd_status="historical"), run_id=None)
  backend = host_owned_backend(sessions)
  try:
    coordinator = sessions.ResumeCoordinator(backend)
    outcome = coordinator.resume(target, location="here")
    assert_pending(outcome, target, status="launch_dispatched")
    assert outcome.run_id == "c" * 32 and target.run_id is None
    assert coordinator.resume(target, location="here") is outcome
    assert backend.calls.count("before_dispatch") == 1
  finally:
    backend.close_host()


@pytest.mark.parametrize("new_run", [None, "", True, "invalid"])
def test_native_only_target_does_not_weaken_new_dispatch_identity(sessions, tmp_path, new_run):
  from dataclasses import replace
  target = replace(known(sessions, tmp_path), run_id=None)
  backend = host_owned_backend(sessions)
  backend.run_id = new_run
  coordinator = sessions.ResumeCoordinator(backend)
  with pytest.raises(sessions.SessionError) as caught:
    coordinator.resume(target, location="here")
  assert caught.value.code == 4 and coordinator.snapshot().status == "unknown"
  assert "native_writer" not in backend.calls
