"""P-PANE 有限故障模型；无真实终端、控制端点或原生宿主。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

from agentcfg.run_owners import ReleaseObservation
from agentcfg.storage import Conflict


MANAGER = {"pid": 3133713, "birth_id": "synthetic-manager-birth"}
OLD_RUN = "a" * 32
NEW_RUN = "b" * 32


@pytest.fixture
def pane_module(monkeypatch):
  path = Path(__file__).parent / "fixtures/rotom/resident-pane-probe.py"
  spec = importlib.util.spec_from_file_location("rotom_resident_pane_probe", path)
  module = importlib.util.module_from_spec(spec)
  monkeypatch.setitem(sys.modules, spec.name, module)
  spec.loader.exec_module(module)
  return module


def binding():
  return {"container_id": "synthetic-container", "generation": 1,
    "manager_identity": deepcopy(MANAGER), "manager_code_identity": "c" * 64,
    "control_protocol": "synthetic-pane-v1", "endpoint_identity": {"endpoint_id": "synthetic-endpoint", "generation": 1},
    "terminal_ref": {"server_id": "synthetic-server", "server_generation": 1,
      "pane_id": "synthetic-pane", "cwd": "/workspace/example"}, "old_run": OLD_RUN}


def request(bound=None):
  bound = binding() if bound is None else bound
  return {"request_id": "synthetic-request", "container_id": bound["container_id"],
    "generation": bound["generation"], "op_id": "d" * 32, "new_run": NEW_RUN,
    "deployment_digest": "e" * 64,
    "session_ref": {"agent": "omp", "backend": "managed",
      "native_home_ref": {"kind": "omp-managed-home", "ref": "synthetic-home"}, "native_ref": "synthetic-session"},
    "terminal_ref": deepcopy(bound["terminal_ref"])}


def case(module, *, approved=True, context=None):
  original = binding()
  current = {"binding": deepcopy(original)}
  approved_request = request(original)
  probe = module.ResidentPaneProbe(original, current_binding=lambda: deepcopy(current["binding"]),
    run_context=object() if context is None else context, approved_resume=approved_request if approved else None)
  return probe, current, original, approved_request


def release(run=OLD_RUN):
  return ReleaseObservation(run, deepcopy(MANAGER), True, True)


def leases(module, **changes):
  values = {"run_id": OLD_RUN, "manager_identity": deepcopy(MANAGER), "instance_released": True,
    "native_home_released": True, "runtime_released": True}
  values.update(changes)
  return module.LeaseObservation(**values)


def test_surviving_runtime_lease_prevents_parked(pane_module):
  probe, current, original, approved = case(pane_module)
  result = probe.park(lambda run: release(run), lambda run: leases(pane_module, runtime_released=False), session_sealed=True)
  assert result["phase"] == "unknown"
  assert result["has_run_context"] is True


def parked(module, *, sealed=True):
  probe, current, original, approved = case(module)
  assert probe.park(lambda run: release(run), lambda run: leases(module), session_sealed=sealed)["phase"] == "parked"
  return probe, current, original, approved


def callbacks(events, payloads):
  def persist(value):
    events.append("persist")
    payloads.append(("persist", deepcopy(value)))
  def consume(value):
    events.append("consume")
    payloads.append(("consume", deepcopy(value)))
    return True
  def launch(value):
    events.append("launch")
    payloads.append(("launch", deepcopy(value)))
  return {"persist_intent": persist, "consume_permit": consume, "launch_once": launch}


@pytest.mark.parametrize("damage", ["live-descendant", "incomplete", "wrong-run", "wrong-manager", "bool-int", "error"])
def test_incomplete_exit_cannot_park_or_drop_context(pane_module, damage):
  probe, current, original, approved = case(pane_module)
  proof = release()
  if damage == "live-descendant":
    proof = ReleaseObservation(OLD_RUN, deepcopy(MANAGER), False, True)
  elif damage == "incomplete":
    proof = ReleaseObservation(OLD_RUN, deepcopy(MANAGER), True, False)
  elif damage == "wrong-run":
    proof = release(NEW_RUN)
  elif damage == "wrong-manager":
    proof = ReleaseObservation(OLD_RUN, {**MANAGER, "birth_id": "different-manager"}, True, True)
  elif damage == "bool-int":
    proof = ReleaseObservation(OLD_RUN, deepcopy(MANAGER), True, 1)
  def observe(run):
    assert probe.snapshot()["phase"] == "parking"
    if damage == "error":
      raise OSError("synthetic-exit-observer-error")
    return proof
  result = probe.park(observe, lambda run: pytest.fail("退出覆盖不足不得查称资源已释放"), session_sealed=True)
  assert result["phase"] == "unknown" and result["has_run_context"] is True


@pytest.mark.parametrize("damage", ["instance-live", "home-live", "runtime-int", "wrong-run", "manager-extra", "mapping"])
def test_lease_observation_requires_exact_run_manager_and_three_true_values(pane_module, damage):
  probe, current, original, approved = case(pane_module)
  changes = {"instance-live": {"instance_released": False}, "home-live": {"native_home_released": False},
    "runtime-int": {"runtime_released": 1}, "wrong-run": {"run_id": NEW_RUN},
    "manager-extra": {"manager_identity": {**MANAGER, "untrusted": "extra"}}, "mapping": {}}[damage]
  proof = leases(pane_module, **changes)
  if damage == "mapping":
    proof = deepcopy(proof.__dict__)
  assert probe.park(lambda run: release(run), lambda run: proof, session_sealed=True)["phase"] == "unknown"


@pytest.mark.parametrize("sealed", [1, None])
def test_session_seal_requires_real_boolean_before_parking(pane_module, sealed):
  probe, current, original, approved = case(pane_module)
  with pytest.raises(Conflict):
    probe.park(lambda run: pytest.fail("invalid seal"), lambda run: pytest.fail("invalid seal"), session_sealed=sealed)
  assert probe.snapshot()["phase"] == "running"


def test_unsealed_session_does_not_block_park_but_blocks_resume(pane_module):
  probe, current, original, approved = parked(pane_module, sealed=False)
  events, payloads = [], []
  with pytest.raises(Conflict):
    probe.resume(approved, **callbacks(events, payloads))
  assert probe.snapshot()["phase"] == "parked" and not probe.snapshot()["session_sealed"]
  assert events == payloads == []


def test_parked_drops_last_reference_to_old_context_and_retains_only_identity_audit(pane_module):
  import gc
  import weakref
  class Context:
    pass
  context = Context()
  context.marker = "synthetic-context-sentinel"
  reference = weakref.ref(context)
  probe, current, original, approved = case(pane_module, context=context)
  del context
  assert reference() is not None
  result = probe.park(lambda run: release(run), lambda run: leases(pane_module), session_sealed=True)
  gc.collect()
  assert result["phase"] == "parked" and result["has_run_context"] is False
  assert reference() is None
  assert result["audit"] == ["old-run-released"]
  assert "synthetic-context-sentinel" not in repr(probe.__dict__)


def mutate(current, field):
  value = current["binding"]
  if field == "closed":
    current["binding"] = None
  elif field in ("server_generation", "pane_id", "cwd"):
    value["terminal_ref"][field] = 2 if field == "server_generation" else "synthetic-changed"
  elif field == "manager":
    value["manager_identity"]["birth_id"] = "synthetic-reused-manager"
  elif field == "endpoint":
    value["endpoint_identity"]["endpoint_id"] = "synthetic-replaced-endpoint"
  elif field == "generation":
    value[field] = 2
  elif field == "extra":
    value["untrusted"] = "extra"
  else:
    value[field] = "synthetic-changed"


@pytest.mark.parametrize("field", ["server_generation", "pane_id", "cwd", "manager", "manager_code_identity",
  "control_protocol", "endpoint", "generation", "closed", "extra"])
def test_current_location_or_manager_binding_drift_refuses_resume_without_launch(pane_module, field):
  probe, current, original, approved = parked(pane_module)
  mutate(current, field)
  events, payloads = [], []
  with pytest.raises(Conflict):
    probe.resume(approved, **callbacks(events, payloads))
  assert probe.snapshot()["phase"] == "unknown" and events == payloads == []


@pytest.mark.parametrize("stage", ["exit-observer", "lease-observer"])
def test_park_rechecks_complete_binding_after_each_observer(pane_module, stage):
  probe, current, original, approved = case(pane_module)
  def exit_observer(run):
    if stage == "exit-observer":
      mutate(current, "manager")
    return release(run)
  def lease_observer(run):
    mutate(current, "cwd")
    return leases(pane_module)
  result = probe.park(exit_observer, lease_observer, session_sealed=True)
  assert result["phase"] == "unknown" and result["has_run_context"] is True


@pytest.mark.parametrize("field", ["container_id", "generation", "op_id", "new_run", "deployment_digest", "session_ref", "terminal_ref", "extra"])
def test_request_must_exactly_match_immutable_explicit_approval(pane_module, field):
  probe, current, original, approved = parked(pane_module)
  wrong = deepcopy(approved)
  if field == "generation":
    wrong[field] = 2
  elif field == "session_ref":
    wrong[field]["native_ref"] = "synthetic-other-session"
  elif field == "terminal_ref":
    wrong[field]["pane_id"] = "synthetic-other-pane"
  elif field == "extra":
    wrong["untrusted"] = "extra"
  elif field == "new_run":
    wrong[field] = OLD_RUN
  elif field == "deployment_digest":
    wrong[field] = "f" * 64
  else:
    wrong[field] = "synthetic-mismatch"
  events, payloads = [], []
  with pytest.raises(Conflict):
    probe.resume(wrong, **callbacks(events, payloads))
  assert probe.snapshot()["phase"] == "parked" and events == payloads == []
  assert probe.resume(approved, **callbacks(events, payloads))["phase"] == "resume_pending"
  assert events == ["persist", "consume", "launch"]


def test_binding_and_approval_are_deep_copied_and_new_run_is_required(pane_module):
  probe, current, original, approved = case(pane_module)
  exact = deepcopy(approved)
  original["terminal_ref"]["cwd"] = "synthetic-caller-mutation"
  approved["session_ref"]["native_ref"] = "synthetic-caller-mutation"
  assert probe.park(lambda run: release(run), lambda run: leases(pane_module), session_sealed=True)["phase"] == "parked"
  events, payloads = [], []
  probe.resume(exact, **callbacks(events, payloads))
  assert all(value == exact for stage, value in payloads)
  other, current, original, approved = case(pane_module, approved=False)
  approved["new_run"] = OLD_RUN
  with pytest.raises(Conflict):
    other.prepare_resume(approved)


def test_resume_requires_explicit_prepare_and_loaded_confirmation_not_queue_success(pane_module):
  probe, current, original, approved = case(pane_module, approved=False)
  probe.park(lambda run: release(run), lambda run: leases(pane_module), session_sealed=True)
  events, payloads = [], []
  actions = callbacks(events, payloads)
  with pytest.raises(Conflict):
    probe.resume(approved, **actions)
  probe.prepare_resume(approved)
  assert probe.resume(approved, **actions)["phase"] == "resume_pending"
  assert events == ["persist", "consume", "launch"]
  for duplicate in (approved, {**approved, "request_id": "synthetic-new-id"}):
    with pytest.raises(Conflict):
      probe.resume(duplicate, **actions)
  assert events == ["persist", "consume", "launch"]
  queued = {"kind": "queued", "run_id": NEW_RUN, "session_ref": deepcopy(approved["session_ref"])}
  assert probe.confirm_loaded(lambda: queued)["phase"] == "resume_pending"
  assert probe.snapshot()["current_run"] == OLD_RUN
  loaded = {**queued, "kind": "loaded"}
  assert probe.confirm_loaded(lambda: loaded)["phase"] == "running"
  assert probe.snapshot()["current_run"] == NEW_RUN and not probe.snapshot()["has_run_context"]
  with pytest.raises(Conflict):
    probe.resume(approved, **actions)
  assert events == ["persist", "consume", "launch"]
  assert not hasattr(probe, "send_input")


@pytest.mark.parametrize("stage", ["persist", "consume", "launch"])
@pytest.mark.parametrize("committed", [False, True])
def test_callback_failure_or_response_loss_is_absorbing_unknown_without_replay(pane_module, stage, committed):
  probe, current, original, approved = parked(pane_module)
  events, effected = [], []
  def action(name):
    def call(value):
      assert value == approved
      assert probe.snapshot()["phase"] == "resume_pending"
      events.append(name)
      if name == stage:
        if committed:
          effected.append(name)
        raise OSError("synthetic-callback-result-unknown")
      effected.append(name)
      return True
    return call
  actions = {"persist_intent": action("persist"), "consume_permit": action("consume"), "launch_once": action("launch")}
  with pytest.raises(Conflict):
    probe.resume(approved, **actions)
  expected = ["persist", "consume", "launch"][:["persist", "consume", "launch"].index(stage) + 1]
  assert events == expected and effected == (expected if committed else expected[:-1])
  assert probe.snapshot()["phase"] == "unknown"
  before = (list(events), list(effected))
  for supplied in (approved, {**approved, "request_id": "synthetic-new-id"}):
    with pytest.raises(Conflict):
      probe.resume(supplied, **actions)
  assert probe.confirm_loaded(lambda: pytest.fail("unknown不可重新观察清除"))["phase"] == "unknown"
  assert (events, effected) == before


@pytest.mark.parametrize("stage", ["persist", "consume", "launch"])
def test_binding_is_rechecked_after_every_resume_callback(pane_module, stage):
  probe, current, original, approved = parked(pane_module)
  events, payloads = [], []
  actions = callbacks(events, payloads)
  key = {"persist": "persist_intent", "consume": "consume_permit", "launch": "launch_once"}[stage]
  original_callback = actions[key]
  def drift(value):
    result = original_callback(value)
    mutate(current, "endpoint")
    return result
  actions[key] = drift
  with pytest.raises(Conflict):
    probe.resume(approved, **actions)
  assert events == ["persist", "consume", "launch"][:["persist", "consume", "launch"].index(stage) + 1]
  assert probe.snapshot()["phase"] == "unknown"


@pytest.mark.parametrize("result", [False, None, 1])
def test_permit_consumption_requires_explicit_true_and_never_launches_otherwise(pane_module, result):
  probe, current, original, approved = parked(pane_module)
  events, payloads = [], []
  actions = callbacks(events, payloads)
  def consume(value):
    events.append("consume")
    return result
  actions["consume_permit"] = consume
  with pytest.raises(Conflict):
    probe.resume(approved, **actions)
  assert events == ["persist", "consume"] and probe.snapshot()["phase"] == "unknown"


@pytest.mark.parametrize("damage", ["run", "session", "extra", "error", "binding-drift"])
def test_loaded_observation_must_match_new_run_session_and_current_location(pane_module, damage):
  probe, current, original, approved = parked(pane_module)
  events, payloads = [], []
  probe.resume(approved, **callbacks(events, payloads))
  observation = {"kind": "loaded", "run_id": NEW_RUN, "session_ref": deepcopy(approved["session_ref"])}
  if damage == "run":
    observation["run_id"] = OLD_RUN
  elif damage == "session":
    observation["session_ref"]["native_ref"] = "synthetic-other-session"
  elif damage == "extra":
    observation["untrusted"] = "extra"
  def observe():
    if damage == "error":
      raise OSError("synthetic-loaded-observer-error")
    if damage == "binding-drift":
      mutate(current, "server_generation")
    return observation
  assert probe.confirm_loaded(observe)["phase"] == "unknown"
  assert events == ["persist", "consume", "launch"]


def test_capabilities_are_finite_fake_evidence_without_production_admission():
  import json
  value = json.loads((Path(__file__).parent / "fixtures/rotom/pane-capabilities.json").read_bytes())
  assert value["schema_version"] == 1 and type(value["schema_version"]) is int
  assert value["production_admitted"] is False
  assert value["herdr"]["version"] == "0.9.5" and value["herdr"]["production_admitted"] is False
  assert value["decision"]["original_location"] == "unavailable"
  assert value["prototype"]["capability"] == "finite-state-mechanism-only"
  assert value["prototype"]["resume_order"] == ["persist-intent", "consume-permit", "launch-once"]
  assert value["prototype"]["unknown"] == "absorbing-no-replay"
  assert value["prototype"]["send_input"] == "not-provided"
  assert set(value["agents"]) == {"dsh", "pi", "omp"}
  assert all(item == {"production_admitted": False} for item in value["agents"].values())


def test_probe_has_no_endpoint_terminal_process_or_signal_implementation(pane_module):
  import ast
  tree = ast.parse(Path(pane_module.__file__).read_text())
  imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
  imported.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
  assert imported == {"copy", "dataclasses", "agentcfg.run_owners", "agentcfg.storage"}
  forbidden = {"kill", "killpg", "pidfd_open", "pidfd_send_signal", "Popen", "fork", "spawn", "send_input", "openpty", "socket"}
  assert not any(isinstance(node, ast.Attribute) and node.attr in forbidden for node in ast.walk(tree))
