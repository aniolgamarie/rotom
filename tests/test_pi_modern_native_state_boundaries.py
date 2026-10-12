"""实际Base和明确synthetic Full sibling的默认状态边界；不启动SDK/宿主。"""

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from agentcfg import runtime
from agentcfg.activity import ExecutionStore
from agentcfg.adapter import Ownership
from agentcfg.pi_dependencies import PiBackend
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree, ensure_private
from agentcfg.workspace import Workspace, load_workspace
from test_pi_adapter import ROOT
from test_pi_activity import make_store
from test_pi_capability_manifest import binding_repository
from test_pi_dependencies import fake_installer
from test_pi_modern_launch_contract import modern_data
from test_pi_profile_projection import resolved


def paired_workspaces(tmp_path):
  local = tmp_path / "native-state-local.toml"
  roots = {name:tmp_path / "machine" / name for name in ("instances_root", "state_root", "cache_root")}
  lines = ["schema_version=1", "[machine]", "id=\"synthetic-native-state\"", "[machine.paths]"]
  lines.extend(name + "=" + json.dumps(str(path)) for name,path in roots.items())
  lines.extend(["[overrides.providers.synthetic]", "protocol=\"openai-compatible\"", "auth_kind=\"api-key\"",
    "base_url=\"https://synthetic.invalid/v1\"", "credential_ref=\"secret:synthetic-unfilled\"",
    "[overrides.models.synthetic]", "provider=\"synthetic\"", "remote_id=\"synthetic-model\"", "input=[\"text\"]"])
  actual = resolved(profile="pi-base")
  # 普通选择按现有规则合并；所有保留选择也使用虚构端点/远端model，不借真实默认值。
  for name in actual["providers"]:
    lines.extend(["[overrides.providers." + name + "]",
      "base_url=\"https://synthetic-" + name.replace("_", "-") + ".invalid/v1\"",
      "credential_ref=\"secret:synthetic-unfilled-" + name + "\""])
  for name in actual["models"]:
    lines.extend(["[overrides.models." + name + "]", "remote_id=\"synthetic-" + name + "\""])
  lines.extend(["[overrides.profiles.pi-base]", "providers=[\"synthetic\"]", "models=[\"synthetic\"]",
    "[overrides.profiles.pi-base.roles]"])
  lines.extend(role + "=\"synthetic\"" for role in actual["profile"]["roles"])
  local.write_text("\n".join(lines) + "\n")
  base = load_workspace(local, profile="pi-base", repository=ROOT)
  # 公共catalog确实没有Full；不添加声明，不把synthetic sibling当实际Full解析。
  with pytest.raises(ConfigError): load_workspace(local, profile="pi-full", repository=ROOT)
  full_data = modern_data("pi-full")
  for key in ("machine", "providers", "models"):
    full_data[key] = deepcopy(base.resolved.data[key])
  for key in ("providers", "models", "roles"):
    full_data["profile"][key] = deepcopy(base.resolved.data["profile"][key])
  full = Workspace(ROOT, base.local_path, SimpleNamespace(data=full_data), base.adapter,
    base.schemas, base.secret_store)
  workspaces = {"pi-base":base, "pi-full":full}
  for workspace in workspaces.values():
    assert all(".invalid/" in provider["base_url"] for provider in workspace.resolved.data["providers"].values())
    assert all(model["remote_id"].startswith("synthetic-") for model in workspace.resolved.data["models"].values())
    workspace.adapter.prepare_runtime(workspace, tmp_path / "never-executed-package")
    ensure_private(workspace.state_root)
  return workspaces, roots


def write_sentinels(workspaces):
  sentinels = {}
  for profile,workspace in workspaces.items():
    home = workspace.instance / "pi-home"
    paths = {"auth":home / "auth.json", "session":home / "sessions/default-fixture.jsonl"}
    for kind,path in paths.items():
      # 普通状态占位符不是凭据，不使用token/APIkey/账号字段或摘要。
      body = json.dumps({"fixture":profile + "-" + kind}).encode() + b"\n"
      fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
      with os.fdopen(fd, "wb") as stream: stream.write(body)
    sentinels[profile] = {**paths, "pi_home":home, "sessions":home / "sessions", "user_home":workspace.instance / "user-home"}
  return sentinels


