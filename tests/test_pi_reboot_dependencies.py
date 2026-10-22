"""全新 Pi npm 闭包：合成发布物、假 npm，不加载第三方代码。"""

from copy import deepcopy
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


SRI = "sha512-" + base64.b64encode(b"s" * 64).decode()


def resolution():
  return {"lockfileVersion": 3, "packages": {
    "": {"dependencies": {"fake-host": "1.0.0"}},
    "node_modules/fake-host": {"version": "1.0.0", "resolved": "https://registry.npmjs.org/fake-host/-/fake-host-1.0.0.tgz",
      "integrity": SRI, "license": "MIT", "dependencies": {"fake-child": "^2.0.0"}},
    "node_modules/fake-child": {"version": "2.0.1", "resolved": "https://registry.npmjs.org/fake-child/-/fake-child-2.0.1.tgz",
      "integrity": SRI, "license": "MIT"}}}


def validate(value):
  from agentcfg.pi_dependencies import validate_package_lock
  return validate_package_lock(value, {"fake-host": "1.0.0"})


def test_complete_public_npm_closure():
  validate(resolution())


@pytest.mark.parametrize("damage", ["missing-child", "missing-peer", "extra-root", "orphan", "no-sri", "weak-sri",
  "credentials", "non-registry", "link", "traversal", "wrong-version", "no-license", "unknown-root"])
def test_invalid_or_unselected_closure_rejected(damage):
  value = resolution()
  host = value["packages"]["node_modules/fake-host"]
  if damage == "missing-child": del value["packages"]["node_modules/fake-child"]
  elif damage == "missing-peer": host["peerDependencies"] = {"fake-peer": "^1.0.0"}
  elif damage == "extra-root": value["packages"][""]["dependencies"]["unselected"] = "1.0.0"
  elif damage == "orphan": value["packages"]["node_modules/unselected"] = deepcopy(host)
  elif damage == "no-sri": del host["integrity"]
  elif damage == "weak-sri": host["integrity"] = "sha1-abc"
  elif damage == "credentials": host["resolved"] = "https://secret-sentinel@registry.npmjs.org/fake.tgz"
  elif damage == "non-registry": host["resolved"] = "file:../../outside.tgz"
  elif damage == "link": host["link"] = True
  elif damage == "traversal": value["packages"]["../outside"] = deepcopy(host)
  elif damage == "wrong-version": host["version"] = "1.0.1"
  elif damage == "no-license": del host["license"]
  elif damage == "unknown-root": value["packages"][""]["scripts"] = {"install": "unapproved"}
  with pytest.raises(ConfigError) as caught:
    validate(value)
  assert "secret-sentinel" not in str(caught.value)


def test_optional_peer_may_be_absent_but_required_peer_must_be_locked():
  value = resolution()
  value["packages"]["node_modules/fake-host"].update(peerDependencies={"fake-peer": "^1.0.0"},
    peerDependenciesMeta={"fake-peer": {"optional": True}})
  validate(value)


def test_nested_dependency_resolution_uses_node_ancestor_rules():
  value = resolution()
  child = value["packages"].pop("node_modules/fake-child")
  value["packages"]["node_modules/fake-host/node_modules/fake-child"] = child
  validate(value)


@pytest.mark.parametrize("scripts", [{"postinstall": "node unknown.js"}, {"preinstall": "sh unknown.sh"}, {"install": "node-gyp rebuild"}])
def test_unknown_install_script_stops_before_activation(tmp_path, scripts):
  from agentcfg.pi_dependencies import validate_installed_packages
  value = resolution()
  for path, record in value["packages"].items():
    if not path: continue
    target = tmp_path / path / "package.json"
    target.parent.mkdir(parents=True)
    package = {"name": path.split("node_modules/")[-1], "version": record["version"], "license": "MIT"}
    if path.endswith("fake-host"): package["scripts"] = scripts
    target.write_text(json.dumps(package))
  with pytest.raises(ConfigError, match="script"):
    validate_installed_packages(tmp_path, value, {})


