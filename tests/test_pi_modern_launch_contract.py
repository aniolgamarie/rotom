"""现代启动组合默认证据；合成backend不构成正式Full来源或宿主验收。"""

from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import deployment, runtime
from agentcfg.pi import PiAdapter
from agentcfg.pi_dependencies import PiBackend
from agentcfg.process import DependencyError
from agentcfg.render import RenderCandidate
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from agentcfg.workspace import load_workspace
from test_pi_adapter import ROOT, pi_data
from test_pi_profile_projection import resolved


_CALLBACKS = []


@pytest.fixture(autouse=True)
def callback_sentinel():
  _CALLBACKS.clear()
  yield
  assert _CALLBACKS == []


class ForeignString(str):
  def __eq__(self, other): _CALLBACKS.append("eq"); raise AssertionError()
  def __hash__(self): _CALLBACKS.append("hash"); raise AssertionError()
  def __iter__(self): _CALLBACKS.append("iter"); raise AssertionError()
  def __contains__(self, other): _CALLBACKS.append("contains"); raise AssertionError()
  def startswith(self, other): _CALLBACKS.append("startswith"); raise AssertionError()


class ForeignList(list):
  def __iter__(self): _CALLBACKS.append("iter"); raise AssertionError()
  def __len__(self): _CALLBACKS.append("len"); raise AssertionError()


class ForeignTuple(tuple):
  def __iter__(self): _CALLBACKS.append("iter"); raise AssertionError()
  def __len__(self): _CALLBACKS.append("len"); raise AssertionError()


def modern_data(profile="pi-base"):
  data = resolved()
  if profile == "pi-full":
    # 此配置只是公开Full投影的合成选择，不提供Full材料或来源资格。
    data["profile"]["id"] = profile
    data["profile"]["plugins"] = []
    data["plugins"] = {}
    data["adapter_documents"]["agent"]["profile_defaults"][profile] = deepcopy(data["adapter_documents"]["agent"]["profile_defaults"]["pi-base"])
    data["adapter_documents"]["plugins"]["profile_plugins"][profile] = {}
  return data


def fixed_error(function, *args, code="pi-arguments"):
  try: raise RuntimeError("SYNTHETIC_PRIVATE_ARGV")
  except RuntimeError:
    with pytest.raises(ConfigError) as caught: function(*args)
  assert type(caught.value) is ConfigError and caught.value.args == ConfigError(code).args
  assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_original_modern_spec_fixed_node_cli_and_instance_environment(tmp_path, profile):
  data = modern_data(profile); adapter = PiAdapter(ROOT)
  before = deepcopy(data)
  spec = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "package", instance_root=tmp_path / "instance", lock_identity="a"*64)
  assert spec.argv == ("node", "--experimental-import-meta-resolve", str(tmp_path / "package/runtime/official-launch.mjs"), "--manifest", str(tmp_path / "instance/pi-home/agentcfg-manifest.json"))
  env = {item.name: item.value for item in spec.environment}
  assert env["HOME"] == str(tmp_path / "instance/user-home")
  assert env["PI_CODING_AGENT_DIR"] == str(tmp_path / "instance/pi-home")
  assert env["PI_CODING_AGENT_SESSION_DIR"] == str(tmp_path / "instance/pi-home/sessions")
  assert "CODEX_HOME" not in env and "BUN_OPTIONS" not in env
  assert data == before
  # 所选SDK入口由installed资料持有；本spec不把SDK入口重写成自有CLI。
  assert "official-launch.mjs" not in data["profile"]["agent_options"].get("entrypoint", "")


@pytest.mark.parametrize("engine", ["bun", "python", True])
def test_modern_engine_cannot_fall_back(tmp_path, engine):
  data = modern_data(); data["profile"]["agent_options"]["runtime"]["engine"] = engine
  with pytest.raises(ConfigError): PiAdapter(ROOT).launch_spec(data, cwd=tmp_path, runtime_root=tmp_path, instance_root=tmp_path, lock_identity="a"*64)


def test_unknown_selected_profile_is_rejected_by_original_resolver(tmp_path):
  local = tmp_path / "local.toml"; local.write_text('schema_version=1\n[machine]\nid="modern-contract"\n')
  with pytest.raises(ConfigError): load_workspace(local, profile="pi-nonexistent", repository=ROOT)


