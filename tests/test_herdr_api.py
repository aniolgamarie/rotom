"""官方协议、端点固定和超时边界；所有网络与进程均为替身。"""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from termcfg import herdr
from termcfg.errors import TermcfgError
from work_helpers import FakeSockets, FakeHerdr, native_responses


def client(monkeypatch, *responses):
  sockets = FakeSockets(*({"result": response} if not isinstance(response, (Exception, bytes)) else response for response in responses))
  monkeypatch.setattr(herdr, "_pin_endpoint", lambda path: (os.open(os.devnull, os.O_RDONLY), (7, 11)))
  monkeypatch.setattr(herdr.socket, "socket", sockets)
  return herdr.HerdrClient("/tmp/example-herdr/api.sock", herdr.Deadline()), sockets


def test_one_connection_per_request_pinned_procfd(monkeypatch):
  c, fake = client(monkeypatch, native_responses()["ping"], {"type": "ok"})
  with c:
    assert c.request("ping", {})["protocol"] == 22
    c.request("workspace.report_metadata", {"workspace_id": "workspace-1", "source": "rotom-work-v1", "tokens": {"rw_epoch": "abc"}})
    assert c.identity == (7, 11)
  assert len(fake.sockets) == 2
  assert len(set(fake.paths)) == 1
  assert fake.paths[0].startswith("/proc/self/fd/")
  assert all(s.closed for s in fake.sockets)
  assert fake.requests[0]["id"] != fake.requests[1]["id"]


@pytest.mark.parametrize("method,params", [("pane.send_text", {}), ("server.stop", {}), ("pane.current", {}), ("tab.create", {"argv": ["sh"]})])
def test_unsafe_or_unknown_requests_never_connect(monkeypatch, method, params):
  c, fake = client(monkeypatch)
  with c, pytest.raises(TermcfgError):
    c.request(method, params)
  assert not fake.paths


@pytest.mark.parametrize("value", [b'not json\n', b'{"id":"wrong","result":{"type":"ok"}}\n', {"type": "pong", "version": "1", "protocol": 999, "capabilities": {}}, {"type": "pane_current", "pane": {"pane_id": "x"}}])
def test_malformed_reads_fail_closed(monkeypatch, value):
  c, fake = client(monkeypatch, value)
  with c, pytest.raises(TermcfgError) as error:
    c.request("ping" if not isinstance(value, dict) or value.get("type") == "pong" else "pane.current", {"caller_pane_id": "pane-1"} if isinstance(value, dict) and value.get("type") == "pane_current" else {})
  assert error.value.code == 5
  assert all(s.closed for s in fake.sockets)


@pytest.mark.parametrize("method,params,code", [("ping", {}, 5), ("tab.create", {"workspace_id": "workspace-1"}, 4)])
def test_lost_reply_no_mutation_retry(monkeypatch, method, params, code):
  c, fake = client(monkeypatch, TimeoutError())
  with c, pytest.raises(TermcfgError) as error:
    c.request(method, params)
  assert error.value.code == code
  assert len(fake.requests) == 1


def test_endpoint_replacement_identity_rejected(monkeypatch):
  c, _ = client(monkeypatch)
  c.close()
  with pytest.raises(TermcfgError) as error:
    herdr.HerdrClient(c.socket_path, herdr.Deadline(), expected_identity=(7, 12))
  assert error.value.code == 4


def test_regular_file_and_symlink_are_not_socket(tmp_path):
  path = tmp_path / "fake.sock"
  path.write_text("sentinel")
  with pytest.raises(TermcfgError):
    herdr.HerdrClient(path, herdr.Deadline())
  link = tmp_path / "link.sock"
  link.symlink_to(path)
  with pytest.raises(TermcfgError):
    herdr.HerdrClient(link, herdr.Deadline())
  assert path.read_text() == "sentinel"