def test_audited_skipped_script_requires_exact_installed_package_body(tmp_path):
  from agentcfg.pi_dependencies import digest, validate_installed_packages
  value = resolution()
  audits = {}
  for path, record in value["packages"].items():
    if not path: continue
    target = tmp_path / path / "package.json"
    target.parent.mkdir(parents=True)
    package = {"name": path.split("node_modules/")[-1], "version": record["version"], "license": "MIT"}
    if path.endswith("fake-host"): package["scripts"] = {"postinstall": "node optional.js"}
    raw = json.dumps(package).encode()
    target.write_bytes(raw)
    audits[path] = {"package_json_digest": digest(raw), "lifecycle": package.get("scripts", {}), "decision": "ignored_not_required"}
  validate_installed_packages(tmp_path, value, audits)
  target = tmp_path / "node_modules/fake-host/package.json"
  target.write_bytes(target.read_bytes() + b" ")
  with pytest.raises(ConfigError): validate_installed_packages(tmp_path, value, audits)


def test_pi_lock_publication_has_exact_fixed_file_allowlist():
  from agentcfg.publication import FILES
  assert FILES["pi"] == frozenset({"manifest.json", "pi-base/package.json", "pi-base/package-lock.json",
    "pi-pro/package.json", "pi-pro/package-lock.json"})


@pytest.fixture
def staged_runtime(tmp_path):
  from agentcfg.pi_dependencies import digest, platform_id
  from agentcfg.pi_runtime_packages import seal
  root = tmp_path / "stage"
  root.mkdir(mode=0o700)
  value = resolution()
  package = {"name": "synthetic-runtime", "private": True, "dependencies": {"fake-host": "1.0.0"}}
  package_raw, lock_raw = json.dumps(package).encode(), json.dumps(value).encode()
  (root / "package.json").write_bytes(package_raw)
  (root / "package-lock.json").write_bytes(lock_raw)
  for path, record in value["packages"].items():
    if not path: continue
    directory = root / path
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps({"name": path.split("node_modules/")[-1], "version": record["version"]}))
  (root / "node_modules/fake-host/bin.js").write_text("// synthetic, never execute\n")
  (root / "node_modules/fake-host/LICENSE").write_text("Synthetic test license\n")
  piece = {"profile": "pi-base", "dependencies": package["dependencies"], "package_json_digest": digest(package_raw),
    "package_lock_digest": digest(lock_raw), "required_files": ["node_modules/fake-host/bin.js", "node_modules/fake-host/LICENSE"],
    "script_audits": {}}
  piece["identity"] = digest(piece)
  tools = {"node": "v22.19.0", "npm": "11.9.0"}
  identity = digest({"profile_identity": piece["identity"], "platform": platform_id(), "toolchains": tools})
  seal(root, identity, "a" * 64, piece, toolchains=tools)
  return root, identity, piece, tools


def test_sealed_body_and_receipt_manifest_are_checked(staged_runtime):
  from agentcfg.pi_runtime_packages import status
  root, identity, _, _ = staged_runtime
  assert status(root, identity) == "installed"
  entry = root / "node_modules/fake-host/bin.js"
  entry.write_text("// synthetic changed body\n")
  assert status(root, identity) == "damaged"


@pytest.mark.parametrize("damage", ["missing-entry", "missing-license", "extra-file", "receipt-key", "receipt-manifest", "escaped-link"])
def test_installed_shape_or_content_damage_is_not_installed(staged_runtime, tmp_path, damage):
  from agentcfg.pi_runtime_packages import status
  root, identity, _, _ = staged_runtime
  if damage in ("missing-entry", "missing-license"):
    (root / "node_modules/fake-host" / ("bin.js" if damage == "missing-entry" else "LICENSE")).unlink()
  elif damage == "extra-file": (root / "unselected.js").write_text("// extra\n")
  elif damage.startswith("receipt-"):
    target = root / ".agentcfg-receipt.json"
    data = json.loads(target.read_text())
    if damage == "receipt-key": data["unrecognized"] = True
    else: data["manifest_digest"] = "0" * 64
    target.write_text(json.dumps(data))
  else:
    outside = tmp_path / "outside"
    outside.write_text("sentinel")
    (root / "escape").symlink_to(outside)
  assert status(root, identity) == "damaged"


def test_activation_failure_restores_previous_owned_package(staged_runtime, tmp_path, monkeypatch):
  from agentcfg import pi_runtime_packages
  root, identity, _, _ = staged_runtime
  final = tmp_path / "final"
  root.rename(final)
  replacement = tmp_path / "replacement"
  import shutil
  shutil.copytree(final, replacement)
  replacement.chmod(0o700)
  original = pi_runtime_packages.rename_directory
  def fail_new(source, destination):
    if source == replacement: raise OSError("synthetic activation interruption")
    return original(source, destination)
  monkeypatch.setattr(pi_runtime_packages, "rename_directory", fail_new)
  before = (final / "node_modules/fake-host/bin.js").read_bytes()
  with pytest.raises(OSError): pi_runtime_packages.activate(replacement, final, identity)
  assert (final / "node_modules/fake-host/bin.js").read_bytes() == before
  assert pi_runtime_packages.status(final, identity) == "installed"
  assert not (tmp_path / (".repair-" + identity)).exists()


