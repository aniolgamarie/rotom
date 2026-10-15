"""原生验收夹具只生成私有文件；Git 等程序在本测试中全部使用替身。"""
import json
import re
import shutil
from urllib.parse import urlsplit
from pathlib import Path
from types import SimpleNamespace
import pytest

from agentcfg import pi_validation_fixture, secret_files
from agentcfg.model_defaults import read_model_defaults
from agentcfg.pi_validation_fixture import prepare_fixture
from agentcfg.workspace import load_public_catalog
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
  allowed = {value["model"] for value in manifest["allowed_models"]}
  assert {"agentcfg-native-main", "agentcfg-native-reader", "agentcfg-native-reviewer"} <= allowed
  assert all(re.fullmatch(r"agentcfg-native-[a-z-]+", model) for model in allowed)
  assert not {"deepseek-flash", "kimi-for-coding", "glm-5.3"} & allowed
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


def test_fixture_closes_shared_default_pool_without_reading_account_sentinels(tmp_path, monkeypatch):
  repository = tmp_path / "public-source"
  for name in ("agents", "profiles", "shared", "schemas"):
    shutil.copytree(ROOT / name, repository / name)
  defaults = repository / "shared/defaults/models.toml"
  original_defaults = defaults.read_bytes()
  catalog, _ = load_public_catalog(repository=repository)
  default_models = read_model_defaults(defaults)["pi"]["models"]
  original_providers = {identity: catalog.registry["models"][identity]["provider"] for identity in default_models}
  sentinel = Path.home() / "config/agentcfg/secrets.toml"
  sentinel.parent.mkdir(parents=True)
  sentinel.write_text('schema_version=1\n[shared]\nnever_read="synthetic-account-sentinel"\n')
  auth = Path.home() / ".pi/agent/auth.json"
  auth.parent.mkdir(parents=True)
  auth.write_text('{"never_read":"synthetic-auth-sentinel"}')
  original_open = Path.open
  original_private_read = secret_files.read_private_file
  def guard_open(path, *args, **kwargs):
    assert path not in (sentinel, auth)
    return original_open(path, *args, **kwargs)
  def guard_private(path, *args, **kwargs):
    assert Path(path) not in (sentinel, auth)
    return original_private_read(path, *args, **kwargs)
  monkeypatch.setattr(Path, "open", guard_open)
  monkeypatch.setattr("agentcfg.secret_files.read_private_file", guard_private)
  monkeypatch.setenv("OPENAI_API_KEY", "synthetic-parent-account-sentinel")
  program = tmp_path / "program"
  program.write_text("never execute")
  program.chmod(0o700)
  packages = tmp_path / "python-packages"
  packages.mkdir()
  programs = {"engine": str(program), "git": str(program), "python": str(program), "python_runtime": str(packages), "python_packages": str(packages)}
  runtime = SimpleNamespace(profile="pi-default", engine="node", root=tmp_path / "runtime", lock_identity="a" * 64)
  result = prepare_fixture(tmp_path / "fixture", repository, runtime, "http://127.0.0.1:43123/v1", programs, run=lambda *_a, **_k: "")
  workspace = result["workspace"]
  manifest = json.loads((workspace.instance / "pi-home/agentcfg-manifest.json").read_text())
  models = json.loads((workspace.instance / "pi-home/models.json").read_text())
  assert {identity: workspace.resolved.data["models"][identity]["provider"] for identity in default_models} == original_providers
  allowed = manifest["allowed_models"]
  assert all(re.fullmatch(r"agentcfg-native-[a-z-]+", model["model"]) for model in allowed)
  assert len(allowed) == 13
  default_ids = [model["model"] for model in allowed if model["model"].startswith("agentcfg-native-default-")]
  assert len(default_ids) == len(set(default_ids)) == 8
  assert all(re.fullmatch(r"agentcfg-native-default-[a-z]+", identity) for identity in default_ids)
  assert {name: manifest["model_bindings"][name]["model"] for name in ("main", "scout", "reviewer")} == {
    "main": "agentcfg-native-main", "scout": "agentcfg-native-reader", "reviewer": "agentcfg-native-reviewer"}
  assert len(models["providers"]) == 4
  for provider in models["providers"].values():
    endpoint = urlsplit(provider["baseUrl"])
    assert (endpoint.scheme, endpoint.hostname, endpoint.port, endpoint.path) == ("http", "127.0.0.1", 43123, "/v1")
    assert all(re.fullmatch(r"agentcfg-native-[a-z-]+", model["id"]) for model in provider["models"])
    assert re.fullmatch(r"\$AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16}", provider["apiKey"])
    assert result["environment"][provider["apiKey"][1:]] == "synthetic-native-key"
  assert "synthetic-parent-account-sentinel" not in json.dumps(result["environment"])
  assert "synthetic-account-sentinel" not in json.dumps(manifest)
  assert not (workspace.instance / "pi-home/auth.json").exists()
  assert defaults.read_bytes() == original_defaults
  assert not (tmp_path / "fixture/fixture-secrets.toml").exists()


def test_fixture_without_defaults_uses_only_synthetic_overrides_at_mocked_workspace_boundary(tmp_path, monkeypatch):
  repository = tmp_path / "synthetic-source"
  repository.mkdir()
  workspace = object()
  captured = {}
  def load(local, profile, *, repository):
    import tomllib
    captured.update(tomllib.loads(local.read_text()))
    assert profile == "pi-default"
    return workspace
  monkeypatch.setattr(pi_validation_fixture, "load_workspace", load)
  monkeypatch.setattr(pi_validation_fixture, "load_public_catalog", lambda **_kwargs: pytest.fail("no defaults to load"))
  programs = {name: str(tmp_path / name) for name in ("engine", "git", "python", "python_runtime", "python_packages")}
  result = pi_validation_fixture.prepare_configuration(tmp_path / "fixture", repository, "pi-default",
    "http://127.0.0.1:43123/v1", programs, run=lambda *_args, **_kwargs: "")
  assert result["workspace"] is workspace
  assert set(captured["overrides"]["providers"]) == {"native-fixture"}
  assert set(captured["overrides"]["models"]) == {"native-" + role for role in pi_validation_fixture.MODELS}
  assert captured["overrides"]["profiles"]["pi-default"]["roles"] == {
    "main": "native-main", "scout": "native-reader", "reviewer": "native-reviewer"}