def test_discovery_official_array_and_connection_error(monkeypatch):
  info = {"name": "work", "default": False, "running": True, "socket_path": "/tmp/example-herdr/api.sock", "session_dir": "/tmp/example-herdr"}
  calls = []
  def run(argv, **kwargs):
    calls.append((argv, kwargs))
    return SimpleNamespace(returncode=0, stdout=json.dumps({"sessions": [info]}))
  monkeypatch.setattr(herdr.subprocess, "run", run)
  assert herdr.discover("/bin/example-herdr", "work", herdr.Deadline()) == info
  assert calls[0][0] == ["/bin/example-herdr", "session", "list", "--json"]
  assert herdr.discover("/bin/example-herdr", "absent", herdr.Deadline()) is None
  info["connection_error"] = "private upstream message"
  with pytest.raises(TermcfgError) as error:
    herdr.discover("/bin/example-herdr", "work", herdr.Deadline())
  assert error.value.code == 5
  assert "private" not in str(error.value)


def test_start_headless_is_separate_from_ready(monkeypatch, tmp_path):
  calls = []
  caller_variables = ("ROTOM_WORK_LAUNCH_V1", "HERDR_PANE_ID", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_TERMINAL_ID", "HERDR_SOCKET_PATH", "HERDR_SESSION", "HERDR_ENV")
  for name in caller_variables:
    monkeypatch.setenv(name, "stale-example")
  monkeypatch.setenv("EDITOR", "example-editor")
  monkeypatch.setenv("ROTOM_TEST_TERMINAL_CUSTOM", "synthetic-terminal-setting")
  monkeypatch.setenv("HERDR_CONFIG_DIR", "/tmp/example-config")
  monkeypatch.setattr(herdr.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)) or SimpleNamespace(pid=42))
  assert herdr.start_headless("/bin/example-herdr", "work", herdr.Deadline(), tmp_path).pid == 42
  argv, kwargs = calls[0]
  assert argv == ["/bin/example-herdr", "--session", "work", "server"]
  assert kwargs["start_new_session"] is True
  assert kwargs["umask"] == 0o077
  assert kwargs["stdin"] == subprocess.DEVNULL
  assert not set(caller_variables).intersection(kwargs["env"])
  assert kwargs["env"]["EDITOR"] == "example-editor"
  assert kwargs["env"]["ROTOM_TEST_TERMINAL_CUSTOM"] == "synthetic-terminal-setting"
  assert kwargs["env"]["HERDR_CONFIG_DIR"] == "/tmp/example-config"
  assert kwargs["env"]["PATH"].split(os.pathsep)[0] == str(tmp_path)


def test_total_deadline_is_not_extended(monkeypatch):
  ticks = iter([10, 11, 39, 41])
  monkeypatch.setattr(herdr.time, "monotonic", lambda: next(ticks))
  deadline = herdr.Deadline(30)
  assert deadline.remaining(5) == 5
  assert deadline.remaining(5) == 1
  with pytest.raises(TermcfgError):
    deadline.remaining(5)


def test_fake_metadata_seq_and_flat_tokens():
  fake = FakeHerdr()
  ws = fake.request("worktree.open", {"cwd": "/tmp/example/project", "path": "/tmp/example/project"})["workspace"]["workspace_id"]
  for seq, value in [(2, "accepted"), (1, "stale")]:
    fake.request("workspace.report_metadata", {"workspace_id": ws, "source": "rotom-work-v1", "seq": seq, "tokens": {"rw_phase": value}})
  assert fake.request("workspace.get", {"workspace_id": ws})["workspace"]["tokens"]["rw_phase"] == "accepted"


def test_public_schema_capabilities_and_different_product_version(monkeypatch):
  from work_helpers import FIXTURES
  schema = json.loads((FIXTURES / "api-schema.json").read_text())["audited_official_request_schema"]
  monkeypatch.setattr(herdr, "_cli_json", lambda *args: schema)
  assert herdr.verify_schema("/bin/example-herdr", herdr.Deadline())["protocol"] == 22
  schema["schemas"]["request"]["oneOf"] = []
  with pytest.raises(TermcfgError) as error:
    herdr.verify_schema("/bin/example-herdr", herdr.Deadline())
  assert error.value.code == 5
  pong = native_responses()["ping"]
  pong["version"] = "0.10.0-example"
  c, _ = client(monkeypatch, pong)
  with c:
    assert c.request("ping")["version"] == "0.10.0-example"