def test_unknown_destination_is_never_adopted(staged_runtime, tmp_path):
  from agentcfg.pi_runtime_packages import activate
  root, identity, _, _ = staged_runtime
  final = tmp_path / "unknown"
  final.mkdir(mode=0o700)
  (final / "sentinel").write_text("keep")
  with pytest.raises(Conflict): activate(root, final, identity)
  assert (final / "sentinel").read_text() == "keep"


@pytest.mark.parametrize("damage", ["duplicate-key", "deep-json"])
def test_malformed_receipt_is_damaged_without_internal_error(staged_runtime, damage):
  from agentcfg.pi_runtime_packages import status
  root, identity, _, _ = staged_runtime
  path = root / ".agentcfg-receipt.json"
  if damage == "duplicate-key":
    path.write_text(path.read_text().strip()[:-1] + ',"identity":' + json.dumps(identity) + '}')
  else:
    path.write_text('[' * 2000 + '0' + ']' * 2000)
  assert status(root, identity) == "damaged"


@pytest.fixture
def recipe_repository(tmp_path):
  import shutil
  source = Path(__file__).resolve().parents[1]
  root = tmp_path / "recipe"
  # 机器锁会解析同一local的两个profile，假仓库也需完整的公开catalog元数据。
  metadata = [Path("agents/pi/dependencies.json"),
    Path("agents/omp/resources/themes/dark-catppuccin.json"),
    Path("agents/omp/resources/themes/light-catppuccin.json")]
  for directory in ("shared", "shared/defaults", "profiles", "agents/dsh", "agents/pi", "agents/omp"):
    metadata.extend(path.relative_to(source) for path in sorted((source / directory).glob("*.toml")))
  for name in metadata:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / name, target)
  for name in ("schemas", "agents/pi/schemas", "agents/pi/templates", "agents/pi/prompts", "agents/pi/licenses", "agents/pi/support", "shared/rules", "shared/skills/repo-navigation", "shared/skills/safe-linux-scripting", "shared/skills/playwright-cli"):
    shutil.copytree(source / name, root / name)
  return root


def test_recipe_digest_excludes_manager_other_profile_retired_sources_and_generated_locks(recipe_repository):
  from agentcfg.pi_dependencies import recipe_digest
  root = recipe_repository
  before = recipe_digest(root, "pi-base")
  for name in ("src/agentcfg/unrelated.py", "agents/pi/packages/retired/index.ts", "locks/pi/manifest.json"):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("unrelated synthetic mutation\n")
  (root / "profiles/pi-pro.toml").write_text('schema_version=1\nid="pi-pro"\nagent="pi"\n[agent_options.ui]\ntheme="catppuccin-frappe"\n')
  assert recipe_digest(root, "pi-base") == before


def test_recipe_digest_tracks_all_selected_skill_support_content(recipe_repository):
  from agentcfg.pi_dependencies import recipe_digest
  root = recipe_repository
  before = recipe_digest(root, "pi-base")
  target = root / "shared/skills/repo-navigation/support-synthetic.txt"
  target.write_text("new selected skill content\n")
  assert recipe_digest(root, "pi-base") != before


def test_recipe_digest_tracks_current_dependency_selection_but_not_ui(recipe_repository):
  from agentcfg.pi_dependencies import recipe_digest
  root = recipe_repository
  before = recipe_digest(root, "pi-base")
  profile = root / "profiles/pi-base.toml"
  profile.write_text(profile.read_text()+'\n[agent_options.ui]\ntheme="catppuccin-frappe"\n')
  assert recipe_digest(root, "pi-base") == before
  profile.write_text(profile.read_text()+'\n[agent_options.resources]\nprompts=[]\n')
  assert recipe_digest(root, "pi-base") != before