def snapshot(paths):
  result = {}
  for name,path in paths.items():
    info = path.lstat()
    assert info.st_uid == os.geteuid() and info.st_nlink >= 1
    expected_mode = 0o700 if stat.S_ISDIR(info.st_mode) else 0o600
    assert stat.S_IMODE(info.st_mode) == expected_mode
    result[name] = {"identity":(info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_size, info.st_nlink,
      info.st_mtime_ns, info.st_ctime_ns), "bytes":None if stat.S_ISDIR(info.st_mode) else path.read_bytes()}
  return result


def synthetic_base_package(tmp_path, monkeypatch, base):
  fixture, _manifest = binding_repository(tmp_path / "synthetic-lock")
  # 原绑定fixture的合成native current slice只测试包机制；不冒充实际Base提供者闭包。
  fixture.instance = base.instance; fixture.state_root = base.state_root; fixture.binding = base.binding
  calls = []
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  backend = PiBackend(profile="pi-base")
  lock = backend.read_lock(fixture.repository)
  assert set(lock.pairs) == {"pi-base"} and lock.validated_bindings["pi-base"].state == "current"
  return fixture, backend, lock, calls


def test_actual_base_and_synthetic_full_sibling_keep_workspace_state_and_launch_homes_separate(tmp_path):
  workspaces, roots = paired_workspaces(tmp_path)
  base, full = (workspaces[profile] for profile in ("pi-base", "pi-full"))
  assert base.local_path == full.local_path and base.resolved.data["machine"] == full.resolved.data["machine"]
  assert base.instance == roots["instances_root"] / "pi/pi-base"
  assert full.instance == roots["instances_root"] / "pi/pi-full"
  assert base.state_root == roots["state_root"] / "pi/pi-base"
  assert full.state_root == roots["state_root"] / "pi/pi-full"
  assert base.instance != full.instance and base.state_root != full.state_root and base.cache != full.cache
  assert base.resolved.data["profile"]["plugins"] == ["pi-todo", "loop-guard", "colorful-footer"]
  assert not {"model-delegate", "pi-subagents", "pi-cursor", "task-keeper"} & set(base.resolved.data["plugins"])
  for profile,workspace in workspaces.items():
    spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=tmp_path,
      runtime_root=tmp_path / "package" / profile, instance_root=workspace.instance, lock_identity="a" * 64)
    env = {binding.name:binding.value for binding in spec.environment}
    assert env["HOME"] == str(workspace.instance / "user-home")
    assert env["PI_CODING_AGENT_DIR"] == str(workspace.instance / "pi-home")
    assert env["PI_CODING_AGENT_SESSION_DIR"] == str(workspace.instance / "pi-home/sessions")
    assert spec.argv[2] == str(tmp_path / "package" / profile / "runtime/official-launch.mjs")
    assert env["HOME"] != os.environ["HOME"]


def test_prepare_runtime_preserves_native_owned_content_permissions_and_profile_identity(tmp_path):
  workspaces, _ = paired_workspaces(tmp_path); sentinels = write_sentinels(workspaces)
  before = {profile:snapshot(paths) for profile,paths in sentinels.items()}
  rendered = {}
  for profile,workspace in workspaces.items():
    data_before = deepcopy(workspace.resolved.data)
    workspace.adapter.prepare_runtime(workspace, tmp_path / "unexecuted-package")
    targets = {target.path:target for target in workspace.adapter.managed_targets(workspace.resolved.data)}
    assert targets["pi-home/auth.json"].ownership is Ownership.RUNTIME
    assert targets["pi-home/sessions"].ownership is Ownership.RUNTIME
    artifacts = workspace.adapter.render(workspace.resolved.data)
    rendered[profile] = tuple((item.target.path, item.content) for item in artifacts)
    assert not {"pi-home/auth.json", "pi-home/sessions"} & {item.target.path for item in artifacts}
    assert workspace.resolved.data == data_before
  assert {profile:snapshot(paths) for profile,paths in sentinels.items()} == before
  sentinels["pi-base"]["session"].write_bytes(b"Synthetic Base session event\n")
  base_changed = snapshot(sentinels["pi-base"])
  assert snapshot(sentinels["pi-full"]) == before["pi-full"]
  sentinels["pi-full"]["session"].write_bytes(b"Synthetic Full sibling session event\n")
  assert snapshot(sentinels["pi-base"]) == base_changed
  for profile,workspace in workspaces.items():
    assert tuple((item.target.path, item.content) for item in workspace.adapter.render(workspace.resolved.data)) == rendered[profile]