def test_connect_failure_is_not_a_mutation_attempt(monkeypatch):
  c, fake = client(monkeypatch)
  fake.connect_error = ConnectionRefusedError()
  with c, pytest.raises(TermcfgError) as error:
    c.request("tab.create", {"workspace_id": "workspace-1"})
  assert error.value.code == 5
  assert not fake.requests


def test_oversize_and_duplicate_json_rejected(monkeypatch):
  monkeypatch.setattr(herdr, "MAX_RESPONSE_BYTES", 32)
  for reply in [b"x" * 33, b'{"id":"a","id":"b"}\n']:
    c, _ = client(monkeypatch, reply)
    with c, pytest.raises(TermcfgError) as error:
      c.request("ping")
    assert error.value.code == 5


def test_endpoint_secure_directory_walk(monkeypatch):
  from types import SimpleNamespace
  import stat
  real_os = herdr.os
  closed = []
  opened = []
  metadata = {
    10: SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0),
    11: SimpleNamespace(st_mode=stat.S_IFDIR | 0o1777, st_uid=0),
    12: SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=123),
    13: SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=123, st_dev=7, st_ino=11),
  }
  def fake_open(name, flags, **kwargs):
    opened.append((name, flags, kwargs))
    return 9 + len(opened)
  fake_os = SimpleNamespace(**{name: getattr(real_os, name) for name in ("O_PATH", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW")}, open=fake_open, close=closed.append, fstat=metadata.__getitem__, getuid=lambda:123, stat=lambda path:metadata[13])
  monkeypatch.setattr(herdr, "os", fake_os)
  assert herdr._pin_endpoint("/tmp/example-herdr/api.sock") == (13, (7, 11))
  assert closed == [10, 11, 12]
  assert opened[-1][1] & real_os.O_NOFOLLOW
  opened.clear()
  metadata[12].st_mode = stat.S_IFDIR | 0o755
  with pytest.raises(TermcfgError) as error:
    herdr._pin_endpoint("/tmp/example-herdr/api.sock")
  assert error.value.code == 5


def test_fixture_digests_and_responses_match_audited_shapes():
  import hashlib
  from work_helpers import FIXTURES
  from jsonschema import Draft202012Validator
  source = json.loads((FIXTURES / "source.json").read_text())
  assert source["official_schema_complete"] is False
  for name, digest in source["fixture_sha256"].items():
    assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest
  for method, result in native_responses().items():
    Draft202012Validator(herdr.RESULT_SCHEMAS[method]).validate(result)


def test_schema_metadata_limits_must_match(monkeypatch):
  from work_helpers import FIXTURES
  schema = json.loads((FIXTURES / "api-schema.json").read_text())["audited_official_request_schema"]
  schema["schemas"]["request"]["$defs"]["WorkspaceReportMetadataParams"]["properties"]["tokens"]["maxProperties"] = 1
  monkeypatch.setattr(herdr, "_cli_json", lambda *args: schema)
  with pytest.raises(TermcfgError) as error:
    herdr.verify_schema("/bin/example-herdr", herdr.Deadline())
  assert error.value.code == 5


def test_malformed_mutation_response_is_uncertain(monkeypatch):
  c, fake = client(monkeypatch, {"type": "wrong_result"})
  with c, pytest.raises(TermcfgError) as error:
    c.request("workspace.focus", {"workspace_id": "workspace-1"})
  assert error.value.code == 4
  assert len(fake.requests) == 1


def test_unencodable_request_is_dependency_error_before_connect(monkeypatch):
  c, fake = client(monkeypatch)
  with c, pytest.raises(TermcfgError) as error:
    c.request("workspace.get", {"workspace_id": "\ud800"})
  assert error.value.code == 5
  assert not fake.paths


def test_read_only_pinned_address_for_public_cli(monkeypatch):
  c, _ = client(monkeypatch)
  with c:
    assert c.pinned_address == f"/proc/self/fd/{c.pinned_fd}"
    with pytest.raises(AttributeError):
      c.pinned_fd = 10
  with pytest.raises(TermcfgError):
    _ = c.pinned_address
