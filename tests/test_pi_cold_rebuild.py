"""冷重建调用完整同步，禁止复制旧运行包；所有安装器与宿主为替身。"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from agentcfg.pi_cold_rebuild import cold_rebuild
from agentcfg.pi_dependencies import recipe_digest
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_dependencies import fixture_repository, digest, payload


def configure(checkout, base, home, profile, run):
  from agentcfg.storage import Tree
  path = base / "local.toml"
  with Tree(base) as tree: tree.write_new(path.name, b'schema_version = 1\n[machine]\nid = "synthetic"\n')
  return path


def source(tmp_path):
  repository, manifest = fixture_repository(tmp_path)
  original = Path(__file__).resolve().parents[1]
  for name in ("agentcfg", "pyproject.toml", "uv.lock"):
    (repository / name).write_bytes((original / name).read_bytes())
  (repository / "agentcfg").chmod(0o700)
  # 真实的安装目录和旧用户资源不属于源文件 allowlist。
  (repository / "node_modules").mkdir(); (repository / "node_modules/old").write_text("must not copy")
  (repository / ".pi").mkdir(); (repository / ".pi/auth.json").write_text("synthetic unselected")
  manifest["recipe_digest"] = recipe_digest(repository); manifest.pop("identity"); manifest["identity"] = digest(manifest)
  (repository / "locks/pi/manifest.json").write_bytes(payload(manifest))
  return repository, manifest


def test_two_rebuilds_have_fresh_homes_caches_and_checkouts(tmp_path, monkeypatch):
  repository, manifest = source(tmp_path); calls = []
  monkeypatch.setenv("https_proxy", "http://127.0.0.1:8123")
  def run(argv, **kwargs):
    calls.append((argv, kwargs))
    assert kwargs["env"]["https_proxy"] == "http://127.0.0.1:8123"
    assert not (kwargs["cwd"] / "node_modules/old").exists()
    assert not (kwargs["cwd"] / ".pi/auth.json").exists()
    assert (kwargs["cwd"] / "locks/pi/manifest.json").is_file()
    return SimpleNamespace(returncode=0, stdout=b"fixture", stderr=b"")
  def inspect(checkout, local, profile, lock):
    assert lock == manifest["identity"] and local.stat().st_mode & 0o777 == 0o600
    assert "synthetic unselected" not in local.read_text()
    return {"installation": "verified", "runtime_identity": "fixture", "native_execution": "not-run"}
  def native(checkout, base, profile, installed, env, run):
    assert "https_proxy" not in env
    return {"native_execution": "not-run"}
  result = cold_rebuild(repository, "pi-fixture", tmp_path / "rebuilt", allow_host=True, run=run, inspect=inspect, uv="/fixture/uv", configure=configure,
    native=native, isolate=lambda base, profile, uv, run: run)
  assert len(calls) == 6 and len({call[1]["env"]["HOME"] for call in calls}) == 2
  assert len({call[1]["env"]["NPM_CONFIG_CACHE"] for call in calls}) == 2
  assert [call[0][-1] for call in calls if call[0][-1] in ("sync", "apply")] == ["sync", "apply", "sync", "apply"]
  assert len({row["source_digest"] for row in result["targets"]}) == 1
  assert result["status"] == "not-run"  # 安装成功不冒充原生场景通过。


def test_cold_rebuild_requires_authorization_and_empty_new_target(tmp_path):
  repository, _ = source(tmp_path)
  with pytest.raises(ConfigError, match="authorization"): cold_rebuild(repository, "pi-fixture", tmp_path / "new")
  existing = tmp_path / "existing"; existing.mkdir()
  with pytest.raises(Conflict): cold_rebuild(repository, "pi-fixture", existing, allow_host=True, uv="/fixture/uv")


def test_failed_first_install_does_not_skip_the_other_target_or_claim_success(tmp_path):
  repository, _ = source(tmp_path); calls = []
  def run(argv, **kwargs):
    calls.append(argv); return SimpleNamespace(returncode=5, stdout=b"", stderr=b"fixture failure")
  result = cold_rebuild(repository, "pi-fixture", tmp_path / "rebuilt", allow_host=True, run=run, uv="/fixture/uv", configure=configure, isolate=lambda base, profile, uv, run: run)
  assert len(calls) == 2 and result["status"] == "failed"
  assert all(row["installation"] == "failed" for row in result["targets"])


def test_source_identity_survives_private_permissions_in_the_new_checkout(tmp_path):
  from agentcfg.pi_cold_rebuild import copy_source
  repository, _ = source(tmp_path)
  (repository / "agentcfg").chmod(0o755)
  first = copy_source(repository, tmp_path / "first-copy")
  second = copy_source(tmp_path / "first-copy", tmp_path / "second-copy")
  assert first == second
  assert (tmp_path / "second-copy/agentcfg").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("stage", ["configure", "inspect", "native"])
def test_target_stage_errors_are_sanitized_and_do_not_hide_the_second_target(tmp_path, stage):
  from agentcfg.process import DependencyError
  repository, _ = source(tmp_path)
  def fail(*_args): raise DependencyError("synthetic private value must not enter report")
  result = cold_rebuild(repository, "pi-fixture", tmp_path / "rebuilt", allow_host=True,
    run=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=b"", stderr=b""), uv="/fixture/uv",
    configure=fail if stage == "configure" else configure,
    inspect=fail if stage == "inspect" else lambda *_: {"installation": "verified"},
    native=fail if stage == "native" else lambda *_: {"native_execution": "passed"},
    isolate=lambda base, profile, uv, run: run)
  assert result["status"] == "failed"
  assert [row["target"] for row in result["targets"]] == ["first", "第二组 空格路径"]
  assert all(row["native_execution" if stage == "native" else "installation"] == "failed" for row in result["targets"])
  assert "synthetic private value" not in json.dumps(result)


@pytest.mark.parametrize("fault", [None, "runtime", "source", "missing-case", "termination", "not-run"])
def test_rebuilt_target_runs_its_own_python_and_rejects_unmatched_or_partial_native_reports(tmp_path, monkeypatch, fault):
  from agentcfg import pi_cold_rebuild as cold
  from agentcfg.deployment import json_bytes
  from agentcfg.storage import Tree
  checkout = tmp_path / "new-checkout"; checkout.mkdir()
  base = tmp_path / "target"; base.mkdir(mode=0o700)
  installed = {"runtime_root": str(base / "runtime"), "runtime_identity": "a" * 64, "lock_identity": "b" * 64, "source_digest": "c" * 64}
  monkeypatch.setattr(cold, "native_cases", lambda _: ("host-resources",))
  def run(argv, **kwargs):
    assert argv[0] == str(checkout / ".venv/bin/python") and argv[2] == str(checkout / "scripts/verify-pi.py")
    assert kwargs["env"]["HOME"] == str(base / "home")
    output = Path(argv[argv.index("--output") + 1])
    value = {"schema_version": 1, "tier": "native", "case": "host-resources", "status": "not-run" if fault == "not-run" else "passed",
      "source_digest": "wrong" if fault == "source" else installed["source_digest"],
      "runtime": {"profile": "pi-managed", "runtime_identity": "wrong" if fault == "runtime" else installed["runtime_identity"], "lock_identity": installed["lock_identity"]},
      "results": [] if fault == "missing-case" else [{"scenario_id": "host-resources", "status": "passed", "execution": {"exit_code": 0, "termination_confirmed": fault != "termination"}}]}
    with Tree(output.parent) as tree: tree.write_new(output.name, json_bytes(value))
    return SimpleNamespace(returncode=1 if fault == "not-run" else 0, stdout=b"", stderr=b"")
  result = cold.verify_native_target(checkout, base, "pi-managed", installed, {"HOME": str(base / "home")}, run)
  assert result["native_execution"] == ("passed" if fault is None else "not-run" if fault == "not-run" else "failed")


def test_both_targets_use_one_frozen_source_even_when_the_working_checkout_changes(tmp_path):
  repository, _ = source(tmp_path)
  initial = (repository / "agentcfg").read_bytes()
  calls = []
  def run(argv, **kwargs):
    calls.append(argv)
    assert (kwargs["cwd"] / "agentcfg").read_bytes() == initial
    (repository / "agentcfg").write_text("new work while validation is running")
    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
  result = cold_rebuild(repository, "pi-fixture", tmp_path / "rebuilt", allow_host=True, run=run,
    inspect=lambda *_: {"installation": "verified"}, uv="/fixture/uv", configure=configure,
    native=lambda *_: {"native_execution": "passed"}, isolate=lambda base, profile, uv, run: run)
  assert result["status"] == "passed" and len(calls) == 6
  assert result["targets"][0]["source_digest"] == result["targets"][1]["source_digest"]
  assert (tmp_path / "rebuilt/candidate-source/agentcfg").read_bytes() == initial


def test_default_driver_reimports_code_and_schemas_from_the_frozen_source(tmp_path, monkeypatch):
  import agentcfg.pi_cold_rebuild as cold
  from agentcfg.deployment import json_bytes
  from agentcfg.storage import Tree
  repository, manifest = source(tmp_path)
  destination = tmp_path / "rebuilt"
  calls = []
  def run(argv, **kwargs):
    calls.append(argv)
    assert argv[1:3] == ["-B", "-I"] and "sys.path.insert(0,str(root/'src'))" in argv[4]
    assert Path(argv[5]) == destination / "candidate-source"
    assert kwargs["cwd"] == destination / "candidate-source"
    assert kwargs["env"]["HOME"] == str(destination / "driver-home")
    result = {"schema_version": 1, "case": "cold-rebuild", "profile": "pi-fixture", "platform": cold.platform_id(),
      "lock_identity": manifest["identity"], "status": "not-run", "reason": "fixture", "targets": [{"target": name, "source_digest": argv[9], "installation": "not-run", "native_execution": "not-run", "steps": []} for name in ("first", "第二组 空格路径")]}
    with Tree(destination) as tree: tree.write_new("frozen-result.json", json_bytes(result))
    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
  monkeypatch.setattr(cold.subprocess, "run", run)
  result = cold.cold_rebuild(repository, "pi-fixture", destination, allow_host=True, uv="/fixture/uv")
  assert result["status"] == "not-run" and len(calls) == 1


def test_cursor_cold_expectation_includes_readseek_tools():
  """能力矩阵要求 Bun 普通核心独立验收含 ReadSeek；冷重建预期集不得再遗漏 cursor。"""
  from agentcfg.pi_cold_rebuild import native_cases
  assert native_cases("pi-cursor") == ("host-resources", "migration-conflicts", "model-delegate-replacement", "budget-permissions",
    "termination-recovery", "readseek-tools")
  assert "readseek-tools" not in native_cases("pi-managed")