def test_recipe_digest_tracks_fixed_host_inputs_and_honest_null_commit(recipe_repository):
  from agentcfg.pi_dependencies import recipe_digest, read_recipe
  root = recipe_repository
  assert read_recipe(root)["host"]["source_commit"] is None
  before = recipe_digest(root, "pi-base")
  path = root / "agents/pi/dependencies.json"
  data = json.loads(path.read_text())
  data["host"]["version"] = "1.3.1"
  path.write_text(json.dumps(data))
  assert recipe_digest(root, "pi-base") != before


@pytest.fixture
def fake_npm(recipe_repository, monkeypatch):
  from agentcfg import pi_dependencies as backend_module
  # 假安装显式模拟首轮Linux；不能让CI所在OS冒充已准入原生平台。
  monkeypatch.setattr(backend_module, "platform_id", lambda: "linux-x86_64")
  root = recipe_repository
  path = root / "agents/pi/dependencies.json"
  recipe = json.loads(path.read_text())
  recipe["script_audits"] = {}
  recipe["module_script_audits"] = {name: {} for name in recipe["modules"]}
  path.write_text(json.dumps(recipe))
  calls = []
  def checked(argv, *, cwd, env):
    calls.append(tuple(argv))
    assert env["HOME"] != str(Path.home())
    npm_env = {key.lower(): value for key, value in env.items()}
    assert npm_env["npm_config_userconfig"] != npm_env["npm_config_globalconfig"]
    assert npm_env["npm_config_ignore_scripts"] == "true"
    if argv == ["node", "--version"]: return "v24.14.0"
    if argv == ["npm", "--version"]: return "11.9.0"
    if argv[:2] == ["npm", "install"]:
      assert "--package-lock-only" in argv and "--ignore-scripts" in argv
      package = json.loads((cwd / "package.json").read_text())
      sources = {item["package"]: item for item in (recipe["host"], *recipe["modules"].values())}
      records = {"": {"name": package["name"], "version": package["version"], "dependencies": package["dependencies"]}}
      for name in package["dependencies"]:
        source = sources[name]
        records["node_modules/" + name] = {key: source[key] for key in ("version", "resolved", "integrity", "license")}
      (cwd / "package-lock.json").write_text(json.dumps({"name": package["name"], "version": package["version"],
        "lockfileVersion": 3, "requires": True, "packages": records}))
      return ""
    if argv[:2] == ["npm", "ci"]:
      assert "--ignore-scripts" in argv
      lock = json.loads((cwd / "package-lock.json").read_text())
      sources = {item["package"]: item for item in (recipe["host"], *recipe["modules"].values())}
      for name, source in sources.items():
        if "node_modules/" + name not in lock["packages"]: continue
        target = cwd / "node_modules" / name
        target.mkdir(parents=True)
        (target / "package.json").write_text(json.dumps({"name": name, "version": source["version"], "license": source["license"]}))
        for entry in (*source["entries"], *source["license_files"]):
          item = target / entry
          item.parent.mkdir(parents=True, exist_ok=True)
          item.write_text("synthetic bytes; never execute\n")
      return ""
    if argv[:2] == ["npm", "ls"]: return "{}"
    pytest.fail("unexpected subprocess")
  monkeypatch.setattr(backend_module, "checked", checked)
  return root, backend_module.PiBackend(), calls


def synthetic_workspace(root, tmp_path, *, profile="pi-base", selection=None):
  import tomllib
  from agentcfg.merge import merge_layers
  agent = tomllib.loads((root / "agents/pi/agent.toml").read_text())
  public = tomllib.loads((root / f"profiles/{profile}.toml").read_text())
  data = merge_layers((("defaults", agent["defaults"]), ("profile", public))).data
  if selection:
    for key, value in selection.items():
      if key == "resources": data["agent_options"]["resources"] = value
      else: data[key] = value
  return SimpleNamespace(repository=root, profile=profile, agent="pi", resolved=SimpleNamespace(data={"profile": data}),
    instance=tmp_path / profile, state_root=tmp_path / "state" / profile,
    binding={"machine": "synthetic", "profile": profile, "local": "/synthetic/local.toml"})


def test_fake_npm_resolve_publish_sync_and_independent_profiles(fake_npm, tmp_path):
  from jsonschema import Draft202012Validator
  root, backend, calls = fake_npm
  lock = backend.resolve_lock(root)
  schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/pi-lock.schema.json").read_text())
  Draft202012Validator.check_schema(schema)
  Draft202012Validator(schema).validate(lock.metadata)
  assert backend.read_lock(root) == lock
  base = synthetic_workspace(root, tmp_path)
  pro = synthetic_workspace(root, tmp_path, profile="pi-pro")
  assert backend.runtime_identity(base, lock) != backend.runtime_identity(pro, lock)
  result = backend.sync(base, lock)
  assert result["installed"] is True
  assert backend.status(base, result["identity"]) == "installed"
  assert not pro.instance.exists()
  assert sum(command[:2] == ("npm", "ci") for command in calls) == 1
  assert backend.sync(base, lock)["installed"] is False


