"""固定模块按选锁和原生投影；假npm/CLI，不启动任何服务。"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from agentcfg import commands, runtime, run_owners
from agentcfg.adapter import SecretRef
from agentcfg.pi import PiAdapter
from agentcfg.secrets import CredentialError
from agentcfg.storage import Conflict
from test_pi_reboot_dependencies import fake_npm, recipe_repository, synthetic_workspace


import pytest

from agentcfg.schema import ConfigError
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY


@pytest.mark.parametrize("profile", ["pi-base", "pi-pro"])
def test_unselected_modules_have_no_extensions_connections_or_background(tmp_path, monkeypatch, profile):
  path = local(tmp_path / "local.toml", profile=profile,
    extra=f"[overrides.profiles.{profile}.agent_options.resources]\nextensions=[]\n")
  path.write_text(path.read_text().replace('models=["example-main"]\n', 'models=["example-main"]\nplugins=[]\n', 1))
  workspace = load_workspace(path, repository=REPOSITORY)
  monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("preview不得启动子进程"))
  monkeypatch.setattr(type(workspace.backend), "sync", lambda *a, **k: pytest.fail("preview不得安装"))
  before = set(tmp_path.rglob("*"))
  workspace.candidate("synthetic-offline-candidate")
  argv = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path,
    runtime_root=tmp_path / "synthetic-runtime", instance_root=workspace.instance,
    lock_identity="synthetic-offline-candidate").argv
  assert "--no-mcp" in argv and "--no-extensions" in argv
  assert [argv[i + 1] for i, arg in enumerate(argv) if arg == "-e"] == [str(tmp_path / "synthetic-runtime/support/command-aliases.mjs")]
  assert "--extension" not in argv
  assert workspace.resolved.data["profile"]["plugins"] == []
  assert workspace.resolved.data["profile"]["mcp"] == []
  assert workspace.adapter.feature_readiness(workspace.resolved.data)["optional_modules"]["selected"] == []
  assert set(tmp_path.rglob("*")) == before
  assert not workspace.instance.exists()


@pytest.mark.parametrize("kind,names,expected", [
  ("plugins", ["pi-web-access"], "pi-plugin-module-not-admitted"),
  ("plugins", ["pi-web-access", "scoped-web-access"], "pi-plugin-module-not-admitted"),
  ("plugins", ["pi-cursor"], "pi-plugin-module-not-admitted"),
  ("plugins", ["pi-cache-hit-monitor", "pi-tool"], "pi-plugin-module-not-admitted"),
  ("mcp", ["brave"], "pi-mcp-module-not-admitted"),
  ("mcp", ["brave", "exa"], "pi-mcp-module-not-admitted"),
])
def test_unadmitted_or_competing_owners_fail_without_provider_fallback(tmp_path, kind, names, expected):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  data = deepcopy(workspace.resolved.data)
  data["profile"][kind] = names
  with pytest.raises(ConfigError) as caught:
    workspace.adapter.validate(data)
  assert caught.value.code == expected and caught.value.exit_code == 2
  assert data["profile"][kind] == names
  assert not workspace.instance.exists()


def test_candidate_probes_preserve_other_instance_auth_cache_and_history_sentinels(tmp_path):
  other = tmp_path / "other-instance"
  other.mkdir(mode=0o700)
  paths = [other / name for name in ("auth.json", "session.jsonl", "cache.json", "project-log")]
  for path in paths:
    path.write_text("SYNTHETIC_OTHER_INSTANCE_SENTINEL")
  before = {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in paths}
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  workspace.candidate("synthetic-preview")
  assert before == {p: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in paths}


def test_only_selected_modules_and_host_are_in_both_current_closures():
  from agentcfg.pi_dependencies import PiBackend
  from agentcfg.pi_modules import MODULES, selected_modules
  lock = PiBackend().read_lock(REPOSITORY)
  for profile in ("pi-base", "pi-pro"):
    root = json.loads(lock.pairs[profile][0])
    selection = lock.metadata["profiles"][profile]["recipe_inputs"]["selection"]
    assert root["dependencies"] == {"@earendil-works/pi-coding-agent": "1.3.0",
      **{MODULES[name][0]: MODULES[name][1] for name in selected_modules(selection)}}


def selected_local(path, *, plugins=(), mcp=(), skills=None, context_key=False, brave_key=True):
  local(path)
  text = path.read_text().replace('models=["example-main"]\n',
    'models=["example-main"]\nplugins=' + json.dumps(list(plugins)) + '\nmcp=' + json.dumps(list(mcp)) + '\n', 1)
  if skills is not None:
    text = text.replace('models=["example-main"]\n', 'models=["example-main"]\nskills=' + json.dumps(skills) + "\n", 1)
  if brave_key:
    text += 'pi_brave_key="SYNTHETIC_BRAVE_PRIVATE_SENTINEL"\n'
  if context_key:
    text += 'pi_context7_key="SYNTHETIC_CONTEXT_PRIVATE_SENTINEL"\n'
    text += '\n[overrides.mcp.pi-context7]\ncredential_ref="secret:pi_context7_key"\n'
  path.write_text(text)
  return path


@pytest.mark.parametrize("plugins,mcp", [(["cache-hit-monitor"], []), ([], ["pi-context7"]), ([], ["pi-brave"])])
def test_admitted_module_ids_resolve_through_strict_public_catalog(tmp_path, plugins, mcp):
  workspace = load_workspace(selected_local(tmp_path / "local.toml", plugins=plugins, mcp=mcp), repository=REPOSITORY)
  assert workspace.resolved.data["profile"]["plugins"] == plugins
  assert workspace.resolved.data["profile"]["mcp"] == mcp
  assert workspace.adapter.feature_readiness(workspace.resolved.data)["optional_modules"]["selected"]


@pytest.fixture
def module_workspace(fake_npm, tmp_path, monkeypatch):
  root, backend, calls = fake_npm
  for directory in ("schemas", "templates"):
    shutil.copytree(REPOSITORY / "agents/pi" / directory, root / "agents/pi" / directory, dirs_exist_ok=True)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 65432, "birth_id": "synthetic-boot:456"})
  monkeypatch.setattr(runtime, "checked", lambda *a, **kw: "v24.14.0")
  launched = []
  monkeypatch.setattr(runtime.subprocess, "run", lambda argv, **kw: launched.append((argv, kw)) or SimpleNamespace(returncode=19))
  def make(*, plugins=(), mcp=(), skills=None, context_key=False, brave_key=True):
    workspace = load_workspace(selected_local(tmp_path / "local.toml", plugins=plugins, mcp=mcp,
      skills=skills, context_key=context_key, brave_key=brave_key), repository=REPOSITORY)
    workspace.repository = root
    workspace.adapter = PiAdapter(root)
    lock = backend.resolve_lock_for(workspace)
    backend.sync(workspace, lock)
    commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
    return workspace, lock
  return make, backend, calls, launched


@pytest.mark.parametrize("plugins,mcp", [(["cache-hit-monitor"], []), ([], ["pi-context7"]),
  ([], ["pi-brave"]), (["cache-hit-monitor"], ["pi-context7", "pi-brave"])])
def test_selected_modules_lock_install_project_and_fake_native_exit(module_workspace, tmp_path, plugins, mcp):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(plugins=plugins, mcp=mcp)
  from jsonschema import Draft202012Validator
  schema = json.loads((REPOSITORY / "schemas/pi-lock.schema.json").read_text())
  Draft202012Validator(schema).validate(lock.metadata)
  piece = lock.metadata["profiles"]["pi-base"]
  assert set(piece["recipe_inputs"]["modules"]) == {"catppuccin", *plugins, *mcp}
  assert set(lock.metadata["profiles"]["pi-pro"]["recipe_inputs"]["modules"]) == {"catppuccin", "pi-footer"}
  npm_calls = list(calls)
  assert runtime.run(workspace, cwd=tmp_path) == 19
  assert len(launched) == 1 and calls == npm_calls
  argv, kwargs = launched[0]
  assert ("--no-mcp" in argv) == (not mcp)
  assert ("builtin:mcp" in argv) == bool(mcp)
  if plugins:
    assert any(item.endswith("node_modules/@narumitw/pi-cache-hit-monitor/src/index.ts") for item in argv)
  root = backend.root(workspace, backend.runtime_identity(workspace, lock))
  assert (root / "support/mcp-launch.py").exists() == bool(mcp)
  if mcp:
    assert (root / "support/mcp-launch.py").stat().st_mode & 0o777 == 0o600
  if mcp:
    native_raw = (workspace.instance / "pi-home/mcp.json").read_text()
    assert "SYNTHETIC_" not in native_raw
    native = json.loads(native_raw)["mcpServers"]
    assert set(native) == set(mcp)
    for name, server in native.items():
      assert server["args"][0] == str(root / "support/mcp-launch.py")
      assert server["exposure"] == "hidden"
      assert set(server["toolExposure"]) == ({"brave_web_search"} if name == "pi-brave" else {"resolve-library-id", "query-docs"})
      assert Path(server["cwd"]) != tmp_path and list(Path(server["cwd"]).iterdir()) == []
      assert all(value.startswith("${AGENTCFG_PI_MCP_") for value in server["env"].values())
    injected = kwargs["env"]
    for item in workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path, runtime_root=root,
        instance_root=workspace.instance, lock_identity=lock.identity).environment:
      if isinstance(item.value, SecretRef) and item.name.startswith("AGENTCFG_PI_MCP_"):
        assert injected[item.name].startswith("SYNTHETIC_")


@pytest.mark.parametrize("mcp,context_key", [(["pi-brave"], False), (["pi-context7"], True)])
def test_selected_required_service_key_missing_refuses_before_cli(module_workspace, tmp_path, monkeypatch, mcp, context_key):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(mcp=mcp, context_key=context_key)
  original = type(workspace.secret_store).resolve
  def resolve(store, reference, *, required=True):
    if reference.reference in ("secret:pi_brave_key", "secret:pi_context7_key"):
      raise CredentialError()
    return original(store, reference, required=required)
  monkeypatch.setattr(type(workspace.secret_store), "resolve", resolve)
  with pytest.raises(CredentialError):
    runtime.run(workspace, cwd=tmp_path)
  assert not launched and not (workspace.state_root / "run-owners").exists()


@pytest.mark.parametrize("damage", ["extra-server", "literal-env", "command", "cwd-content", "helper-content"])
def test_mcp_drift_is_refused_without_repair_or_launch(module_workspace, tmp_path, damage):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(mcp=["pi-brave"])
  native = workspace.instance / "pi-home/mcp.json"
  body = json.loads(native.read_text())
  if damage == "extra-server": body["mcpServers"]["unknown"] = {"command": "arbitrary"}
  elif damage == "literal-env": body["mcpServers"]["pi-brave"]["env"]["BRAVE_API_KEY"] = "SYNTHETIC_UNMANAGED_SECRET"
  elif damage == "command": body["mcpServers"]["pi-brave"]["command"] = "arbitrary"
  elif damage == "cwd-content": (Path(body["mcpServers"]["pi-brave"]["cwd"]) / ".env").write_text("synthetic")
  else:
    root = backend.root(workspace, backend.runtime_identity(workspace, lock))
    (root / "support/mcp-launch.py").write_text("changed")
  if damage in ("extra-server", "literal-env", "command"): native.write_text(json.dumps(body))
  before, npm_calls = native.read_bytes(), list(calls)
  from agentcfg.process import DependencyError
  with pytest.raises((Conflict, DependencyError)):
    runtime.run(workspace, cwd=tmp_path)
  assert native.read_bytes() == before and calls == npm_calls and not launched


@pytest.mark.parametrize("selection", [
  {"plugins": ["cache-hit-monitor"]}, {"plugins": ["pi-footer"]}, {"mcp": ["pi-context7"]},
  {"mcp": ["pi-brave"]}, {"skills": ["playwright-cli"]},
])
def test_selected_fake_cancellation_preserves_unknown_owner(module_workspace, tmp_path, monkeypatch, selection):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(**selection)
  def cancel(*a, **kw): raise KeyboardInterrupt()
  monkeypatch.setattr(runtime.subprocess, "run", cancel)
  with pytest.raises(KeyboardInterrupt):
    runtime.run(workspace, cwd=tmp_path)
  owners = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()
  assert len(owners) == 1 and next(iter(owners.values()))["state"] == "unknown"
  with pytest.raises(Conflict): commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))


def test_support_source_change_invalidates_only_selected_mcp_slice(fake_npm, tmp_path):
  root, backend, calls = fake_npm
  workspace = synthetic_workspace(root, tmp_path, selection={"mcp": ["pi-context7"]})
  lock = backend.resolve_lock_for(workspace)
  base_identity = backend.runtime_identity(workspace, lock)
  pro = synthetic_workspace(root, tmp_path, profile="pi-pro")
  pro_identity = backend.runtime_identity(pro, lock)
  (root / "agents/pi/support/mcp-launch.py").write_text("synthetic changed helper")
  assert backend.read_lock(root) == lock
  assert backend.runtime_identity(pro, lock) == pro_identity
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)
  assert base_identity != pro_identity


def test_unselected_module_audit_and_source_do_not_change_default_identity(fake_npm, tmp_path):
  root, backend, calls = fake_npm
  workspace = synthetic_workspace(root, tmp_path)
  lock = backend.resolve_lock(root)
  before = backend.runtime_identity(workspace, lock)
  path = root / "agents/pi/dependencies.json"
  recipe = json.loads(path.read_text())
  recipe["modules"]["pi-context7"]["source_commit"] = "a" * 40
  recipe["module_script_audits"]["pi-context7"] = {"node_modules/synthetic": {
    "package_json_digest": "b" * 64, "lifecycle": {}, "decision": "ignored_not_required"}}
  path.write_text(json.dumps(recipe))
  assert backend.read_lock(root) == lock
  assert backend.runtime_identity(workspace, lock) == before


def test_launcher_exec_is_fixed_and_environment_is_service_scoped(monkeypatch):
  import importlib.util
  import sys
  source = REPOSITORY / "agents/pi/support/mcp-launch.py"
  spec = importlib.util.spec_from_file_location("pi_mcp_test_launcher", source)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  env = {key: "synthetic" for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "XDG_CACHE_HOME", "NODE_OPTIONS", "NODE_PATH",
    "OPENAI_API_KEY", "AGENTCFG_PI_CREDENTIAL_FAKE", "BRAVE_API_KEY", "CONTEXT7_API_KEY", "CONTEXT7_API_URL", "BRAVE_API_KEY_FILE")}
  filtered = module.filtered_environment("context7", env)
  assert set(filtered) == {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "XDG_CACHE_HOME", "CONTEXT7_API_KEY"}
  called = []
  monkeypatch.setattr(module.os, "execvpe", lambda *args: called.append(args))
  monkeypatch.setattr(sys, "argv", [str(source), "brave"])
  module.main()
  assert called[0][0] == "node" and called[0][1][1].endswith("node_modules/@brave/brave-search-mcp-server/dist/index.js")
  monkeypatch.setattr(sys, "argv", [str(source), "arbitrary"])
  with pytest.raises(SystemExit): module.main()


def test_disabling_module_removes_managed_loading_without_deleting_native_state(module_workspace, tmp_path):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(mcp=["pi-context7"])
  # 缓存与账号正文不是管理器资料；哨兵仅证明禁用不删除它们。
  sentinels = [workspace.instance / "pi-mcp/pi-context7/home/native-cache", workspace.instance / "pi-home/auth.json"]
  for path in sentinels:
    path.write_text("SYNTHETIC_NATIVE_STATE")
  before = {p: (p.read_bytes(), p.stat().st_ino) for p in sentinels}
  workspace, lock = make()
  assert json.loads((workspace.instance / "pi-home/mcp.json").read_text()) == {}
  assert runtime.run(workspace, cwd=tmp_path) == 19
  argv, options = launched[0]
  assert "--no-mcp" in argv and "builtin:mcp" not in argv
  assert not any(key.startswith("AGENTCFG_PI_MCP_") for key in options["env"])
  assert before == {p: (p.read_bytes(), p.stat().st_ino) for p in sentinels}


def test_module_reselection_after_retirement_preserves_footer_and_native_state(module_workspace, tmp_path):
  make, backend, calls, launched = module_workspace
  selection = {"plugins": ["pi-footer", "cache-hit-monitor"], "mcp": ["pi-context7"]}
  workspace, lock = make(**selection)
  footer = workspace.instance / "pi-home/extensions/pi-footer.json"
  preference = json.loads(footer.read_text())
  preference["enabled"] = False
  footer.write_text(json.dumps(preference))
  cache = workspace.instance / "pi-mcp/pi-context7/home/native-cache"
  cache.write_text("SYNTHETIC_NATIVE_STATE")
  before = {p: (p.read_bytes(), p.stat().st_ino) for p in (footer, cache)}
  workspace, lock = make()
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  assert json.loads((workspace.instance / "pi-home/mcp.json").read_text()) == {}
  workspace, lock = make(**selection)
  assert before == {p: (p.read_bytes(), p.stat().st_ino) for p in (footer, cache)}
  assert set(json.loads((workspace.instance / "pi-home/mcp.json").read_text())["mcpServers"]) == {"pi-context7"}
  assert runtime.run(workspace, cwd=tmp_path) == 19
  argv, _ = launched[0]
  assert "builtin:mcp" in argv and "--no-mcp" not in argv
  assert sum(arg.endswith("node_modules/pi-footer/src/index.ts") for arg in argv) == 1


@pytest.mark.parametrize("damage", ["symlink", "missing", "mode"])
def test_private_mcp_cwd_requires_existing_owned_private_directory(module_workspace, tmp_path, damage):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(mcp=["pi-context7"])
  directory = workspace.instance / "pi-mcp/pi-context7/cwd"
  if damage == "mode": directory.chmod(0o755)
  else:
    directory.rmdir()
    if damage == "symlink": directory.symlink_to(tmp_path, target_is_directory=True)
  with pytest.raises(Conflict): runtime.run(workspace, cwd=tmp_path)
  assert not launched


def test_pi_host_environment_drops_raw_service_override_variables(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  env = {"PATH": "synthetic", "CONTEXT7_API_URL": "https://example.invalid", "CONTEXT7_API_KEY": "synthetic",
    "BRAVE_API_KEY_FILE": "synthetic", "BRAVE_API_KEY": "synthetic"}
  assert workspace.adapter.adjust_launch_environment(workspace, None, env, None) == {"PATH": "synthetic", "PI_OFFLINE": "1"}


@pytest.mark.parametrize("operation", ["plan", "capture", "rollback", "doctor"])
def test_mcp_literal_secret_never_enters_reports_or_backups(module_workspace, monkeypatch, capsys, operation):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(mcp=["pi-brave"])
  # 建立previous，使rollback也先经过既有守卫检查。
  workspace.resolved.data["profile"]["agent_options"]["settings"]["defaultThinkingLevel"] = "low"
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  native = workspace.instance / "pi-home/mcp.json"
  document = json.loads(native.read_text())
  sentinel = "SYNTHETIC_MCP_UNMANAGED_CREDENTIAL"
  document["mcpServers"]["pi-brave"]["env"]["BRAVE_API_KEY"] = sentinel
  native.write_text(json.dumps(document))
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  with pytest.raises(Conflict) as error:
    getattr(commands, "cmd_" + operation)(SimpleNamespace(live=False))
  captured = capsys.readouterr()
  assert sentinel not in captured.out + captured.err + str(error.value)
  for root in (workspace.state_root, workspace.cache):
    for path in root.rglob("*"):
      if path.is_file(): assert sentinel.encode() not in path.read_bytes()
  assert not launched


@pytest.mark.parametrize("field,value", [("command", "npx"), ("args", ["arbitrary.js"]),
  ("url", "https://example.invalid/mcp"), ("transport", "http")])
def test_selected_mcp_mapping_rejects_arbitrary_executable_or_route(tmp_path, field, value):
  workspace = load_workspace(selected_local(tmp_path / "local.toml", mcp=["pi-context7"]), repository=REPOSITORY)
  data = deepcopy(workspace.resolved.data)
  data["mcp"]["pi-context7"][field] = value
  with pytest.raises(ConfigError) as error: workspace.adapter.validate(data)
  assert error.value.code == "pi-mcp-module-not-admitted"


def test_selected_plugin_entry_cannot_be_redirected(tmp_path):
  workspace = load_workspace(selected_local(tmp_path / "local.toml", plugins=["cache-hit-monitor"]), repository=REPOSITORY)
  data = deepcopy(workspace.resolved.data)
  data["plugins"]["cache-hit-monitor"]["entry"] = "arbitrary.ts"
  with pytest.raises(ConfigError) as error: workspace.adapter.validate(data)
  assert error.value.code == "pi-plugin-module-not-admitted"