@pytest.mark.parametrize("args", [(), [], ["message"], ["--print", "message"], ["--mode", "rpc"], ["--help"], ["-h"], ["--", "--manifest", "anything"], ["--thinking", "off"], ["--thinking", "minimal"], ["--thinking", "low"], ["--thinking", "medium"], ["--thinking", "high"], ["--thinking", "xhigh"], ["--thinking", "max"], ["--mode", "rpc", "--thinking", "max", "--help"], ["--print", "--", "--mode", "rpc"], ["", "正文"]])
def test_modern_arguments_match_public_parser_positive(args):
  result = PiAdapter(ROOT).validate_arguments_for(modern_data(), args)
  assert type(result) is tuple and all(type(item) is str for item in result)
  assert result == tuple(args)


@pytest.mark.parametrize("args", [["-p"], ["--manifest", "private"], ["--model=x"], ["--tools", "all"], ["--mode"], ["--mode", "tui"], ["--print", "--print"], ["--mode", "rpc", "--print"], ["--print", "--mode", "rpc"], ["--mode", "rpc", "message"], ["message", "--mode", "rpc"], ["--mode", "rpc", "--", "message"], ["--thinking"], ["--thinking", "bad"], ["--thinking", "low", "--thinking", "high"], ["\0"], ["\ud800"], ["--", "\0"], ["--", "\udfff"], ForeignList(["hello"]), ForeignTuple(("hello",)), [ForeignString("hello")], (ForeignString("--print"),), "hello", iter(())])
def test_modern_arguments_fixed_private_error_and_zero_foreign(args):
  fixed_error(PiAdapter(ROOT).validate_arguments_for, modern_data(), args)


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit(19)])
def test_argument_control_exception_preserves_object(monkeypatch, error):
  import agentcfg.pi as pi
  def throwing(value): raise error
  monkeypatch.setattr(pi, "ord", throwing, raising=False)
  with pytest.raises(type(error)) as caught: PiAdapter(ROOT).validate_arguments_for(modern_data(), ["message"])
  assert caught.value is error


def test_internal_argument_error_is_fixed_and_ambient_chain_cleared(monkeypatch):
  import agentcfg.pi as pi
  def throwing(value): raise RuntimeError("SYNTHETIC_PRIVATE_ARGV")
  monkeypatch.setattr(pi, "ord", throwing, raising=False)
  fixed_error(PiAdapter(ROOT).validate_arguments_for, modern_data(), ["message"])


def test_legacy_profile_uses_original_validator_and_returns_none(tmp_path):
  data = pi_data(tmp_path); adapter = PiAdapter(ROOT)
  assert adapter.validate_arguments_for(data, ["-p", "message"]) is None
  with pytest.raises(ConfigError): adapter.validate_arguments_for(data, ["--mode", "rpc"])
  node = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "package", instance_root=tmp_path / "instance", lock_identity="a"*64)
  assert node.argv == ("node", str(tmp_path / "package/runtime/launch.mjs"), "--manifest", str(tmp_path / "instance/pi-home/agentcfg-manifest.json"))


class SyntheticBackend:
  """只供record/run组合的自有合成material，不冒充PiBackend或sealed SDK。"""
  def __init__(self, root, identity):
    self.directory = root; self.identity = identity
    self.raw = b"synthetic backend material; never executable\n"
    root.mkdir(mode=0o700); (root / "material").write_bytes(self.raw)
    (root / "material").chmod(0o600)
  def runtime_identity(self, workspace, lock): return self.identity
  def root(self, workspace, identity):
    assert identity == self.identity
    return self.directory
  def status(self, workspace, identity):
    root = self.root(workspace, identity)
    if not root.exists(): return "missing"
    if not (root / "material").is_file() or (root / "material").read_bytes() != self.raw: return "damaged"
    return "installed"
  def executable_paths(self, root): return ()


