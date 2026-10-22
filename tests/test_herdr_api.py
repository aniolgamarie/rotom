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


def structured_schema():
  from copy import deepcopy
  from work_helpers import FIXTURES
  schema = deepcopy(json.loads((FIXTURES / "api-schema.json").read_text())["audited_official_request_schema"])
  delta = json.loads((FIXTURES.parent / "v2" / "api-schema.json").read_text())["audited_official_request_schema"]
  request = schema["schemas"]["request"]
  request["oneOf"].extend(delta["schemas"]["request"]["oneOf"])
  request["$defs"].update(delta["schemas"]["request"]["$defs"])
  return schema


@pytest.mark.parametrize("method,params", [
  ("workspace.create", {"cwd": "/projects/example", "label": "Example", "focus": False,
    "env": {"ROTOM_WORK_LAUNCH_V2": "synthetic one-use envelope"}}),
  ("workspace.rename", {"workspace_id": "workspace-2", "label": "Renamed"}),
])
def test_structured_public_requests_and_results(monkeypatch, method, params):
  from work_helpers import FIXTURES
  response = json.loads((FIXTURES.parent / "v2" / "responses.json").read_text())[method]
  c, fake = client(monkeypatch, response)
  with c:
    assert c.request(method, params) == response
  assert fake.requests[0]["params"] == params
  assert len(fake.requests) == 1


@pytest.mark.parametrize("method,params", [
  ("workspace.create", {"cwd": "/projects/example", "argv": ["sh"]}),
  ("workspace.rename", {"label": "Wrong implicit focused workspace"}),
  ("workspace.close", {"workspace_id": "workspace-2", "close_group": False}),
  ("pane.current", {"workspace_id": "workspace-2"}),
])
def test_structured_unsupported_or_implicit_requests_never_connect(monkeypatch, method, params):
  c, fake = client(monkeypatch)
  with c, pytest.raises(TermcfgError):
    c.request(method, params)
  assert not fake.requests and not fake.paths


@pytest.mark.parametrize("method,params", [
  ("workspace.create", {"cwd": "/projects/example", "label": "Example", "focus": False, "env": {}}),
  ("workspace.rename", {"workspace_id": "workspace-2", "label": "Renamed"}),
])
def test_structured_lost_mutation_reply_is_unknown_without_resend(monkeypatch, method, params):
  c, fake = client(monkeypatch, TimeoutError())
  with c, pytest.raises(TermcfgError) as error:
    c.request(method, params)
  assert error.value.code == 4
  assert len(fake.requests) == 1


def test_structured_admission_checks_new_capabilities_without_changing_legacy(monkeypatch):
  from work_helpers import FIXTURES
  legacy = json.loads((FIXTURES / "api-schema.json").read_text())["audited_official_request_schema"]
  monkeypatch.setattr(herdr, "_cli_json", lambda *args: legacy)
  assert herdr.verify_schema("/bin/example-herdr", herdr.Deadline())["protocol"] == 22
  with pytest.raises(TermcfgError) as error:
    herdr.verify_schema("/bin/example-herdr", herdr.Deadline(), structured=True)
  assert error.value.code == 5
  current = structured_schema()
  monkeypatch.setattr(herdr, "_cli_json", lambda *args: current)
  assert herdr.verify_schema("/bin/example-herdr", herdr.Deadline(), structured=True)["protocol"] == 22
  current["schemas"]["request"]["$defs"]["WorkspaceCreateParams"]["properties"].pop("env")
  with pytest.raises(TermcfgError):
    herdr.verify_schema("/bin/example-herdr", herdr.Deadline(), structured=True)


def test_v2_delta_provenance_and_close_limitation():
  import hashlib
  from work_helpers import FIXTURES
  from jsonschema import Draft202012Validator
  directory = FIXTURES.parent / "v2"
  source = json.loads((directory / "source.json").read_text())
  assert source["official_schema_complete"] is False
  assert source["coverage"]["unsupported_capability"] == ["workspace.close"]
  for name, digest in source["fixture_sha256"].items():
    assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
  values = json.loads((directory / "responses.json").read_text())
  for method in source["coverage"]["wire_result_methods"]:
    Draft202012Validator(herdr.RESULT_SCHEMAS[method]).validate(values[method])