def test_external_license_notice_is_copied_without_changing_npm_host(fake_npm, tmp_path):
  from agentcfg.pi_dependencies import digest
  root, backend, _ = fake_npm
  lock = backend.resolve_lock(root)
  notice = lock.metadata["host"]["license_notices"][0]
  piece = lock.metadata["profiles"]["pi-base"]
  resolution = json.loads(lock.pairs["pi-base"][1])
  assert piece["closure_digest"] == digest({"resolution": resolution,
    "resources": piece["recipe_inputs"]["resources"], "license_notices": [notice]})
  workspace = synthetic_workspace(root, tmp_path)
  result = backend.sync(workspace, lock)
  runtime = backend.root(workspace, result["identity"])
  assert (runtime / notice["target_path"]).read_bytes() == (root / notice["source_path"]).read_bytes()
  assert digest((runtime / notice["target_path"]).read_bytes()) == notice["sha256"]
  assert notice["target_path"] in lock.metadata["profiles"]["pi-base"]["required_files"]
  assert not (runtime / "node_modules/@earendil-works/pi-coding-agent/LICENSE").exists()
  (runtime / notice["target_path"]).write_text("synthetic changed legal material")
  assert backend.status(workspace, result["identity"]) == "damaged"


def test_external_license_notice_hash_drift_refuses_existing_lock_without_install(fake_npm, tmp_path):
  root, backend, calls = fake_npm
  lock = backend.resolve_lock(root)
  notice = lock.metadata["host"]["license_notices"][0]
  before = list(calls)
  (root / notice["source_path"]).write_text("synthetic unreviewed license change")
  with pytest.raises(ConfigError):
    backend.read_lock(root)
  with pytest.raises(ConfigError):
    backend.sync(synthetic_workspace(root, tmp_path), lock)
  assert calls == before


@pytest.mark.parametrize("field,value", [
  ("source_path", "agents/pi/licenses/../outside"), ("source_path", "shared/LICENSE"),
  ("target_path", "node_modules/fake-host/LICENSE"), ("target_path", "licenses/../outside"),
  ("source_uri", "https://raw.githubusercontent.com/earendil-works/pi/main/LICENSE"),
  ("sha256", "0" * 64), ("unknown", "rejected")])
def test_license_notice_requires_fixed_source_paths_and_matching_bytes(recipe_repository, field, value):
  from agentcfg.pi_dependencies import read_recipe
  path = recipe_repository / "agents/pi/dependencies.json"
  recipe = json.loads(path.read_text())
  recipe["host"]["license_notices"][0][field] = value
  path.write_text(json.dumps(recipe))
  with pytest.raises(ConfigError):
    read_recipe(recipe_repository)


def test_source_cannot_omit_both_package_license_and_external_notice(recipe_repository):
  from agentcfg.pi_dependencies import read_recipe
  path = recipe_repository / "agents/pi/dependencies.json"
  recipe = json.loads(path.read_text())
  recipe["host"]["license_notices"] = []
  path.write_text(json.dumps(recipe))
  with pytest.raises(ConfigError):
    read_recipe(recipe_repository)


def test_reviewed_notice_body_and_descriptor_update_changes_recipe_identity(recipe_repository):
  from agentcfg.pi_dependencies import digest, recipe_digest, read_recipe
  before = recipe_digest(recipe_repository, "pi-base")
  path = recipe_repository / "agents/pi/dependencies.json"
  recipe = json.loads(path.read_text())
  notice = recipe["host"]["license_notices"][0]
  body = b"Synthetic separately reviewed license notice\n"
  (recipe_repository / notice["source_path"]).write_bytes(body)
  notice["sha256"] = digest(body)
  path.write_text(json.dumps(recipe))
  assert recipe_digest(recipe_repository, "pi-base") != before
  assert read_recipe(recipe_repository)["host"]["source_commit"] is None


def test_missing_pi_lock_is_configuration_error_without_resolution_or_instance_write(fake_npm):
  root, backend, calls = fake_npm
  with pytest.raises(ConfigError) as caught: backend.read_lock(root)
  assert caught.value.exit_code == 2
  assert calls == [] and not (root / "locks/pi").exists()


