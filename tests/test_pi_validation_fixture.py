"""原生验收夹具只生成私有文件；Git 等程序在本测试中全部使用替身。"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from agentcfg.pi_validation_fixture import prepare_fixture
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("service", ["mcp", "web", "terminal"])
def test_native_service_fixture_selects_only_synthetic_service_bindings(tmp_path, service):
  program = tmp_path / "program"; program.write_text("never execute"); program.chmod(0o700)
  packages = tmp_path / "packages"; packages.mkdir()
  programs = {"engine": str(program), "git": str(program), "python": str(program), "python_runtime": str(packages), "python_packages": str(packages)}
  runtime = SimpleNamespace(profile="pi-default", engine="node", root=tmp_path / "runtime", lock_identity="a" * 64)
  result = prepare_fixture(tmp_path / "fixture", ROOT, runtime, "http://127.0.0.1:43123/v1", programs, run=lambda *_a, **_k: "", service=service)
  manifest = json.loads((result["workspace"].instance / "pi-home/agentcfg-manifest.json").read_text())
  if service == "mcp":
    assert "pi-mcp" in manifest["plugins"] and "pi-web" not in manifest["plugins"]
    assert manifest["options"]["mcp"]["servers"]["native-mcp"]["authentication"] == "bearer"
  elif service == "web":
    assert "pi-web" in manifest["plugins"] and manifest["options"]["web"]["providers"] == ["searxng"]
  else:
    assert manifest["options"]["agent_state"]["mode"] == "service"
    assert manifest["options"]["agent_state"]["pane"] == "native-pane"
  assert "synthetic-web-key" not in json.dumps(manifest) and "synthetic-mcp-key" not in json.dumps(manifest)


@pytest.mark.parametrize("profile,engine", [("pi-default", "node"), ("pi-managed", "node"), ("pi-codex", "node"), ("pi-cursor", "bun")])
@pytest.mark.parametrize("fixing", [False, True])
def test_native_fixture_renders_new_instance_with_synthetic_models_and_no_parent_credentials(tmp_path, monkeypatch, profile, engine, fixing):
  monkeypatch.setenv("OPENAI_API_KEY", "never-forward-parent-value")
  program = tmp_path / "synthetic-program"; program.write_text("fixture program, never execute"); program.chmod(0o700)
  packages = tmp_path / "packages"; packages.mkdir()
  programs = {"engine": str(program), "git": str(program), "python": str(program), "python_runtime": str(packages), "python_packages": str(packages)}
  runtime = SimpleNamespace(profile=profile, engine=engine, root=tmp_path / "runtime", lock_identity="a" * 64)
  calls = []
  def run(argv, **kwargs): calls.append((argv, kwargs)); return ""
  result = prepare_fixture(tmp_path / "fixture", ROOT, runtime, "http://127.0.0.1:43123/v1", programs, run=run, fixing=fixing)
  assert len(calls) == 4 and all(row[1]["cwd"] == result["project"] for row in calls)
  assert "OPENAI_API_KEY" not in result["environment"] and "never-forward-parent-value" not in json.dumps(result["environment"])
  manifest = json.loads((result["workspace"].instance / "pi-home/agentcfg-manifest.json").read_text())
  assert manifest["engine"] == engine and not manifest["bootstrap"]
  assert "python-runtime" not in manifest["options"]["paths"]["roots"]
  if profile != "pi-managed":
    from agentcfg.model_delegate import selected_route
    assert manifest["options"]["model_delegate"]["pi"]["model_roles"] == ["scout", "reviewer"]
    assert selected_route(manifest, "pi", {"provider_id": "agentcfg-native-fixture", "model_id": "agentcfg-native-reader"})[0] == "native-direct"
  assert manifest["model_bindings"]["main"]["model"] == "agentcfg-native-main"
  assert "synthetic-native-key" not in json.dumps(manifest)
  assert all(value["model"].startswith("agentcfg-native-") for value in manifest["allowed_models"])
  assert not (result["workspace"].instance / "pi-home/auth.json").exists()
  assert (result["project"] / "code.txt").read_text() == "original\n"
  assert json.dumps("changed\n" if fixing else "original\n") in (result["project"] / "test_native_fixture.py").read_text()
  with pytest.raises(Conflict): prepare_fixture(tmp_path / "fixture", ROOT, runtime, "http://127.0.0.1:43123/v1", programs, run=run)


def test_native_fixture_rejects_an_external_model_endpoint_before_any_process_or_file(tmp_path):
  calls = []
  with pytest.raises(ConfigError, match="loopback"):
    prepare_fixture(tmp_path / "fixture", ROOT, None, "https://real-account.invalid/v1", {}, run=lambda *args, **kwargs: calls.append(args))
  assert not calls and not (tmp_path / "fixture").exists()


def test_configuration_can_bind_a_new_python_environment_before_runtime_installation(tmp_path):
  from agentcfg.pi_validation_fixture import prepare_configuration
  programs = {"engine": "/fixture/node", "git": "/fixture/git", "python": "/fixture/python",
    "python_runtime": "/fixture/python-runtime", "python_packages": str(tmp_path / "checkout/.venv/lib/python3.11/site-packages")}
  calls = []
  result = prepare_configuration(tmp_path / "new-home/native", ROOT, "pi-managed", "http://127.0.0.1:43217/v1", programs,
    run=lambda argv, **kwargs: calls.append(argv) or "")
  assert len(calls) == 4
  assert not result["workspace"].instance.exists()
  options = result["workspace"].resolved.data["profile"]["agent_options"]
  assert options["task_keeper"]["enabled"] and set(options["task_keeper"]["check_ids"]) == {"native-build", "native-tests"}
  assert options["paths"]["roots"]["python-packages"]["path"] == programs["python_packages"]
  assert not Path(programs["python_packages"]).exists()


def test_preinstalled_fixture_cannot_adopt_an_ordinary_existing_directory(tmp_path):
  from agentcfg.pi_validation_fixture import prepare_configuration
  root = tmp_path / "fixture"; slot = root / "instances_root/pi/pi-default/runtimes" / ("a" * 64)
  slot.mkdir(parents=True)
  sentinel = root / "original"; sentinel.write_text("synthetic existing data")
  with pytest.raises(Conflict, match="FIXTURE_EXISTS"):
    prepare_configuration(root, ROOT, "pi-default", "http://127.0.0.1:43217/v1", {}, run=lambda *_: pytest.fail("must not run"), preinstalled_runtime=slot)
  assert sentinel.read_text() == "synthetic existing data" and not (root / "local.toml").exists()