def deployed(tmp_path, monkeypatch, *, separate=True):
  data = modern_data(); lock = SimpleNamespace(identity="a"*64, metadata={"toolchains": {"node": "v24.14.0"}})
  adapter = PiAdapter(ROOT)
  backend = SyntheticBackend(tmp_path / "material-package", "b"*64 if separate else lock.identity)
  instance = tmp_path / "instance"; state_root = tmp_path / "state"
  local = tmp_path / "local.toml"; local.write_text('schema_version=1\n')
  workspace = SimpleNamespace(repository=ROOT, local_path=local, instance=instance, state_root=state_root,
    resolved=SimpleNamespace(data=data), adapter=adapter, backend=backend, agent="pi", profile="pi-base",
    binding={"machine": data["machine"]["id"], "local": str(local), "profile": "pi-base"},
    secret_store=SimpleNamespace(resolve=lambda reference, required=False: None))
  # 合成backend没有manager角色；只替lease provider，不替validate/spec/record/deployment。
  monkeypatch.setattr(adapter, "lifecycle_guard", lambda workspace: nullcontext())
  contract = runtime.record(workspace, lock)
  artifacts = adapter.render(data)
  candidate = RenderCandidate(hashlib.sha256(deployment.json_bytes(contract)).hexdigest(), artifacts)
  deployment.apply(instance, state_root, candidate, workspace.binding, contract)
  with Tree(state_root) as tree: current = deployment.read_state(tree)["current"]
  assert current["launch"] == contract
  return workspace, lock, contract


@pytest.mark.parametrize("separate", [False, True])
def test_original_record_apply_readback_two_identity_encodings(tmp_path, monkeypatch, separate):
  workspace, lock, contract = deployed(tmp_path, monkeypatch, separate=separate)
  assert ("runtime_identity" in contract) is separate
  assert contract.get("runtime_identity", contract["lock_identity"]) == workspace.backend.identity
  assert contract["lock_identity"] == lock.identity
  assert contract["argv"][1] == "--experimental-import-meta-resolve"
  assert contract["argv"][2].endswith("runtime/official-launch.mjs")
  assert runtime.decode(contract, tmp_path, ("--print", "hello")).argv == tuple(contract["argv"]) + ("--print", "hello")


@pytest.mark.parametrize("mutation", ["foreign", "flag"])
def test_original_run_uses_captured_tuple_after_late_caller_mutation(tmp_path, monkeypatch, fake_subprocess, mutation):
  workspace, lock, contract = deployed(tmp_path, monkeypatch)
  args = ["--print", "hello"]; events = []
  def lifecycle(workspace):
    args[:] = [ForeignString("foreign")] if mutation == "foreign" else ["--manifest", "unvalidated"]
    return nullcontext()
  monkeypatch.setattr(workspace.adapter, "lifecycle_guard", lifecycle)
  monkeypatch.setattr(workspace.adapter, "operation_cwd", lambda workspace, cwd, values: events.append(values) or cwd, raising=False)
  fake_subprocess.queue(returncode=0, stdout="v24.14.0")
  def executor(workspace, spec, env, lease, saved, **kwargs):
    assert spec.argv == tuple(contract["argv"]) + ("--print", "hello")
    assert env["HOME"] == str(workspace.instance / "user-home")
    events.append(spec.argv[-2:]); return 23
  assert runtime.run(workspace, cwd=tmp_path, arguments=args, launch_operation=executor) == 23
  assert events == [("--print", "hello"), ("--print", "hello")]
  assert len(fake_subprocess.calls) == 1


def test_modern_argument_failure_precedes_lease_secret_and_child(monkeypatch, fake_subprocess):
  calls = []
  class Adapter(PiAdapter):
    def lifecycle_guard(self, workspace): calls.append("lease"); raise AssertionError()
  workspace = SimpleNamespace(adapter=Adapter(ROOT), resolved=SimpleNamespace(data=modern_data()))
  fixed_error(lambda args: runtime.run(workspace, cwd=Path("/"), arguments=args), ["--mode", "rpc", "message"])
  assert calls == [] and fake_subprocess.calls == []


