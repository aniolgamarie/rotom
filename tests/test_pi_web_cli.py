"""联网媒体的命令、准入及驱动使用假进程/假 socket；默认不执行第三方工具。"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.pi_web_cli import media_arguments
from agentcfg.pi_checks import linux_verifier_argv, macos_verifier_policy
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_web_media import setup as media_setup
from test_pi_activity import identity


def setup(tmp_path, monkeypatch):
  operations, host, cwd, principal, _ = media_setup(tmp_path)
  manifest = host.manifest()
  manifest["web_services"] = {"public": {"type": "public", "network_route": "direct"}}
  manifest["options"]["web"]["media"].update(yt_dlp_tool_ref="ffmpeg", javascript_tool_ref="ffmpeg")
  base = host.runtime_root / "supervisor"
  (base / "scripts").mkdir(parents=True, exist_ok=True)
  (base / "src/agentcfg").mkdir(parents=True, exist_ok=True)
  (base / "scripts/pi-web-cli.py").write_text("synthetic driver, never run")
  (base / "src/agentcfg/pi_web_relay.py").write_text("synthetic relay, never run")
  # 路径来自测试专属目录；socket 类型/身份以替身返回，不建立真实监听。
  path = tmp_path / "ipc/proxy.sock"; path.parent.mkdir(mode=0o700); path.write_bytes(b"fake socket")
  monkeypatch.setattr("agentcfg.pi_web_cli.socket_snapshot", lambda path: {"path": str(path), "device": 1, "inode": 2})
  args = {"operation_id": "network-media", "operation": "youtube-info", "input": {"video_id": "abcdefghijk"}, "socket_path": str(path), "token": "a" * 64}
  return operations, host, principal, args


def test_fixed_media_flags_exclude_global_config_plugins_and_other_protocols():
  argv = media_arguments("youtube-info", {"video_id": "abcdefghijk"}, javascript=Path("/tools/node"))
  for flag in ("--ignore-config", "--no-plugin-dirs", "--no-js-runtimes", "--no-remote-components", "--proxy"): assert flag in argv
  assert "node:/tools/node" in argv and argv[-1] == "https://www.youtube.com/watch?v=abcdefghijk"
  frame = media_arguments("remote-frame", {"url": "https://media.invalid/video?signature=synthetic", "seconds": 1.5})
  assert "https,tls,tcp,httpproxy" in frame and "AGENTCFG_WEB_PROXY" in frame
  for payload in ({"url": "file:///private", "seconds": 1}, {"url": "https://u:p@media.invalid/a", "seconds": 1}, {"url": "https://media.invalid/a", "seconds": True}):
    with pytest.raises(ConfigError): media_arguments("remote-frame", payload)
  with pytest.raises(ConfigError): media_arguments("youtube-info", {"video_id": "--exec=bad"}, javascript="/tools/node")


def test_cli_job_has_isolated_network_explicit_loopback_and_private_input(tmp_path, monkeypatch):
  operations, host, principal, args = setup(tmp_path, monkeypatch)
  ticket = operations.handle(principal, "ordinary_web_cli_prepare", args)
  row = operations.commands.records[ticket["operation_id"]]; check = row["check"]
  assert check["network"] == "none" and check["write_roots"] == []
  assert operations.handle(principal, "ordinary_web_cli_prepare", args) == ticket
  native = linux_verifier_argv(check, temporary=tmp_path / "scratch", system_roots=())
  assert "--unshare-all" in native and "--share-net" not in native
  policy = macos_verifier_policy(check, temporary=tmp_path / "scratch")
  assert '(remote ip "127.0.0.1:' + str(check["web_cli_port"]) + '")' in policy
  assert '(remote ip "*' not in policy
  assert args["token"] not in json.dumps(ticket)
  assert operations.handle(principal, "ordinary_web_cli_authorize", {"operation_id": ticket["operation_id"]}) == {"valid": False, "revoked": False}
  host.store.processes.current[203] = identity(203)
  host.store.start(ticket["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  assert operations.handle(principal, "ordinary_web_cli_authorize", {"operation_id": ticket["operation_id"]}) == {"valid": True, "revoked": False}
  host.store.request_cancel(ticket["lease_id"], host.store.owner)
  assert operations.handle(principal, "ordinary_web_cli_authorize", {"operation_id": ticket["operation_id"]}) == {"valid": False, "revoked": True}
  with pytest.raises(Conflict, match="TERMINATION_UNKNOWN"):
    operations.handle(principal, "ordinary_command_finish", {"operation_id": ticket["operation_id"]})


def test_unstarted_job_cleanup_and_permission_denial(tmp_path, monkeypatch):
  operations, host, principal, args = setup(tmp_path, monkeypatch)
  ticket = operations.handle(principal, "ordinary_web_cli_prepare", args)
  directory = Path(operations.commands.records[ticket["operation_id"]]["check"]["cwd"])
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  operations.handle(principal, "ordinary_command_finish", {"operation_id": ticket["operation_id"]})
  assert not directory.exists()
  host.manifest()["permission_policy"]["rules"][-1]["effect"] = "deny"
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    operations.handle(principal, "ordinary_web_cli_prepare", {**args, "operation_id": "denied"})


def test_restart_reclaims_private_cli_inputs_only_after_lease_is_unprotected(tmp_path, monkeypatch):
  from datetime import datetime, timedelta, timezone
  from agentcfg.pi_web_cli import reclaim
  operations, host, principal, args = setup(tmp_path, monkeypatch)
  ticket = operations.handle(principal, "ordinary_web_cli_prepare", args)
  directory = Path(operations.commands.records[ticket["operation_id"]]["check"]["cwd"])
  operations.commands.records.clear()
  now = datetime.now(timezone.utc) + timedelta(seconds=4000)
  reclaim(operations, now=now)
  assert (directory / "input.json").exists()
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  reclaim(operations, now=now)
  assert not directory.exists()


def test_cli_driver_starts_relay_before_child_and_does_not_inherit_credentials(monkeypatch):
  path = Path(__file__).resolve().parents[1] / "scripts/pi-web-cli.py"
  spec = importlib.util.spec_from_file_location("web_cli_test_driver", path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  events = []; calls = []
  monkeypatch.setenv("AMBIENT_SECRET", "must-not-pass")
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_CAPABILITY", "must-not-pass")
  class Relay:
    def __init__(self, path, port): pass
    def start(self): events.append("relay-start")
    def poll(self, timeout): events.append("poll")
    def close(self): events.append("relay-close")
  class Child:
    returncode = 0
    def poll(self): return 0
  def popen(argv, **kwargs):
    events.append("child-start"); calls.append((argv, kwargs)); return Child()
  document = {"argv": ["/tools/yt-dlp", "--proxy", "AGENTCFG_WEB_PROXY"], "socket_path": "/private/proxy.sock", "port": 41234, "token": "a" * 64, "timeout_seconds": 30, "github_authorization": "Basic synthetic-github"}
  assert module.execute(document, relay_factory=Relay, popen=popen) == 0
  assert events == ["relay-start", "child-start", "relay-close"]
  env = calls[0][1]["env"]
  assert "AMBIENT_SECRET" not in env and "AGENTCFG_SUPERVISOR_CAPABILITY" not in env
  assert calls[0][0][2] == env["https_proxy"] and env["no_proxy"] == ""
  assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader" and env["GIT_CONFIG_VALUE_0"] == "Authorization: Basic synthetic-github"
  assert "synthetic-github" not in str(calls[0][0])


def test_github_clone_uses_only_new_output_and_holds_the_common_write_lease(tmp_path, monkeypatch):
  from agentcfg.pi_web_git import clone_arguments
  operations, host, principal, args = setup(tmp_path, monkeypatch)
  manifest = host.manifest(); options = manifest["options"]
  cwd = next(row["path"] for row in options["paths"]["roots"].values() if row["purpose"] == "project")
  cache = Path(cwd) / "clone-cache"; cache.mkdir()
  options["paths"]["roots"]["clones"] = {"path": str(cache), "purpose": "write"}
  options["web"]["github_clone"] = {"git_tool_ref": "ffmpeg", "root_ref": "clones"}
  manifest["web_services"]["github"] = {"type": "api", "origins": ["https://github.com"], "network_route": "direct"}
  manifest["permission_policy"]["rules"].append({"id": "clone-output", "kind": "file", "effect": "allow", "root_ref": "clones", "relative_path": ".", "match": "subtree",
    "tool_ids": ["write", "read"], "operations": ["read", "write", "create"]})
  args.update(operation="git-clone", input={"owner": "fixture", "repo": "example", "ref": "main"}, cwd=cwd, github_authorization="Basic synthetic")
  ticket = operations.handle(principal, "ordinary_web_cli_prepare", args)
  row = operations.commands.records[ticket["operation_id"]]
  destination = Path(ticket["destination"])
  assert destination.parent == cache and destination.is_dir()
  assert row["check"]["write_roots"] == [str(destination)] and cwd not in row["check"]["read_roots"]
  assert host.store.read(ticket["lease_id"])["planned_workspaces"]
  document = json.loads((Path(row["check"]["cwd"]) / "input.json").read_text())
  assert document["github_authorization"] == "Basic synthetic"
  assert "Basic synthetic" not in json.dumps(ticket) and "Basic synthetic" not in json.dumps(row)
  assert "credential.helper=" in document["argv"] and "core.hooksPath=/dev/null" in document["argv"]
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    operations.prepare(principal, {"operation_id": "other-writer", "role_id": "main", "cwd": cwd, "tool_name": "write", "input": {"path": str(cache / "other"), "content": "x"}})
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  (destination / "user-edit.txt").write_text("keep user edit")
  operations.handle(principal, "ordinary_command_finish", {"operation_id": ticket["operation_id"]})
  assert (destination / "user-edit.txt").read_text() == "keep user edit"
  for rule in manifest["permission_policy"]["rules"]:
    if rule["id"] == "clone-output":
      rule["tool_ids"].append("ls"); rule["operations"].append("list")
  (destination / "README.md").write_text("# Synthetic clone\n")
  content = operations.handle(principal, "ordinary_web_git_content", {"cwd": cwd, "directory": str(destination), "type": "root", "path": ""})
  assert "Synthetic clone" in content["content"] and "user-edit.txt" in content["content"]
  outside = tmp_path / "private-sentinel"; outside.write_text("must not read")
  (destination / "escape").symlink_to(outside)
  with pytest.raises(Conflict):
    operations.handle(principal, "ordinary_web_git_content", {"cwd": cwd, "directory": str(destination), "type": "blob", "path": "escape"})
  manifest["permission_policy"]["rules"].append({"id": "deny-clone-read", "kind": "file", "effect": "deny", "root_ref": "clones", "relative_path": ".", "match": "subtree",
    "tool_ids": ["read"], "operations": ["read"]})
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    operations.handle(principal, "ordinary_web_git_content", {"cwd": cwd, "directory": str(destination), "type": "blob", "path": "README.md"})
  for ref in ("--upload-pack=evil", "main..other", "refs/heads/a.lock", "a\nb"):
    with pytest.raises(ConfigError): clone_arguments({"owner": "fixture", "repo": "example", "ref": ref}, destination)
