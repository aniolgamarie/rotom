"""浏览器候选的固定受管入口；假npm/exec，不启动CLI或浏览器。"""

import importlib.util
import hashlib
import json
from pathlib import Path
import re

import pytest

from agentcfg import runtime
from agentcfg.pi_dependencies import dependency_selection, recipe_inputs
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from agentcfg.workspace import load_workspace
from test_pi_optional_modules import module_workspace, selected_local
from test_pi_reboot_configuration import local, REPOSITORY
from test_pi_reboot_dependencies import fake_npm, recipe_repository, synthetic_workspace


def launcher():
  spec = importlib.util.spec_from_file_location("test_owned_browser_launcher", REPOSITORY / "agents/pi/support/browser-launch.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_public_browser_skill_selects_only_current_slice_and_owned_wrapper(module_workspace, tmp_path):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(skills=["playwright-cli"])
  piece = lock.metadata["profiles"]["pi-base"]
  assert piece["dependencies"]["@playwright/cli"] == "0.1.22"
  assert "@playwright/cli" not in lock.metadata["profiles"]["pi-pro"]["dependencies"]
  from jsonschema import Draft202012Validator
  Draft202012Validator(json.loads((REPOSITORY / "schemas/pi-lock.schema.json").read_text())).validate(lock.metadata)
  root = backend.root(workspace, backend.runtime_identity(workspace, lock))
  assert (root / "support/browser-launch.py").stat().st_mode & 0o777 == 0o600
  wrapper = workspace.instance / "pi-home/bin/playwright-cli"
  assert wrapper.stat().st_mode & 0o777 == 0o700
  body = wrapper.read_text()
  assert "runpy.run_path" in body and str(root / "support/browser-launch.py") in body
  assert str(workspace.instance / "pi-browser") in body and "os.environ" not in body
  assert runtime.run(workspace, cwd=tmp_path) == 19
  assert runtime.run(workspace, cwd=tmp_path) == 19
  sessions = [kwargs["env"]["AGENTCFG_PI_BROWSER_SESSION"] for _, kwargs in launched]
  assert all(re.fullmatch(r"[a-f0-9]{32}", value) for value in sessions) and sessions[0] != sessions[1]
  assert all(kwargs["env"]["PATH"].startswith(str(wrapper.parent) + ":") for _, kwargs in launched)
  feature = workspace.adapter.feature_readiness(workspace.resolved.data)["optional_modules"]
  assert feature["status"] == "not_verified" and "playwright-cli" in feature["selected"]
  assert not any((workspace.instance / "pi-browser/browsers").iterdir())


def test_complete_upstream_skill_and_ten_guides_license_are_preserved():
  source = REPOSITORY / "shared/skills/playwright-cli"
  # 精确0.1.22 tarball的原始正文身份；测试不依赖维护机器的审包缓存。
  expected = {
    "LICENSE": "9a7110fc2d2f964038e5dc49128f908f29f47a574c961cba16085914e879cbda",
    "upstream/references/element-attributes.md": "bf19aa4671e0a50a0fefa9c790f39124e803060eefe395042b723c29fcb7faa2",
    "upstream/references/playwright-tests.md": "c5b0719fef2cfdff50bd744051b2f9afc119775db4b48e9b2882c1cf3886797c",
    "upstream/references/pr-attachments.md": "24b118e74598be72e73e24fe223d295b9099c85b1860a7c8f6e5690c9038fa2a",
    "upstream/references/request-mocking.md": "54e801c9663fc2b6d68ceb058cb1c360724c2499f42acc7852a68e83e5b5f37c",
    "upstream/references/running-code.md": "3029569ed6ddaeffc0b87badde967efdc2973b1677f078830098146eb3b78ebe",
    "upstream/references/session-management.md": "a4f16271f95d3eec7bc56e659d8adbb8f6ad7d603a6fa15efdcdd071a50c6ce3",
    "upstream/references/storage-state.md": "9ac47f9ae4a1aedcd2077f8ac9ab1ba6bee1962cb83ff51adcd36fb6d83b5ec6",
    "upstream/references/test-generation.md": "27ecb11ef647999bd7486695bb1aacc3682097e6bb5742804cb6c8769c2b5364",
    "upstream/references/tracing.md": "ef73e71bee792e341df9cd4f60529c929ade48b538ac76e033f4f20843e8dbda",
    "upstream/references/video-recording.md": "1c800b897824cb54394c34265d8ebffdbb530adfc8d612c5d798b667a1799f48",
    "upstream/SKILL.md": "9bba755285a4c9ad72a4a41b9c7baef6fb516d329c0b44ed0573715f4479b906"
  }
  assert len([name for name in expected if "/references/" in name]) == 10
  for name, identity in expected.items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == identity
  entry = (source / "SKILL.md").read_text()
  assert "name: playwright-cli" in entry and "npx" in entry and "用户明确" in entry


def test_unselected_browser_has_no_loading_support_path_or_environment(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  inputs = recipe_inputs(REPOSITORY, "pi-base", dependency_selection(workspace.resolved.data))
  assert "playwright-cli" not in inputs["modules"]
  assert not any(item.get("id") == "pi-browser-launch" for item in inputs["resources"])
  assert not any(target.path.startswith("pi-home/bin") for target in workspace.adapter.managed_targets(workspace.resolved.data))
  env = {"PATH": "/synthetic/bin", "AGENTCFG_PI_BROWSER_SESSION": "a" * 32, "PLAYWRIGHT_CLI_SESSION": "foreign"}
  result = workspace.adapter.adjust_launch_environment(workspace, None, env, None)
  assert result == {"PATH": "/synthetic/bin"}
  assert not workspace.instance.exists()


@pytest.mark.parametrize("source", ["agents/pi/support/browser-launch.py", "shared/skills/playwright-cli/upstream/references/tracing.md"])
def test_browser_source_drift_only_invalidates_selected_slice(module_workspace, tmp_path, source):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(skills=["playwright-cli"])
  pro = synthetic_workspace(workspace.repository, tmp_path, profile="pi-pro")
  before = backend.runtime_identity(pro, lock)
  path = workspace.repository / source
  path.write_bytes(path.read_bytes() + b"\n")
  assert backend.read_lock(workspace.repository) == lock
  assert backend.runtime_identity(pro, lock) == before
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)


@pytest.mark.parametrize("arguments", [["attach", "chrome"], ["install"], ["install-browser"], ["close-all"], ["kill-all"],
  ["open", "--persistent"], ["open", "--profile=/synthetic/profile"], ["open", "--config=custom.json"],
  ["-s=foreign", "open"], ["open", "--session", "foreign"], ["open", "--browser=chrome"],
  ["open", "--browser=chromium"], ["open", "--browser", "chromium"], ["show"], ["unknown"], ["open", "--unknown"]])
def test_wrapper_rejects_unknown_or_ownership_bypassing_arguments(arguments):
  with pytest.raises(ValueError): launcher().validate_arguments(arguments)


@pytest.mark.parametrize("arguments,expected", [
  (["open", "https://example.invalid"], ["open", "https://example.invalid", "--browser=chromium"]),
  (["--json", "--raw", "open"], ["--json", "--raw", "open", "--browser=chromium"]),
  (["snapshot"], ["snapshot"]), (["close"], ["close"]),
  (["--help"], ["--help"]), (["--version"], ["--version"]),
])
def test_fake_exec_keeps_fixed_private_identity_and_service_scoped_environment(module_workspace, tmp_path, monkeypatch, arguments, expected):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(skills=["playwright-cli"])
  root = backend.root(workspace, backend.runtime_identity(workspace, lock))
  module = launcher()
  module.RUNTIME_ROOT = str(root)
  module.BROWSER_ROOT = str(workspace.instance / "pi-browser")
  monkeypatch.setattr(module.sys, "argv", ["playwright-cli", *arguments])
  monkeypatch.setenv("AGENTCFG_PI_BROWSER_SESSION", "a" * 32)
  monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC_MODEL_SENTINEL")
  monkeypatch.setenv("BRAVE_API_KEY", "SYNTHETIC_SEARCH_SENTINEL")
  monkeypatch.setenv("NODE_OPTIONS", "--synthetic-forbidden")
  monkeypatch.setenv("PLAYWRIGHT_CLI_SESSION", "foreign")
  monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/synthetic/foreign")
  executed = []
  monkeypatch.setattr(module.os, "execvpe", lambda *args: executed.append(args))
  before_cwd = Path.cwd()
  try:
    assert module.main() == 0
  finally:
    module.os.chdir(before_cwd)
  executable, argv, env = executed[0]
  assert executable == "node" and argv[1] == str(root / "node_modules/@playwright/cli/playwright-cli.js")
  assert argv[2:] == expected
  assert sum(arg.startswith("--browser") for arg in argv) == int("open" in arguments)
  assert env["PLAYWRIGHT_CLI_SESSION"] == "a" * 32 and env["NO_UPDATE_NOTIFIER"] == "1"
  assert env["HOME"] == str(workspace.instance / "pi-browser/home")
  assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(workspace.instance / "pi-browser/browsers")
  assert not {"NODE_OPTIONS", "OPENAI_API_KEY", "BRAVE_API_KEY", "AGENTCFG_PI_BROWSER_SESSION"} & env.keys()
  assert module.validate_arguments(["snapshot"]) == ["snapshot"]


@pytest.mark.parametrize("damage", ["wrapper", "extra-bin"])
def test_managed_bin_integrity_refuses_drift_before_fake_cli(module_workspace, tmp_path, damage):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(skills=["playwright-cli"])
  directory = workspace.instance / "pi-home/bin"
  (directory / ("playwright-cli" if damage == "wrapper" else "unmanaged")).write_text("synthetic changed")
  with pytest.raises(Conflict): runtime.run(workspace, cwd=tmp_path)
  assert not launched


def test_unselected_browser_support_and_skill_mutation_leave_default_identity(module_workspace):
  make, backend, calls, launched = module_workspace
  workspace, lock = make()
  before = backend.runtime_identity(workspace, lock)
  for name in ("agents/pi/support/browser-launch.py", "shared/skills/playwright-cli/upstream/references/tracing.md"):
    path = workspace.repository / name
    path.write_bytes(path.read_bytes() + b"\n")
  assert backend.read_lock(workspace.repository) == lock
  assert backend.runtime_identity(workspace, lock) == before


def test_disabling_browser_preserves_private_state_and_does_not_remove_unknown_bin(module_workspace, tmp_path):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(skills=["playwright-cli"])
  state = workspace.instance / "pi-browser/cache/private-sentinel"
  state.write_text("SYNTHETIC_BROWSER_STATE")
  extra = workspace.instance / "pi-home/bin/unmanaged"
  extra.write_text("SYNTHETIC_UNMANAGED_FILE")
  before = {path: (path.read_bytes(), path.stat().st_ino) for path in (state, extra)}
  workspace, lock = make(skills=[])
  assert not (workspace.instance / "pi-home/bin/playwright-cli").exists()
  assert before == {path: (path.read_bytes(), path.stat().st_ino) for path in (state, extra)}
  assert runtime.run(workspace, cwd=tmp_path) == 19
  env = launched[0][1]["env"]
  assert "AGENTCFG_PI_BROWSER_SESSION" not in env
  assert not env["PATH"].startswith(str(extra.parent) + ":")


def test_browser_session_and_path_override_cannot_be_inherited(tmp_path):
  from agentcfg.config import validate_environment_settings
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  policy = workspace.schemas.bundles["pi"].policy(workspace.resolved.data["adapter_documents"])
  with pytest.raises(ConfigError):
    validate_environment_settings({"inherit": ["AGENTCFG_PI_BROWSER_SESSION"], "unset": []},
      policy.credential_targets, reserved_environment=policy.reserved_environment)
  module = launcher()
  with pytest.raises(ValueError): module.browser_environment(tmp_path, {"AGENTCFG_PI_BROWSER_SESSION": "foreign"})
  env = module.browser_environment(tmp_path, {"AGENTCFG_PI_BROWSER_SESSION": "a" * 32, "PATH": "/synthetic/bin"})
  assert module.browser_environment(tmp_path, {"AGENTCFG_PI_BROWSER_SESSION": "a" * 32})["PLAYWRIGHT_CLI_SESSION"] == env["PLAYWRIGHT_CLI_SESSION"]


@pytest.mark.parametrize("location,damage", [("cwd", "file"), ("home", "file"), ("cwd", "config-link"),
  ("home", "config-link"), ("cwd", "marker-link"), ("cwd", "marker-file"), ("cwd", "marker-missing")])
def test_implicit_custom_browser_config_is_refused_without_body_read_or_deletion(module_workspace, monkeypatch, location, damage):
  make, backend, calls, launched = module_workspace
  workspace, lock = make(skills=["playwright-cli"])
  root = backend.root(workspace, backend.runtime_identity(workspace, lock))
  base = workspace.instance / "pi-browser"
  marker = base / location / ".playwright"
  if not marker.exists(): marker.mkdir(mode=0o700)
  unknown = base / "private-unmanaged"
  unknown.write_text("SYNTHETIC_UNREAD_BROWSER_CONFIGURATION")
  if damage == "marker-link":
    marker.rmdir()
    marker.symlink_to(unknown.parent, target_is_directory=True)
  elif damage == "marker-file":
    marker.rmdir()
    marker.write_text("SYNTHETIC_UNREAD_MARKER")
  elif damage == "marker-missing": marker.rmdir()
  elif damage == "config-link": (marker / "cli.config.json").symlink_to(unknown)
  else: (marker / "cli.config.json").write_text("SYNTHETIC_UNREAD_BROWSER_CONFIGURATION")
  module = launcher()
  module.RUNTIME_ROOT, module.BROWSER_ROOT = str(root), str(base)
  monkeypatch.setattr(module.sys, "argv", ["playwright-cli", "open"])
  monkeypatch.setenv("AGENTCFG_PI_BROWSER_SESSION", "b" * 32)
  original_open = module.os.open
  def no_config_read(path, *args, **kwargs):
    assert str(path) not in ("cli.config.json", str(unknown))
    return original_open(path, *args, **kwargs)
  monkeypatch.setattr(module.os, "open", no_config_read)
  monkeypatch.setattr(module.os, "execvpe", lambda *args: pytest.fail("custom config不得进入CLI"))
  assert module.main() == 4
  assert unknown.exists()
  if damage in ("file", "config-link"): assert (marker / "cli.config.json").exists()