def test_base_current_fake_package_reinstall_and_failed_repair_preserve_both_native_states(tmp_path, monkeypatch):
  workspaces, _ = paired_workspaces(tmp_path); sentinels = write_sentinels(workspaces)
  before = {profile:snapshot(paths) for profile,paths in sentinels.items()}
  fixture, backend, lock, calls = synthetic_base_package(tmp_path, monkeypatch, workspaces["pi-base"])
  result = backend.sync(fixture, lock); assert result["installed"] is True and len(calls) == 3
  root = backend.root(fixture, result["identity"])
  assert root.parent == workspaces["pi-base"].instance / "runtimes"
  assert not (workspaces["pi-full"].instance / "runtimes").exists()
  assert not (root / "pi-full").exists() and not (root / "vendor/full.tgz").exists()
  assert not (root / "install-home").exists()
  assert backend.sync(fixture, lock)["installed"] is False and len(calls) == 3
  target = root / lock.metadata["profile_slices"]["pi-base"]["entrypoint"]
  target.write_bytes(b"Synthetic package drift; never execute\n")
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls, fail=True))
  with pytest.raises(DependencyError):
    backend.sync(fixture, lock)
  assert target.read_bytes() == b"Synthetic package drift; never execute\n"
  assert {profile:snapshot(paths) for profile,paths in sentinels.items()} == before
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  assert backend.sync(fixture, lock)["installed"] is True
  assert backend.status(fixture, result["identity"]) == "installed" and not (root / "install-home").exists()
  assert {profile:snapshot(paths) for profile,paths in sentinels.items()} == before


@pytest.mark.parametrize("fault", ["recipe", "runtime-source"])
def test_stale_base_source_or_recipe_refuses_normal_sync_before_installer(tmp_path, monkeypatch, fault):
  workspaces, _ = paired_workspaces(tmp_path); sentinels = write_sentinels(workspaces)
  before = {profile:snapshot(paths) for profile,paths in sentinels.items()}
  fixture, backend, lock, calls = synthetic_base_package(tmp_path, monkeypatch, workspaces["pi-base"])
  if fault == "recipe":
    (fixture.repository / "agents/pi/dependencies-modern.json").write_bytes(b"Synthetic changed declaration\n")
  else:
    source = lock.metadata["profile_slices"]["pi-base"]["runtime_files"][0]["source"]
    (fixture.repository / source).write_bytes(b"Synthetic runtime source drift\n")
  with pytest.raises(ConfigError, match="pi-lock-missing-or-stale"):
    backend.sync(fixture, backend.read_lock(fixture.repository))
  assert calls == [] and not (workspaces["pi-base"].instance / "runtimes").exists()
  assert {profile:snapshot(paths) for profile,paths in sentinels.items()} == before


@pytest.mark.parametrize("operation", ["run", "sync"])
@pytest.mark.parametrize("condition", ["pending", "protected-activity-ledger"])
def test_normal_pending_or_protected_activity_blocks_native_preparation_launch_and_install(tmp_path, monkeypatch, fake_subprocess, operation, condition):
  workspaces, _ = paired_workspaces(tmp_path); base = workspaces["pi-base"]; sentinels = write_sentinels(workspaces)
  before = {profile:snapshot(paths) for profile,paths in sentinels.items()}
  fixture, backend, lock, calls = synthetic_base_package(tmp_path, monkeypatch, base)
  # 正常绑定先就绪；后续拒绝不被首次instance marker初始化的写入混淆。
  with base.adapter.lifecycle_guard(base): pass
  if condition == "pending":
    with Tree(base.state_root) as tree: tree.write_state("pending.json", b"{\"fixture\":\"default pending presence\"}\n")
  else:
    template, processes = make_store(tmp_path / "owner-fixture")
    store = ExecutionStore(base.state_root, template.owner, processes, now=template.now)
    lease = store.allocate(kind="worker", execution_id="native-state-default", task_id="synthetic", attempt_id="one",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64, planned_workspaces=[])
    assert lease["state"] == "allocating" and processes.signals == []
  preparation = []
  monkeypatch.setattr(base.adapter, "prepare_runtime", lambda *_: preparation.append("unexpected"))
  with pytest.raises(Conflict):
    if operation == "run":
      runtime.run(base, cwd=tmp_path, launch_operation=lambda *_args, **_kwargs: pytest.fail("unexpected host launch"))
    else: backend.sync(fixture, lock)
  assert preparation == [] and calls == [] and fake_subprocess.calls == []
  assert not (base.instance / "runtimes").exists()
  assert {profile:snapshot(paths) for profile,paths in sentinels.items()} == before
  # 此处是真实durable ledger门控，不是活进程flock竞争、namespace退出或T014验收。
