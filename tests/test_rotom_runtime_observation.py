"""最小 v2 登记接入；仅合成进程、临时存储和假宿主，不据此准入恢复。"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import deployment, lifecycle, run_owners, runtime
from agentcfg.adapter import ContractError, EnvironmentBinding, LaunchSpec, SecretRef
from agentcfg.dependencies import read_lock
from agentcfg.dsh import DshAdapter
from agentcfg.omp import OmpAdapter
from agentcfg.pi import PiAdapter
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from test_runtime import CANARY, local_file


MANAGER = {"pid": 31337, "birth_id": "synthetic-current-manager"}
ADAPTERS = {"dsh": DshAdapter, "pi": PiAdapter, "omp": OmpAdapter}


@pytest.fixture
def sources(tmp_path):
  instance = tmp_path / "instance"
  native = instance / "dsh-home"
  native.mkdir(parents=True, mode=0o700)
  instance.chmod(0o700)
  workspace = SimpleNamespace(instance=instance, state_root=tmp_path / "state", agent="dsh",
    profile="synthetic-profile", binding={"machine": "synthetic", "local": str(tmp_path / "local.toml"),
      "profile": "synthetic-profile"})
  spec = LaunchSpec(("synthetic-agent", "--resume", "must-not-infer-this-id"), tmp_path,
    "b" * 64, (EnvironmentBinding("DSH_HOME", str(native)),
      EnvironmentBinding("SYNTHETIC_SECRET", SecretRef("secret:never-read"))))
  current = {"generation": "a" * 64, "launch": {"lock_identity": "b" * 64,
    "runtime_identity": "c" * 64, "adapter_binding": None}}
  return workspace, current, spec


@pytest.mark.parametrize("agent,variable,relative,kind", [
  ("dsh", "DSH_HOME", "dsh-home", "dsh-home"),
  ("pi", "PI_CODING_AGENT_DIR", "pi-home", "pi-home"),
  ("omp", "HOME", "user-home", "omp-managed-home"),
])
def test_metadata_uses_managed_storage_and_saved_identity(sources, agent, variable, relative, kind):
  workspace, current, spec = sources
  workspace.agent = agent
  native = workspace.instance / relative
  native.mkdir(mode=0o700, exist_ok=True)
  # OMP 的实际进程 HOME 可以是调用者 HOME；不得把它记录成受管存储。
  literal = "/home/example-caller" if agent == "omp" else str(native)
  spec = replace(spec, environment=(EnvironmentBinding(variable, literal),))
  if agent == "omp":
    current["launch"]["adapter_binding"] = {"identity": {"home": str(native)}}
    current["launch"]["runtime_identity"] += "-linux-x64"
  metadata = runtime.run_metadata(workspace, current, spec)
  assert set(metadata) == {"agent", "backend", "profile", "machine_ref", "start_cwd",
    "native_home_ref", "deployed_identity", "coordination_domain"}
  assert metadata["agent"] == agent and metadata["profile"] == workspace.profile
  assert metadata["native_home_ref"] == {"kind": kind, "path": str(native),
    "source": "deployed-contract", "confirmation": "confirmed"}
  assert metadata["machine_ref"] == {key: workspace.binding[key] for key in ("machine", "local")}
  assert metadata["start_cwd"]["path"] == str(spec.cwd)
  assert metadata["start_cwd"]["source"] == "launch-spec"
  assert metadata["start_cwd"]["confirmation"] == "confirmed"
  assert type(metadata["start_cwd"]["observed_at_ns"]) is int
  assert metadata["deployed_identity"]["deployment"] == current["generation"]
  identity = current["launch"]["runtime_identity"]
  expected = hashlib.sha256(identity.encode()).hexdigest() if agent == "omp" else identity
  assert metadata["deployed_identity"]["runtime"] == expected
  assert metadata["coordination_domain"] is None
  assert "must-not-infer-this-id" not in json.dumps(metadata)
  assert "never-read" not in json.dumps(metadata)


@pytest.mark.parametrize("mutation", ["missing", "wrong-home", "secret-home"])
def test_invalid_storage_provenance_refuses_before_registration(sources, mutation):
  workspace, current, spec = sources
  values = {"missing": (),
    "wrong-home": (EnvironmentBinding("DSH_HOME", "/home/example-other"),),
    "secret-home": (EnvironmentBinding("DSH_HOME", SecretRef("secret:forbidden")),)}
  with pytest.raises(Conflict):
    runtime.run_metadata(workspace, current, replace(spec, environment=values[mutation]))
  assert not workspace.state_root.exists()


def test_duplicate_environment_already_fails_the_launch_spec_contract(sources):
  workspace, current, spec = sources
  with pytest.raises(ContractError):
    replace(spec, environment=spec.environment + spec.environment)
  assert not workspace.state_root.exists()


def test_backend_uses_saved_ssh_route_and_not_current_defaults(sources):
  workspace, current, spec = sources
  spec = replace(spec, environment=(*spec.environment, EnvironmentBinding("AGENTCFG_DSH_EXECUTION", "ssh")))
  assert runtime.run_metadata(workspace, current, spec)["backend"] == "ssh"


@pytest.mark.parametrize("form", ["relative", "parent", "symlink-parent"])
def test_start_directory_observation_resolves_real_target_without_changing_launch_cwd(sources, tmp_path, monkeypatch, form):
  workspace, current, spec = sources
  (tmp_path / "target/child").mkdir(parents=True)
  (tmp_path / "link").symlink_to(tmp_path / "target/child", target_is_directory=True)
  monkeypatch.chdir(tmp_path)
  paths = {"relative": Path("target").absolute(), "parent": tmp_path / "target/child/..",
    "symlink-parent": tmp_path / "link/.."}
  spec = replace(spec, cwd=paths[form])
  before = spec.cwd
  assert runtime.run_metadata(workspace, current, spec)["start_cwd"]["path"] == str(tmp_path / "target")
  assert spec.cwd == before


def test_non_linux_registration_is_explicitly_unknown_and_preserves_launch(sources, monkeypatch, capsys):
  workspace, current, spec = sources
  metadata = runtime.run_metadata(workspace, current, spec)
  monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
  def forbidden():
    pytest.fail("unsupported platform must not invent process identity")
  monkeypatch.setattr(run_owners, "current_process_identity", forbidden)
  with lifecycle.registered_run(workspace, metadata=metadata) as run_id:
    assert run_id is None
  assert not workspace.state_root.exists()
  assert "未登记" in capsys.readouterr().err


def test_pi_preserves_existing_non_linux_owner_guard_refusal(sources, monkeypatch):
  workspace, current, spec = sources
  metadata = runtime.run_metadata(workspace, current, spec)
  workspace.agent = "pi"
  metadata["agent"] = "pi"
  metadata["native_home_ref"]["kind"] = "pi-home"
  monkeypatch.setattr(lifecycle.sys, "platform", "darwin")
  with pytest.raises(Conflict):
    with lifecycle.registered_run(workspace, metadata=metadata):
      pytest.fail("Pi must not bypass its pre-existing platform ownership boundary")
  assert not workspace.state_root.exists()


@pytest.fixture
def observation(monkeypatch):
  complete = {"value": False}
  class FakeScope:
    def __init__(self, identity):
      assert identity == MANAGER
    def __enter__(self):
      return self
    def observe(self, run_id):
      return run_owners.ReleaseObservation(run_id, deepcopy(MANAGER), True, True) if complete["value"] else None
    def __exit__(self, *args):
      pass
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  monkeypatch.setattr("agentcfg.descendants.DescendantScope", FakeScope)
  return complete


@pytest.mark.parametrize("agent", ["dsh", "pi"])
@pytest.mark.parametrize("complete", [False, True])
def test_admitted_registration_paths_use_v2_without_guessing_host_or_session(sources, observation, agent, complete):
  workspace, current, spec = sources
  workspace.agent = agent
  relative = {"dsh": "dsh-home", "pi": "pi-home", "omp": "user-home"}[agent]
  native = workspace.instance / relative
  native.mkdir(mode=0o700, exist_ok=True)
  if agent == "omp":
    current["launch"]["adapter_binding"] = {"identity": {"home": str(native)}}
  else:
    name = "DSH_HOME" if agent == "dsh" else "PI_CODING_AGENT_DIR"
    spec = replace(spec, environment=(EnvironmentBinding(name, str(native)),))
  metadata = runtime.run_metadata(workspace, current, spec)
  observation["value"] = complete
  adapter = ADAPTERS[agent](Path(__file__).resolve().parents[1])
  with lifecycle.guard(workspace):
    pass
  with lifecycle.guard(workspace, shared=True, create=False):
    with adapter.run_owner_guard(workspace, metadata=metadata) as run_id:
      record = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()[run_id]
      assert record["schema_version"] == 2 and record["lifecycle_state"] == "active"
      assert record["host_identity"] is record["session_observation"] is record["terminal_ref"] is None
      assert record["protocol"]["control"] is None
  record = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()[run_id]
  assert record["lifecycle_state"] == ("idle_confirmed" if complete else "unknown")


@pytest.mark.parametrize("agent", ["dsh", "pi"])
def test_unknown_blocks_adapter_exclusive_maintenance_without_rewriting(sources, observation, agent):
  workspace, current, spec = sources
  workspace.agent = agent
  adapter = ADAPTERS[agent](Path(__file__).resolve().parents[1])
  physical = lifecycle.guard
  with physical(workspace, create=True):
    pass
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  with physical(workspace, shared=True, create=False):
    run_id = registry.register(deepcopy(MANAGER))
    registry.mark_unknown(run_id, MANAGER)
  path = registry.root / (run_id + ".json")
  before = path.read_bytes()
  with pytest.raises(Conflict):
    with adapter.lifecycle_guard(workspace):
      pytest.fail("unknown ownership must prevent mutation")
  assert path.read_bytes() == before
  # 明确物理 EX + 完整观察仍可对账；普通维护不能伪造这条内部通道。
  registry.reconcile(run_id, maintenance_guard=physical(workspace, create=False),
    observe=lambda record: run_owners.ReleaseObservation(run_id, deepcopy(MANAGER), True, True))
  with adapter.lifecycle_guard(workspace):
    pass


def test_omp_registration_waits_for_shared_runtime_owner_coordination():
  adapter = OmpAdapter(Path(__file__).resolve().parents[1])
  assert not hasattr(adapter, "run_owner_guard")


def test_dsh_sync_refuses_unknown_before_any_runtime_repair(sources, observation, monkeypatch):
  from agentcfg import dependencies
  workspace, current, spec = sources
  with lifecycle.guard(workspace):
    pass
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  with lifecycle.guard(workspace, shared=True, create=False):
    run_id = registry.register(deepcopy(MANAGER))
    registry.mark_unknown(run_id, MANAGER)
  def forbidden(*args, **kwargs):
    pytest.fail("unknown must prevent sync before any repair/cache/native side effect")
  monkeypatch.setattr(dependencies, "_sync", forbidden)
  with pytest.raises(Conflict):
    dependencies._sync_guarded(workspace, None, "dsh")
  assert registry.snapshot()[run_id]["state"] == "unknown"


def test_runtime_registers_after_preflight_and_keeps_native_execution(sources, observation,
    tmp_path, fake_subprocess, prepared_runtime):
  path = tmp_path / "local.toml"
  local_file(path)
  workspace = load_workspace(path)
  lock = read_lock(workspace.repository)
  deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity),
    workspace.binding, runtime.record(workspace, lock))
  prepared_runtime(workspace, lock)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=-15)
  assert runtime.run(workspace, cwd=tmp_path, arguments=("--opaque-native",)) == 143
  record, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
  assert record["schema_version"] == 2 and record["lifecycle_state"] == "unknown"
  assert record["manager_identity"] == MANAGER and record["host_identity"] is None
  assert record["start_cwd"]["path"] == str(tmp_path)
  assert record["session_cwd"] is record["session_observation"] is None
  call = fake_subprocess.calls[-1]
  assert call["argv"][-1] == "--opaque-native" and call["cwd"] == tmp_path
  assert len(call["pass_fds"]) == 2
  encoded = json.dumps(record)
  assert CANARY not in encoded and "--opaque-native" not in encoded and "environment" not in encoded