def test_structured_payload_removed_from_headless_server_environment(monkeypatch, tmp_path):
  calls = []
  monkeypatch.setenv("ROTOM_WORK_LAUNCH_V2", "synthetic one-use envelope")
  monkeypatch.setattr(herdr.subprocess, "Popen", lambda argv, **kw: calls.append(kw) or SimpleNamespace(pid=42))
  herdr.start_headless("/bin/example-herdr", "work", herdr.Deadline(), tmp_path)
  assert "ROTOM_WORK_LAUNCH_V2" not in calls[0]["env"]


def startup_fixture(monkeypatch, tmp_path):
  from termcfg.work_config import WorkSettings
  import termcfg.work_config as configuration
  binary = tmp_path / "synthetic-herdr"
  binary.write_bytes(b"synthetic binary identity")
  binary.chmod(0o700)
  settings = WorkSettings(tmp_path / "private.toml", str(binary), "trial", model="structured-v1")
  monkeypatch.setattr(configuration, "prepared_config", lambda: (tmp_path / "native.toml", "a" * 64))
  monkeypatch.setattr(configuration, "validate_native_config", lambda *args: None)
  monkeypatch.setattr(herdr.subprocess, "run", lambda *args, **kwargs:
    SimpleNamespace(returncode=0, stdout="herdr 0.9.5\n"))
  process = {"pid": 1234, "start": "5678", "executable": [binary.stat().st_dev, binary.stat().st_ino]}
  monkeypatch.setattr(herdr, "observe_process", lambda pid: dict(process))
  fake = FakeHerdr(str(tmp_path / "native" / "api.sock"), version="v2")
  fake.peer_pid = process["pid"]
  return settings, fake, process


def test_structured_existing_server_without_startup_proof_is_not_adopted(monkeypatch, tmp_path, sentinel_factory):
  settings, fake, _ = startup_fixture(monkeypatch, tmp_path)
  before = sentinel_factory(tmp_path)
  with pytest.raises(TermcfgError) as error:
    herdr.require_startup_evidence(fake, settings, settings.herdr_binary)
  assert error.value.code == 5
  assert not fake.mutation_calls
  before.assert_unchanged()


def test_structured_startup_records_disk_server_and_observation_separately(monkeypatch, tmp_path, sentinel_factory):
  settings, fake, process = startup_fixture(monkeypatch, tmp_path)
  inputs = herdr.native_inputs(settings, settings.herdr_binary, fake.deadline)
  proof = herdr.record_startup_evidence(fake, settings, settings.herdr_binary, process, inputs)
  assert proof["inputs"]["disk_version"] == "0.9.5"
  assert proof["server_version"] == "0.9.5" and proof["protocol"] == 22
  assert proof["config_observation"] == "startup-file-and-wrapper"
  assert proof["inputs"]["detection"] == "not-used-for-lifecycle"
  before = sentinel_factory(Path(os.environ["XDG_STATE_HOME"]))
  assert herdr.require_startup_evidence(fake, settings, settings.herdr_binary) == proof
  before.assert_unchanged()
  assert not fake.mutation_calls


@pytest.mark.parametrize("change", ["binary", "config", "process", "endpoint", "server-version"])
def test_structured_startup_drift_refuses_without_native_mutation(monkeypatch, tmp_path, change):
  import termcfg.work_config as configuration
  settings, fake, process = startup_fixture(monkeypatch, tmp_path)
  inputs = herdr.native_inputs(settings, settings.herdr_binary, fake.deadline)
  herdr.record_startup_evidence(fake, settings, settings.herdr_binary, process, inputs)
  if change == "binary":
    Path(settings.herdr_binary).write_bytes(b"changed synthetic binary")
  elif change == "config":
    monkeypatch.setattr(configuration, "prepared_config", lambda: (tmp_path / "native.toml", "b" * 64))
  elif change == "process":
    process["start"] = "5679"
  elif change == "endpoint":
    fake.identity = (7, 12)
  else:
    fake.data["ping"]["version"] = "0.10.0-synthetic"
  with pytest.raises(TermcfgError):
    herdr.require_startup_evidence(fake, settings, settings.herdr_binary)
  assert not fake.mutation_calls


def test_structured_startup_cannot_claim_another_native_process(monkeypatch, tmp_path):
  settings, fake, process = startup_fixture(monkeypatch, tmp_path)
  inputs = herdr.native_inputs(settings, settings.herdr_binary, fake.deadline)
  fake.peer_pid += 1
  with pytest.raises(TermcfgError):
    herdr.record_startup_evidence(fake, settings, settings.herdr_binary, process, inputs)
  assert not fake.mutation_calls