def test_current_profile_drift_fails_without_implicitly_resolving(fake_npm, tmp_path):
  root, backend, calls = fake_npm
  lock = backend.resolve_lock(root)
  workspace = synthetic_workspace(root, tmp_path, selection={"skills": []})
  count = len(calls)
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)
  with pytest.raises(ConfigError): backend.sync(workspace, lock)
  assert len(calls) == count and not workspace.instance.exists()


@pytest.mark.parametrize("damage", ["identity", "metadata", "pair"])
def test_sync_rejects_caller_forged_lock_before_install_or_instance_write(fake_npm, tmp_path, damage):
  from agentcfg.pi_dependencies import PiLock
  root, backend, calls = fake_npm
  lock = backend.resolve_lock(root)
  metadata, pairs = deepcopy(lock.metadata), deepcopy(lock.pairs)
  identity = lock.identity
  if damage == "identity":
    identity = "0" * 64
  elif damage == "metadata":
    metadata["profiles"]["pi-base"]["required_files"] = []
  else:
    pairs["pi-base"] = (b"{}", pairs["pi-base"][1])
  forged = PiLock(identity, metadata, pairs)
  workspace = synthetic_workspace(root, tmp_path)
  count = len(calls)
  with pytest.raises(ConfigError):
    backend.sync(workspace, forged)
  assert len(calls) == count
  assert not workspace.instance.exists() and not workspace.state_root.exists()


def test_unadmitted_platform_refuses_before_install_and_preserves_other_state(fake_npm, tmp_path, monkeypatch):
  from agentcfg import pi_dependencies
  from agentcfg.process import DependencyError
  root, backend, calls = fake_npm
  lock = backend.resolve_lock(root)
  workspace = synthetic_workspace(root, tmp_path)
  count = len(calls)
  monkeypatch.setattr(pi_dependencies, "platform_id", lambda: "darwin-arm64")
  with pytest.raises(DependencyError):
    backend.sync(workspace, lock)
  assert len(calls) == count and not workspace.instance.exists()


def test_other_profile_drift_does_not_invalidate_current_profile(fake_npm, tmp_path):
  root, backend, calls = fake_npm
  lock = backend.resolve_lock(root)
  base = synthetic_workspace(root, tmp_path)
  before = backend.runtime_identity(base, lock)
  with (root / "profiles/pi-pro.toml").open("a") as stream: stream.write('\n[agent_options.resources]\nprompts=[]\n')
  lock = backend.read_lock(root)
  assert backend.runtime_identity(base, lock) == before
  with pytest.raises(ConfigError): backend.runtime_identity(synthetic_workspace(root, tmp_path, profile="pi-pro"), lock)


def test_explicit_local_selection_lock_excludes_unselected_npm_module(fake_npm, tmp_path):
  root, backend, _ = fake_npm
  workspace = synthetic_workspace(root, tmp_path, selection={"skills": [], "resources": {"prompts": [], "themes": [], "extensions": []}})
  lock = backend.resolve_lock_for(workspace)
  assert backend.runtime_identity(workspace, lock)
  piece = lock.metadata["profiles"]["pi-base"]
  assert "catppuccin-pi-theme" not in piece["dependencies"]
  raw = lock.pairs["pi-base"][1]
  assert b"catppuccin-pi-theme" not in raw
  assert "catppuccin-pi-theme" in lock.metadata["profiles"]["pi-pro"]["dependencies"]


def test_sync_source_content_failure_does_not_replace_home_or_previous_runtime(fake_npm, tmp_path, monkeypatch):
  from agentcfg import pi_dependencies
  from agentcfg.process import DependencyError
  root, backend, _ = fake_npm
  lock = backend.resolve_lock(root)
  workspace = synthetic_workspace(root, tmp_path)
  home = workspace.instance / "pi-home"
  home.mkdir(parents=True)
  (home / "auth.json").write_text("SYNTHETIC_UNREAD_SENTINEL")
  original = pi_dependencies.checked
  def damaged(argv, **kwargs):
    result = original(argv, **kwargs)
    if argv[:2] == ["npm", "ci"]:
      target = kwargs["cwd"] / "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
      target.unlink()
    return result
  monkeypatch.setattr(pi_dependencies, "checked", damaged)
  with pytest.raises(DependencyError): backend.sync(workspace, lock)
  assert (home / "auth.json").read_text() == "SYNTHETIC_UNREAD_SENTINEL"
  assert backend.status(workspace, backend.runtime_identity(workspace, lock)) == "missing"


