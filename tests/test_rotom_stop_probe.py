"""仅注入假通道和假内核；不启动或停止任何宿主进程。"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

from agentcfg.storage import Conflict


RUN = "a" * 32
MANAGER = {"pid": 3133713, "birth_id": "synthetic-manager-birth"}
HOST = {"pid": 3133714, "birth_id": "synthetic-host-birth"}


@pytest.fixture
def probe_module(monkeypatch):
  path = Path(__file__).parent / "fixtures/rotom/stop-channel-probe.py"
  spec = importlib.util.spec_from_file_location("rotom_stop_probe", path)
  module = importlib.util.module_from_spec(spec)
  monkeypatch.setitem(sys.modules, spec.name, module)
  spec.loader.exec_module(module)
  return module


class FakeTransport:
  def __init__(self, handle, identity, events):
    self.handle, self.identity, self.events = handle, deepcopy(identity), events
    self.sent = []
    self.exited = False
    self.failure = None

  def identify(self, handle):
    assert handle is self.handle
    return deepcopy(self.identity)

  def send_graceful(self, handle):
    assert handle is self.handle
    self.events.append("send")
    self.sent.append(handle)
    if self.failure:
      raise self.failure

  def host_exited(self, handle):
    assert handle is self.handle
    return self.exited


def case(module, *, manager=None, host=None, run=RUN, writer=None):
  manager = deepcopy(MANAGER if manager is None else manager)
  host = deepcopy(HOST if host is None else host)
  events, intents = [], []
  handle = object()
  transport = FakeTransport(handle, host, events)
  current = {"manager": deepcopy(manager)}
  def persist(intent):
    events.append("persist")
    intents.append(deepcopy(intent))
    if writer:
      writer(intent, transport, current)
  binding = module.BoundHost(run, manager, host, handle)
  probe = module.StopProbe(binding, transport=transport,
    current_manager=lambda: deepcopy(current["manager"]), persist_intent=persist)
  target = {"run_id": run, "manager_identity": manager, "host_identity": host}
  return probe, transport, current, events, intents, target


def test_manager_change_during_intent_publication_prevents_send(probe_module):
  def change_manager(intent, transport, current):
    current["manager"]["birth_id"] = "synthetic-replacement-manager"
  probe, transport, current, events, intents, target = case(probe_module, writer=change_manager)
  with pytest.raises(Conflict):
    probe.request_stop("request-a", **target)
  assert events == ["persist"] and not transport.sent
  assert probe.snapshot()["phase"] == "unknown"


def test_exactly_two_selected_bound_handles_leave_third_and_manager_unchanged(probe_module):
  cases = [case(probe_module, run=letter * 32,
    host={"pid": HOST["pid"] + index, "birth_id": "synthetic-host-" + letter})
    for index, letter in enumerate(("a", "b", "c"))]
  third_before = cases[2][0].snapshot()
  for index, (probe, transport, current, events, intents, target) in enumerate(cases[:2]):
    result = probe.request_stop("request-" + str(index), **target)
    assert result["phase"] == "signal_sent"
    assert events == ["persist", "send"] and len(transport.sent) == len(intents) == 1
    assert intents[0] == {"schema_version": 1, "kind": "fake-stop-intent",
      "request_id": "request-" + str(index), **target}
    assert transport.sent[0] is transport.handle
  assert cases[2][0].snapshot() == third_before
  assert cases[2][1].sent == cases[2][3] == cases[2][4] == []
  assert all(values[2]["manager"] == MANAGER for values in cases)


@pytest.mark.parametrize("wrong", ["run", "manager", "host", "manager-extra", "host-extra"])
def test_wrong_target_rejected_before_intent_without_poisoning_binding(probe_module, wrong):
  probe, transport, current, events, intents, target = case(probe_module)
  supplied = deepcopy(target)
  if wrong == "run":
    supplied["run_id"] = "b" * 32
  elif wrong.endswith("extra"):
    supplied[wrong.split("-")[0] + "_identity"]["untrusted"] = "extra"
  else:
    supplied[wrong + "_identity"]["birth_id"] = "reused-birth"
  with pytest.raises(Conflict):
    probe.request_stop("request-a", **supplied)
  assert probe.snapshot()["phase"] == "bound"
  assert not events and not intents and not transport.sent
  assert probe.request_stop("request-a", **target)["phase"] == "signal_sent"


@pytest.mark.parametrize("drift", ["host-before", "host-during", "manager-before", "manager-extra"])
def test_reused_or_changed_actual_identity_never_receives_stop(probe_module, drift):
  def mutate(intent, transport, current):
    if drift == "host-during":
      transport.identity["birth_id"] = "synthetic-reused-host"
  probe, transport, current, events, intents, target = case(probe_module, writer=mutate)
  if drift == "host-before":
    transport.identity["birth_id"] = "synthetic-reused-host"
  elif drift == "manager-before":
    current["manager"]["birth_id"] = "synthetic-reused-manager"
  elif drift == "manager-extra":
    current["manager"]["untrusted"] = "extra"
  with pytest.raises(Conflict):
    probe.request_stop("request-a", **target)
  assert probe.snapshot()["phase"] == "unknown" and not transport.sent
  assert events == (["persist"] if drift == "host-during" else [])


def test_transport_missing_and_host_same_pid_as_manager_refuse_without_writer(probe_module):
  calls = []
  binding = probe_module.BoundHost(RUN, MANAGER, HOST, object())
  with pytest.raises(Conflict):
    probe_module.StopProbe(binding, current_manager=lambda: MANAGER, persist_intent=calls.append)
  for host in (MANAGER, {**MANAGER, "birth_id": "different-birth"}):
    handle = object()
    transport = FakeTransport(handle, host, [])
    with pytest.raises(Conflict):
      probe_module.StopProbe(probe_module.BoundHost(RUN, MANAGER, host, handle), transport=transport,
        current_manager=lambda: MANAGER, persist_intent=calls.append)
  assert calls == []


@pytest.mark.parametrize("stage", ["writer-before", "writer-response-lost", "send-response-lost"])
def test_lost_dispatch_responses_are_unknown_without_retries_or_escalation(probe_module, stage):
  probe, transport, current, events, intents, target = case(probe_module)
  durable = []
  if stage != "send-response-lost":
    def persist(intent):
      events.append("persist-attempt")
      if stage == "writer-response-lost":
        durable.append(deepcopy(intent))
      raise OSError("synthetic-writer-result-unknown")
    probe._persist_intent = persist
  else:
    transport.failure = OSError("synthetic-send-response-lost")
  with pytest.raises(Conflict):
    probe.request_stop("request-a", **target)
  assert probe.snapshot()["phase"] == "unknown"
  assert len(transport.sent) == (1 if stage == "send-response-lost" else 0)
  assert len(durable) == (1 if stage == "writer-response-lost" else 0)
  before = (list(events), len(transport.sent), deepcopy(durable))
  for request in ("request-a", "request-other"):
    with pytest.raises(Conflict):
      probe.request_stop(request, **target)
  for _ in range(2):
    assert probe.timeout()["phase"] == "unknown"
    assert probe.observe_release(lambda run: pytest.fail("unknown不得自行恢复观察"))["phase"] == "unknown"
  assert (events, len(transport.sent), durable) == before
  assert current["manager"] == MANAGER


def test_successful_dispatch_is_single_shot_even_if_another_request_id_arrives(probe_module):
  probe, transport, current, events, intents, target = case(probe_module)
  probe.request_stop("request-a", **target)
  for request in ("request-a", "request-other"):
    with pytest.raises(Conflict):
      probe.request_stop(request, **target)
  assert len(transport.sent) == len(intents) == 1


@pytest.mark.parametrize("fault", ["none", "live", "incomplete", "wrong-run", "wrong-manager", "manager-extra", "bool-int", "mapping", "error"])
def test_host_exit_alone_or_invalid_complete_observation_never_releases(probe_module, fault):
  from agentcfg.run_owners import ReleaseObservation
  probe, transport, current, events, intents, target = case(probe_module)
  probe.request_stop("request-a", **target)
  transport.exited = True
  assert probe.observe_host_exit()["phase"] == "host_exited"
  proof = ReleaseObservation(RUN, deepcopy(MANAGER), True, True)
  if fault == "none":
    proof = None
  elif fault == "live":
    proof = ReleaseObservation(RUN, deepcopy(MANAGER), False, True)
  elif fault == "incomplete":
    proof = ReleaseObservation(RUN, deepcopy(MANAGER), True, False)
  elif fault == "wrong-run":
    proof = ReleaseObservation("b" * 32, deepcopy(MANAGER), True, True)
  elif fault == "wrong-manager":
    proof = ReleaseObservation(RUN, {**MANAGER, "birth_id": "replacement"}, True, True)
  elif fault == "manager-extra":
    proof = ReleaseObservation(RUN, {**MANAGER, "untrusted": "extra"}, True, True)
  elif fault == "bool-int":
    proof = ReleaseObservation(RUN, deepcopy(MANAGER), 1, True)
  elif fault == "mapping":
    proof = deepcopy(proof.__dict__)
  def observe(run):
    assert run == RUN
    if fault == "error":
      raise OSError("synthetic-observer-error")
    return proof
  result = probe.observe_release(observe)
  assert result["phase"] == "unknown" and result["host_exited"] is True
  assert len(transport.sent) == 1 and current["manager"] == MANAGER


def test_complete_same_run_manager_observation_is_separate_from_host_exit(probe_module):
  from agentcfg.run_owners import ReleaseObservation
  probe, transport, current, events, intents, target = case(probe_module)
  assert probe.request_stop("request-a", **target)["phase"] == "signal_sent"
  assert probe.observe_host_exit()["phase"] == "signal_sent"
  transport.exited = True
  assert probe.observe_host_exit()["phase"] == "host_exited"
  assert probe.observe_release(lambda run: ReleaseObservation(run, deepcopy(MANAGER), True, True))["phase"] == "released"
  assert probe.timeout()["phase"] == "released"
  assert len(transport.sent) == 1


@pytest.mark.parametrize("lost", ["before-observer", "during-observer"])
def test_manager_loss_prevents_release_and_never_targets_manager(probe_module, lost):
  from agentcfg.run_owners import ReleaseObservation
  probe, transport, current, events, intents, target = case(probe_module)
  probe.request_stop("request-a", **target)
  observed = []
  def observe(run):
    observed.append(run)
    current["manager"] = None
    return ReleaseObservation(run, deepcopy(MANAGER), True, True)
  if lost == "before-observer":
    current["manager"] = None
  assert probe.observe_release(observe)["phase"] == "unknown"
  assert observed == ([] if lost == "before-observer" else [RUN])
  assert probe.timeout()["phase"] == "unknown" and len(transport.sent) == 1


def test_timeout_never_resends_escalates_or_stops_manager(probe_module):
  probe, transport, current, events, intents, target = case(probe_module)
  probe.request_stop("request-a", **target)
  before = (list(events), list(transport.sent), deepcopy(current))
  for _ in range(3):
    assert probe.timeout()["phase"] == "signal_sent"
  assert (events, transport.sent, current) == before
  current["manager"] = None
  assert probe.timeout()["phase"] == "unknown"
  assert events == before[0] and transport.sent == before[1]


# 复用既有假内核 fixture，实际 DescendantScope 仍消费其公开观察契约。
from test_descendant_release import kernel


@pytest.mark.parametrize("condition", ["complete", "surviving-descendant", "observer-error"])
def test_real_descendant_scope_contract_with_fake_kernel(probe_module, kernel, condition):
  descendants, manager, state = kernel
  host = {"pid": manager["pid"] + 100000, "birth_id": "synthetic-descendant-host"}
  probe, transport, current, events, intents, target = case(probe_module, manager=manager, host=host)
  with descendants.DescendantScope(manager) as scope:
    probe.request_stop("request-a", **target)
    transport.exited = True
    assert probe.observe_host_exit()["phase"] == "host_exited"
    if condition == "surviving-descendant":
      state["wait"] = [(host["pid"], 0), (0, 0)]
    elif condition == "observer-error":
      state["wait"] = [OSError("synthetic-kernel-observer-error")]
    else:
      state["wait"] = [(host["pid"], 0), (host["pid"] + 1, 0)]
    assert probe.observe_release(scope.observe)["phase"] == ("released" if condition == "complete" else "unknown")
  assert len(transport.sent) == 1 and current["manager"] == manager


def test_capability_fixture_admits_only_verified_dsh_combination():
  import json
  path = Path(__file__).parent / "fixtures/rotom/exit-capabilities.json"
  value = json.loads(path.read_bytes())
  assert set(value) == {"schema_version", "capability", "platforms", "agents", "feature_merged_into_main", "admitted_combinations"}
  assert type(value["schema_version"]) is int and value["schema_version"] == 1
  assert value["capability"] == "exact-combination-native-acceptance"
  assert value["feature_merged_into_main"] is False
  assert set(value["platforms"]) == {"linux", "other"}
  linux = value["platforms"]["linux"]
  assert set(linux) == {"stable_handle_apis", "production_admitted"}
  assert linux["production_admitted"] is False
  assert linux["stable_handle_apis"] == [
    {"name": "os.pidfd_open", "python_min": "3.9", "linux_min": "5.3",
      "source": "https://docs.python.org/3.11/library/os.html#os.pidfd_open"},
    {"name": "signal.pidfd_send_signal", "python_min": "3.9", "linux_min": "5.1",
      "source": "https://docs.python.org/3.11/library/signal.html#signal.pidfd_send_signal"}]
  assert value["platforms"]["other"] == {"capability": "unknown", "production_admitted": False}
  assert set(value["agents"]) == {"dsh", "pi", "omp"}
  assert value["agents"]["dsh"] == {"production_admitted": False,
    "admission": "listed-combinations-only",
    "pending": ["full-maintenance-setup-restore", "other-runtime-platform-combinations"]}
  assert len(value["admitted_combinations"]) == 1
  admitted = value["admitted_combinations"][0]
  assert (admitted["agent"], admitted["platform"], admitted["backend"], admitted["operation"]) == ("dsh", "linux", "managed", "stop_only")
  assert admitted["runtime_identity"] == "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d"
  assert admitted["registration"] == 2 and admitted["control"] == "linux-pidfd-stop-v1"
  assert admitted["new_launch_binding_required"] is True
  assert all(admitted[key] is False for key in ("setup_admitted", "force_admitted", "automatic_continue_admitted"))
  for name in ("pi", "omp"):
    capability = value["agents"][name]
    assert set(capability) == {"production_admitted", "pending"}
    assert capability["production_admitted"] is False
    assert capability["pending"] == ["native-stop-semantics", "launch-time-host-binding", "real-host-validation"]


def test_probe_has_no_native_transport_or_process_api_imports(probe_module):
  import ast
  tree = ast.parse(Path(probe_module.__file__).read_text())
  imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
  imported.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
  assert imported == {"copy", "dataclasses", "agentcfg.run_owners", "agentcfg.storage"}
  assert not any(isinstance(node, ast.Attribute) and node.attr in
    {"kill", "killpg", "pidfd_open", "pidfd_send_signal", "Popen", "fork", "spawn"}
    for node in ast.walk(tree))


def test_last_handle_identity_probe_cannot_hide_manager_loss_before_send(probe_module):
  probe, transport, current, events, intents, target = case(probe_module)
  original = transport.identify
  checked = []
  def identify(handle):
    result = original(handle)
    checked.append(handle)
    if len(checked) == 2:
      current["manager"] = None
    return result
  transport.identify = identify
  with pytest.raises(Conflict):
    probe.request_stop("request-a", **target)
  assert events == ["persist"] and not transport.sent
  assert probe.snapshot()["phase"] == "unknown"