@pytest.mark.parametrize("result", [[], "hello", 1, True, ForeignTuple(("hello",)), (ForeignString("hello"),), (1,)])
def test_invalid_hook_return_domain_precedes_all_activity(result, fake_subprocess):
  calls = []
  adapter = SimpleNamespace(validate_arguments_for=lambda data, args: result,
    lifecycle_guard=lambda workspace: calls.append("lease"))
  workspace = SimpleNamespace(adapter=adapter, resolved=SimpleNamespace(data={}))
  fixed_error(lambda: runtime.run(workspace, cwd=Path("/")), code="runtime-arguments")
  assert calls == [] and fake_subprocess.calls == []


@pytest.mark.parametrize("hook", [False, True])
def test_none_hook_and_other_adapter_fallback_keep_original_arguments(hook):
  args = ["old"]; seen = []; sentinel = RuntimeError("stop after original parameter seam")
  def validate(values): seen.append(values)
  def validate_for(data, values): seen.append(values); return None
  def stop(workspace, cwd, values): seen.append(values); raise sentinel
  adapter = SimpleNamespace(validate_arguments=validate, operation_cwd=stop)
  if hook: adapter.validate_arguments_for = validate_for
  workspace = SimpleNamespace(adapter=adapter, resolved=SimpleNamespace(data={}))
  with pytest.raises(RuntimeError) as caught: runtime.run(workspace, cwd=Path("/"), arguments=args)
  assert caught.value is sentinel and seen == [args, args] and all(value is args for value in seen)


@pytest.mark.parametrize("fault", ["missing", "damaged", "binding", "resource"])
def test_original_run_keeps_existing_admission_failures(tmp_path, monkeypatch, fake_subprocess, fault):
  workspace, lock, contract = deployed(tmp_path, monkeypatch)
  if fault == "missing": (workspace.backend.directory / "material").unlink(); workspace.backend.directory.rmdir()
  elif fault == "damaged": (workspace.backend.directory / "material").write_bytes(b"drift")
  elif fault == "binding": workspace.binding = {**workspace.binding, "profile": "different"}
  else: (workspace.instance / "pi-home/AGENTS.md").write_bytes(b"drift")
  with pytest.raises((DependencyError, Conflict)): runtime.run(workspace, cwd=tmp_path, launch_operation=lambda *args, **kwargs: pytest.fail("child activity"))
  assert fake_subprocess.calls == []


def test_original_modern_candidate_install_gate_is_unchanged(tmp_path, monkeypatch, fake_subprocess):
  from test_pi_owner_origin import _prepare
  workspace, lock, *_ = _prepare(tmp_path, monkeypatch, current=False)
  with pytest.raises(DependencyError, match="候选"): PiBackend(profile="pi-full").sync(workspace, lock)
  assert not (workspace.instance / "runtimes").exists() and fake_subprocess.calls == []


def test_legacy_validator_opaque_return_is_ignored(monkeypatch, tmp_path):
  adapter = PiAdapter(ROOT); opaque = ForeignList([ForeignString("unused")]); seen = []
  def original(values): seen.append(values); return opaque
  monkeypatch.setattr(adapter, "validate_arguments", original)
  args = ["legacy"]
  assert adapter.validate_arguments_for(pi_data(tmp_path), args) is None
  assert seen == [args] and seen[0] is args


def test_original_record_keeps_synthetic_sdk_entrypoint_separate_from_cli(tmp_path, monkeypatch):
  workspace, lock, _ = deployed(tmp_path, monkeypatch)
  # 公开SDK入口字段属于安装资料；这里只构造不执行的合成backend文件。
  sdk_entry = "node_modules/synthetic-sdk/public.js"
  root = workspace.backend.directory
  (root / "runtime").mkdir(mode=0o700)
  (root / "node_modules/synthetic-sdk").mkdir(parents=True, mode=0o700)
  (root / sdk_entry).write_bytes(b"// inert public SDK placeholder; never imported\n")
  installed = deployment.json_bytes({"schema_version": 2, "entrypoint": sdk_entry})
  (root / "runtime/profile.json").write_bytes(installed)
  lock.metadata["profile_slices"] = {"pi-base": {"entrypoint": sdk_entry}}
  before = deepcopy(lock.metadata)
  contract = runtime.record(workspace, lock)
  assert contract["argv"][2] == str(root / "runtime/official-launch.mjs")
  assert contract["argv"][2] != str(root / sdk_entry)
  assert (root / "runtime/profile.json").read_bytes() == installed and lock.metadata == before
