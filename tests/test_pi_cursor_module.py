"""Cursor公开插件与本实例OAuth边界；假npm/CLI，不启动账号或插件。"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from agentcfg import commands, runtime, run_owners
from agentcfg.adapter import SecretRef
from agentcfg.pi import PiAdapter
from agentcfg.pi_dependencies import dependency_selection, recipe_inputs
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY
from test_pi_reboot_dependencies import fake_npm, recipe_repository, synthetic_workspace


def cursor_local(path, *, selected=True):
  path.write_text('schema_version=1\n[machine]\nid="cursor-example"\ndefault_profile="pi-base"\n'
    '[overrides.providers.cursor]\nprotocol="oauth-dynamic"\nauth_kind="oauth"\n'
    '[overrides.models.cursor-main]\nprovider="cursor"\nremote_id="fictional-cursor-model"\ninput=["text"]\n'
    '[overrides.profiles.pi-base]\nproviders=["cursor"]\nmodels=["cursor-main"]\n'
    + ('plugins=["pi-cursor"]\n' if selected else 'plugins=[]\n')
    + '[overrides.profiles.pi-base.roles]\nmain="cursor-main"\n')
  return path


@pytest.fixture
def cursor_workspace(fake_npm, tmp_path, monkeypatch):
  root, backend, calls = fake_npm
  for directory in ("schemas", "templates"):
    shutil.copytree(REPOSITORY / "agents/pi" / directory, root / "agents/pi" / directory)
  workspace = load_workspace(cursor_local(tmp_path / "local.toml"), repository=REPOSITORY)
  workspace.repository, workspace.adapter = root, PiAdapter(root)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 76543, "birth_id": "synthetic-boot:567"})
  monkeypatch.setattr(runtime, "checked", lambda *a, **kw: "v24.14.0")
  launched = []
  monkeypatch.setattr(runtime.subprocess, "run", lambda argv, **kw: launched.append((argv, kw)) or SimpleNamespace(returncode=0))
  lock = backend.resolve_lock_for(workspace)
  backend.sync(workspace, lock)
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  return workspace, backend, lock, calls, launched


def test_cursor_public_oauth_owner_native_route_and_fake_launch(cursor_workspace, tmp_path):
  workspace, backend, lock, calls, launched = cursor_workspace
  data = workspace.resolved.data
  piece = lock.metadata["profiles"]["pi-base"]
  assert piece["dependencies"]["@rahularya01/pi-cursor"] == "1.4.39"
  assert "@rahularya01/pi-cursor" not in lock.metadata["profiles"]["pi-pro"]["dependencies"]
  from jsonschema import Draft202012Validator
  Draft202012Validator(json.loads((REPOSITORY / "schemas/pi-lock.schema.json").read_text())).validate(lock.metadata)
  assert workspace.adapter.route(data, "cursor") == "cursor"
  claims = workspace.schemas.bundles["pi"].authentication_claims(data)
  assert [(claim.provider, claim.owner) for claim in claims if claim.provider == "cursor"] == [("cursor", "pi-cursor")]
  artifacts = workspace.adapter.render(data)
  assert not any(item.target.path == "pi-home/models.json" and (item.target.selector or "").startswith("/providers/cursor/") for item in artifacts)
  spec = workspace.adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=workspace.instance, lock_identity=lock.identity)
  assert not any(isinstance(item.value, SecretRef) and "cursor" in item.value.reference for item in spec.environment)
  assert runtime.run(workspace, cwd=tmp_path) == 0
  argv, options = launched[0]
  assert any(arg.endswith("/node_modules/@rahularya01/pi-cursor/dist/index.js") for arg in argv)
  assert options["env"]["PI_CURSOR_SYSTEM_CREDENTIALS"] == "0"
  assert options["env"]["PI_CURSOR_CACHE_DIR"] == str(workspace.instance / "pi-cursor")
  assert (workspace.instance / "pi-cursor").stat().st_mode & 0o777 == 0o700


def test_cursor_provider_requires_plugin_and_plugin_requires_matching_provider(tmp_path):
  with pytest.raises(ConfigError): load_workspace(cursor_local(tmp_path / "missing.toml", selected=False), repository=REPOSITORY)
  from test_pi_optional_modules import selected_local
  with pytest.raises(ConfigError): load_workspace(selected_local(tmp_path / "wrong.toml", plugins=["pi-cursor"]), repository=REPOSITORY)


@pytest.mark.parametrize("mutation", ["base-url", "credential", "owner", "route", "other-owner"])
def test_cursor_owner_and_route_are_strict(tmp_path, mutation):
  workspace = load_workspace(cursor_local(tmp_path / "local.toml"), repository=REPOSITORY)
  data = deepcopy(workspace.resolved.data)
  if mutation == "base-url": data["providers"]["cursor"]["base_url"] = "https://example.invalid"
  elif mutation == "credential": data["providers"]["cursor"]["credential_ref"] = "secret:cursor_key"
  elif mutation == "owner": data["adapter_documents"]["bindings"]["oauth"]["cursor"]["owner"] = "pi-native"
  elif mutation == "route": data["adapter_documents"]["bindings"]["oauth"]["cursor"]["route"] = "other"
  else:
    data["providers"]["other"] = data["providers"].pop("cursor")
    data["models"]["cursor-main"]["provider"] = "other"
    data["adapter_documents"]["bindings"]["oauth"]["other"] = {"route": "cursor", "owner": "pi-cursor"}
  with pytest.raises(ConfigError): workspace.adapter.validate(data)


def test_inherited_cursor_credentials_and_routes_are_removed_and_constants_fixed(cursor_workspace, tmp_path):
  workspace, backend, lock, calls, launched = cursor_workspace
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=workspace.instance, lock_identity=lock.identity)
  env = {key: "SYNTHETIC_FORBIDDEN" for key in ["CURSOR_ACCESS_TOKEN", "CURSOR_API_KEY", "PI_CURSOR_ACCESS_TOKEN",
    "PI_CURSOR_PROVIDER_ROUTE", "PI_CURSOR_CACHE_DIR", "PI_CURSOR_SYSTEM_CREDENTIALS", "USAGE_SESSION_TOKEN", "USAGE_SESSION_TOKEN_OTHER"]}
  env["PATH"] = "/synthetic/bin"
  result = workspace.adapter.adjust_launch_environment(workspace, spec, env, None)
  assert result == {"PATH": "/synthetic/bin", "PI_OFFLINE": "1", "PI_CURSOR_SYSTEM_CREDENTIALS": "0", "PI_CURSOR_CACHE_DIR": str(workspace.instance / "pi-cursor")}
  workspace.adapter.validate_operation_environment(workspace, spec=spec, env=result)
  result["CURSOR_ACCESS_TOKEN"] = "SYNTHETIC_FORBIDDEN"
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict): workspace.adapter.validate_operation_environment(workspace, spec=spec, env=result)


def test_offline_management_never_reads_auth_and_disable_preserves_native_material(cursor_workspace, tmp_path, monkeypatch):
  workspace, backend, lock, calls, launched = cursor_workspace
  auth = workspace.instance / "pi-home/auth.json"
  cache = workspace.instance / "pi-cursor/journal-sentinel"
  for path in (auth, cache): path.write_text("SYNTHETIC_NATIVE_CURSOR_MATERIAL")
  before = {path: (path.read_bytes(), path.stat().st_ino) for path in (auth, cache)}
  original = Tree.read
  def safe_read(tree, path, **kwargs):
    assert not str(path).endswith("auth.json")
    return original(tree, path, **kwargs)
  monkeypatch.setattr(Tree, "read", safe_read)
  backend.read_lock(workspace.repository)
  workspace.candidate(lock.identity)
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  commands.cmd_doctor(SimpleNamespace(live=False))
  # 用公开虚构API provider替换OAuth并显式重锁/apply；不清理原生认证/缓存。
  local(workspace.local_path)
  workspace.local_path.write_text(workspace.local_path.read_text().replace('id="reboot-test"', 'id="cursor-example"'))
  replacement = load_workspace(workspace.local_path, repository=REPOSITORY)
  replacement.repository, replacement.adapter = workspace.repository, workspace.adapter
  replacement.resolved.data["machine"]["paths"] = workspace.resolved.data["machine"]["paths"]
  new_lock = backend.resolve_lock_for(replacement)
  backend.sync(replacement, new_lock)
  commands.apply_candidate(replacement, new_lock, replacement.candidate(new_lock.identity))
  assert before == {path: (path.read_bytes(), path.stat().st_ino) for path in (auth, cache)}


def test_unselected_cursor_sources_and_audits_do_not_stale_default_slice(fake_npm, tmp_path):
  root, backend, calls = fake_npm
  workspace = synthetic_workspace(root, tmp_path)
  lock = backend.resolve_lock(root)
  before = backend.runtime_identity(workspace, lock)
  recipe_path = root / "agents/pi/dependencies.json"
  recipe = json.loads(recipe_path.read_text())
  recipe["modules"]["pi-cursor"]["source_commit"] = "b" * 40
  recipe["module_script_audits"]["pi-cursor"] = {"node_modules/synthetic": {"package_json_digest": "c" * 64,
    "lifecycle": {}, "decision": "ignored_not_required"}}
  recipe_path.write_text(json.dumps(recipe))
  assert backend.read_lock(root) == lock and backend.runtime_identity(workspace, lock) == before
  base = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  env = base.adapter.adjust_launch_environment(base, None, {"PATH": "/synthetic/bin", "CURSOR_ACCESS_TOKEN": "synthetic", "PI_CURSOR_CACHE_DIR": "foreign", "USAGE_SESSION_TOKEN": "synthetic"}, None)
  assert env == {"PATH": "/synthetic/bin", "PI_OFFLINE": "1"}
  assert not (base.instance / "pi-cursor").exists()


@pytest.mark.parametrize("damage", ["missing", "link", "mode"])
def test_cursor_private_cache_requires_existing_owned_directory(cursor_workspace, tmp_path, damage):
  workspace, backend, lock, calls, launched = cursor_workspace
  cache = workspace.instance / "pi-cursor"
  if damage == "mode": cache.chmod(0o755)
  else:
    cache.rmdir()
    if damage == "link": cache.symlink_to(tmp_path, target_is_directory=True)
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict): runtime.run(workspace, cwd=tmp_path)
  assert not launched


@pytest.mark.parametrize("mutation", ["system", "cache", "missing"])
def test_final_cursor_constant_environment_cannot_be_overridden(cursor_workspace, mutation):
  workspace, backend, lock, calls, launched = cursor_workspace
  env = workspace.adapter.adjust_launch_environment(workspace, None, {"PATH": "/synthetic/bin"}, None)
  if mutation == "system": env["PI_CURSOR_SYSTEM_CREDENTIALS"] = "1"
  elif mutation == "cache": env["PI_CURSOR_CACHE_DIR"] = "/synthetic/foreign"
  else: env.pop("PI_CURSOR_SYSTEM_CREDENTIALS")
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict): workspace.adapter.validate_operation_environment(workspace, env=env)


def test_cursor_fake_cancellation_keeps_unknown_and_blocks_maintenance(cursor_workspace, tmp_path, monkeypatch):
  workspace, backend, lock, calls, launched = cursor_workspace
  def cancel(*args, **kwargs): raise KeyboardInterrupt()
  monkeypatch.setattr(runtime.subprocess, "run", cancel)
  with pytest.raises(KeyboardInterrupt): runtime.run(workspace, cwd=tmp_path)
  records = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()
  assert len(records) == 1 and next(iter(records.values()))["state"] == "unknown"
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict): commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  assert not launched