def test_reader_rejects_lock_directory_replacement_while_generation_is_leased(fake_npm, monkeypatch):
  import shutil
  from agentcfg import pi_dependencies
  root, backend, _ = fake_npm
  backend.resolve_lock(root)
  original = pi_dependencies.read_recipe
  replaced = []
  def replace_after_lease(repository):
    recipe = original(repository)
    if not replaced:
      directory = root / "locks/pi"
      old = root / "locks/renamed-generation"
      directory.rename(old)
      shutil.copytree(old, directory)
      replaced.append(True)
    return recipe
  monkeypatch.setattr(pi_dependencies, "read_recipe", replace_after_lease)
  with pytest.raises(Conflict): backend.read_lock(root)


@pytest.mark.parametrize("metadata,accepted", [({"optional": True}, True), ({"optional": False}, False), ({}, False)])
def test_metadata_only_peer_requires_explicit_optional_true(metadata, accepted):
  value = resolution()
  value["packages"]["node_modules/fake-host"]["peerDependenciesMeta"] = {"supports-color": metadata}
  if accepted:
    validate(value)
  else:
    with pytest.raises(ConfigError):
      validate(value)


@pytest.mark.parametrize("bundled,remove_sri", [("true", False), (1, False), (True, True), (False, True)])
def test_bundled_metadata_cannot_bypass_public_source_integrity(bundled, remove_sri):
  value = resolution()
  package = value["packages"]["node_modules/fake-child"]
  package["inBundle"] = bundled
  if remove_sri:
    del package["integrity"]
  with pytest.raises(ConfigError):
    validate(value)


@pytest.mark.parametrize("version", ["01.0.0", "1.00.0", "1.0.01"])
def test_exact_package_version_rejects_leading_zero_core(version):
  value = resolution()
  value["packages"]["node_modules/fake-child"]["version"] = version
  with pytest.raises(ConfigError):
    validate(value)



def content_type_resolution(version, paths):
  value = resolution()
  value["packages"]["node_modules/fake-host"]["dependencies"]["content-type"] = version
  if len(paths) > 1:
    value["packages"]["node_modules/fake-child"]["dependencies"] = {"content-type": version}
  for path in paths:
    value["packages"][path] = {"version": version,
      "resolved": f"https://registry.npmjs.org/content-type/-/content-type-{version}.tgz",
      "integrity": SRI, "license": "MIT"}
  validate(value)
  return value


def scoped_content_type_audit():
  return {"package_json_digest": "a" * 64, "lifecycle": {"prepare": "reviewed build"},
    "decision": "ignored_not_required", "package": "content-type", "version": "2.1.0"}


@pytest.mark.parametrize("paths", [["node_modules/content-type"],
  ["node_modules/fake-host/node_modules/content-type"],
  ["node_modules/content-type", "node_modules/fake-host/node_modules/content-type"]])
def test_version_qualified_audit_projects_exactly_to_all_resolved_paths(paths):
  from agentcfg.pi_dependencies import _resolution_audits
  audit = scoped_content_type_audit()
  catalog = {"node_modules/reviewed/node_modules/content-type": audit}
  before = deepcopy(catalog)
  projected = _resolution_audits(catalog, content_type_resolution("2.1.0", paths))
  expected = {key: audit[key] for key in ("package_json_digest", "lifecycle", "decision")}
  assert projected == {path: expected for path in paths}
  assert catalog == before
  projected[paths[0]]["lifecycle"]["prepare"] = "mutated output"
  assert catalog == before


def test_qualified_audit_does_not_attach_to_a_different_version_and_legacy_is_unchanged():
  from agentcfg.pi_dependencies import _resolution_audits
  value = content_type_resolution("1.0.5", ["node_modules/content-type"])
  assert _resolution_audits({"node_modules/content-type": scoped_content_type_audit()}, value) == {}
  legacy = {"node_modules/fake-host": {"package_json_digest": "b" * 64,
    "lifecycle": {}, "decision": "ignored_not_required"}}
  assert _resolution_audits(legacy, value) == legacy
  from agentcfg.deployment import json_bytes
  assert json_bytes(_resolution_audits(legacy, value)) == json_bytes(legacy)