def test_expected_peer_pid_is_checked_before_any_mutation_send(monkeypatch):
  c, fake = client(monkeypatch, {"type": "ok"})
  monkeypatch.setattr(herdr, "peer_pid", lambda connection: 9999)
  c.expected_peer_pid = 1234
  with c, pytest.raises(TermcfgError) as error:
    c.request("workspace.report_metadata", {"workspace_id": "workspace-1", "source": "rotom-work-v2", "tokens": {"rw2_pending": "a" * 32}})
  assert error.value.code == 4
  assert not fake.requests


@pytest.mark.parametrize("change", ["unknown-field", "float-version", "unsafe-mode"])
def test_startup_record_schema_or_permission_conflict_is_not_repaired(monkeypatch, tmp_path, change):
  from termcfg.work_state import WorkState, json_bytes
  settings, fake, process = startup_fixture(monkeypatch, tmp_path)
  inputs = herdr.native_inputs(settings, settings.herdr_binary, fake.deadline)
  proof = herdr.record_startup_evidence(fake, settings, settings.herdr_binary, process, inputs)
  with WorkState(fake.socket_path, fake.identity) as state:
    path = state.root / "server.json"
  if change == "unknown-field":
    proof["extra"] = "invalid"
  elif change == "float-version":
    proof["version"] = 2.0
  path.write_bytes(json_bytes(proof))
  if change == "unsafe-mode":
    path.chmod(0o644)
  original = path.read_bytes()
  with pytest.raises(TermcfgError) as error:
    herdr.require_startup_evidence(fake, settings, settings.herdr_binary)
  assert error.value.code == 4
  with pytest.raises(TermcfgError):
    herdr.record_startup_evidence(fake, settings, settings.herdr_binary, process, inputs)
  assert path.read_bytes() == original
  assert not fake.mutation_calls


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


def test_structured_tab_rename_explicit_identity_and_tab_result(monkeypatch):
  from copy import deepcopy
  response = deepcopy(native_responses()["tab.get"])
  response["tab"]["label"] = "Problem 中文"
  c, sockets = client(monkeypatch, response)
  with c:
    assert c.request("tab.rename", {"tab_id": response["tab"]["tab_id"], "label": "Problem 中文"}) == response
  assert len(sockets.requests) == 1


@pytest.mark.parametrize("params", [{"label": "implicit"}, {"tab_id": "tab-1"},
  {"tab_id": "tab-1", "label": "named", "workspace_id": "workspace-1"}])
def test_structured_tab_rename_rejects_missing_or_unknown_fields_before_connect(monkeypatch, params):
  c, sockets = client(monkeypatch)
  with c, pytest.raises(TermcfgError):
    c.request("tab.rename", params)
  assert not sockets.requests and not sockets.paths


def test_structured_tab_rename_lost_reply_never_resends(monkeypatch):
  c, sockets = client(monkeypatch, TimeoutError())
  with c, pytest.raises(TermcfgError) as error:
    c.request("tab.rename", {"tab_id": "tab-1", "label": "Problem"})
  assert error.value.code == 4
  assert len(sockets.requests) == 1


def test_structured_tab_rename_capability_required_only_for_structured(monkeypatch):
  schema = structured_schema()
  request = schema["schemas"]["request"]
  request["oneOf"] = [item for item in request["oneOf"] if item["properties"]["method"]["const"] != "tab.rename"]
  monkeypatch.setattr(herdr, "_cli_json", lambda *args: schema)
  assert herdr.verify_schema("/bin/example-herdr", herdr.Deadline())["protocol"] == 22
  with pytest.raises(TermcfgError) as error:
    herdr.verify_schema("/bin/example-herdr", herdr.Deadline(), structured=True)
  assert error.value.code == 5


def test_v2_fake_tab_rename_preserves_workspace_pane_and_process_identity():
  from copy import deepcopy
  fake = FakeHerdr(version="v2")
  made = fake.request("workspace.create", {"cwd": "/synthetic/project", "label": "Project", "focus": False, "env": {}})
  before = deepcopy((fake.workspaces, fake.panes))
  tab_id = made["tab"]["tab_id"]
  response = fake.request("tab.rename", {"tab_id": tab_id, "label": "Problem 中文"})
  assert response["type"] == "tab_info" and response["tab"]["label"] == "Problem 中文"
  assert fake.tabs[tab_id]["label"] == "Problem 中文"
  assert (fake.workspaces, fake.panes) == before
  assert fake.mutation_calls[-1][0] == "tab.rename"
  legacy = FakeHerdr()
  with pytest.raises(AssertionError):
    legacy.request("tab.rename", {"tab_id": "tab-1", "label": "unsupported legacy fixture"})