@pytest.mark.parametrize("damage", ["missing-package", "missing-version", "invalid-package", "invalid-version", "unknown"])
def test_audit_qualifiers_require_strict_paired_name_and_version(damage):
  from agentcfg.pi_dependencies import _audits
  audit = scoped_content_type_audit()
  if damage == "missing-package": del audit["package"]
  elif damage == "missing-version": del audit["version"]
  elif damage == "invalid-package": audit["package"] = "../content-type"
  elif damage == "invalid-version": audit["version"] = "02.1.0"
  else: audit["unknown"] = True
  with pytest.raises(ValueError): _audits({"node_modules/content-type": audit})


@pytest.mark.parametrize("legacy", [False, True])
def test_conflicting_audit_sources_cannot_overwrite_a_resolved_path(legacy):
  from agentcfg.pi_dependencies import _resolution_audits
  audit = scoped_content_type_audit()
  other = deepcopy(audit)
  other["package_json_digest"] = "b" * 64
  if legacy:
    other = {key: other[key] for key in ("package_json_digest", "lifecycle", "decision")}
  catalog = {"node_modules/declared/node_modules/content-type": audit, "node_modules/content-type": other}
  with pytest.raises(ConfigError, match="audit-conflict"):
    _resolution_audits(catalog, content_type_resolution("2.1.0", ["node_modules/content-type"]))


def test_identical_qualified_sources_deduplicate_without_weakening_body_identity():
  from agentcfg.pi_dependencies import _resolution_audits
  audit = scoped_content_type_audit()
  catalog = {"node_modules/a/node_modules/content-type": audit,
    "node_modules/b/node_modules/content-type": deepcopy(audit)}
  projected = _resolution_audits(catalog, content_type_resolution("2.1.0", ["node_modules/content-type"]))
  assert projected == {"node_modules/content-type": {key: audit[key] for key in ("package_json_digest", "lifecycle", "decision")}}


def test_resolved_audit_mapping_is_verified_even_if_lock_identities_are_resealed(fake_npm):
  from agentcfg.pi_dependencies import digest
  root, backend, _ = fake_npm
  path = root / "agents/pi/dependencies.json"
  recipe = json.loads(path.read_text())
  recipe["script_audits"] = {"node_modules/reviewed/node_modules/host": {
    "package_json_digest": "a" * 64, "lifecycle": {}, "decision": "ignored_not_required",
    "package": recipe["host"]["package"], "version": recipe["host"]["version"]}}
  path.write_text(json.dumps(recipe))
  lock = backend.resolve_lock(root)
  host_path = "node_modules/" + recipe["host"]["package"]
  assert lock.metadata["profiles"]["pi-base"]["script_audits"] == {
    host_path: {"package_json_digest": "a" * 64, "lifecycle": {}, "decision": "ignored_not_required"}}
  assert backend.read_lock(root) == lock
  metadata = deepcopy(lock.metadata)
  piece = metadata["profiles"]["pi-base"]
  piece["script_audits"][host_path]["package_json_digest"] = "b" * 64
  piece["identity"] = digest({key: value for key, value in piece.items() if key != "identity"})
  metadata["identity"] = digest({key: value for key, value in metadata.items() if key != "identity"})
  (root / "locks/pi/manifest.json").write_text(json.dumps(metadata))
  with pytest.raises(ConfigError): backend.read_lock(root)



def test_projected_audit_still_requires_the_exact_installed_manifest(tmp_path):
  from agentcfg.pi_dependencies import _resolution_audits, digest, validate_installed_packages
  value = content_type_resolution("2.1.0", ["node_modules/content-type"])
  for path, record in value["packages"].items():
    if not path: continue
    target = tmp_path / path
    target.mkdir(parents=True)
    body = {"name": path.split("node_modules/")[-1], "version": record["version"]}
    if path == "node_modules/content-type": body["scripts"] = {"prepare": "reviewed build"}
    (target / "package.json").write_text(json.dumps(body))
  raw = (tmp_path / "node_modules/content-type/package.json").read_bytes()
  audit = scoped_content_type_audit()
  audit["package_json_digest"] = digest(raw)
  mapped = _resolution_audits({"node_modules/old/node_modules/content-type": audit}, value)
  validate_installed_packages(tmp_path, value, mapped)
  (tmp_path / "node_modules/content-type/package.json").write_bytes(raw + b" ")
  with pytest.raises(ConfigError, match="script-not-audited"):
    validate_installed_packages(tmp_path, value, mapped)
