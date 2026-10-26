"""命名代理能力不能弱化维护准入；全部后端/CLI 工作区合成且默认离线。"""
from types import SimpleNamespace

import pytest

from agentcfg import backends, cli, commands, dependencies
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_lock_sync_proxy import PROXY
from test_rotom_setup_operation import operation


@pytest.mark.parametrize("kind", ["legacy", "progress", "positional-only", "positional-and-kwargs"])
def test_selected_proxy_rejection_precedes_backend_and_progress(kind):
  calls, stages = [], []
  def legacy(w, lock): calls.append(True)
  def progress(w, lock, *, progress=None): calls.append(True)
  def positional(w, lock, proxy=None, /): calls.append(True)
  def positional_kwargs(w, lock, proxy=None, /, **options): calls.append(True)
  action = {"legacy": legacy, "progress": progress, "positional-only": positional,
    "positional-and-kwargs": positional_kwargs}[kind]
  ws = SimpleNamespace(backend=SimpleNamespace(sync=action))
  with pytest.raises(ConfigError) as caught:
    commands.sync_backend(ws, object(), stages.append, proxy=PROXY)
  assert caught.value.code == "sync-proxy-unsupported"
  assert calls == [] and stages == []


@pytest.mark.parametrize("kind", ["keyword-only", "positional-or-keyword", "kwargs"])
def test_selected_proxy_keyword_support_keeps_object_identity(kind):
  calls, stages, lock = [], [], object()
  def keyword(w, actual, *, proxy, progress):
    calls.append((w, actual, proxy, progress))
    return lock
  def positional_keyword(w, actual, proxy, progress):
    return keyword(w, actual, proxy=proxy, progress=progress)
  def kwargs(w, actual, **options):
    assert set(options) == {"proxy", "progress"}
    return keyword(w, actual, **options)
  ws = SimpleNamespace(backend=SimpleNamespace(sync={"keyword-only": keyword,
    "positional-or-keyword": positional_keyword, "kwargs": kwargs}[kind]))
  report = stages.append
  assert commands.sync_backend(ws, lock, report, proxy=PROXY) is lock
  assert len(calls) == 1
  assert calls[0][0] is ws and calls[0][1] is lock and calls[0][2] is PROXY and calls[0][3] is report


@pytest.mark.parametrize("kind", ["proxy-only", "kwargs", "positional-only", "positional-and-kwargs"])
def test_proxy_support_never_grants_implicit_maintenance_capability(kind):
  calls, stages = [], []
  def proxy_only(w, lock, *, proxy=None): calls.append(True)
  def kwargs(w, lock, **options): calls.append(True)
  def positional(w, lock, maintenance=None, /, *, proxy=None): calls.append(True)
  def positional_kwargs(w, lock, maintenance=None, /, **options): calls.append(True)
  action = {"proxy-only": proxy_only, "kwargs": kwargs, "positional-only": positional,
    "positional-and-kwargs": positional_kwargs}[kind]
  ws = SimpleNamespace(backend=SimpleNamespace(sync=action))
  with pytest.raises(Conflict):
    commands.sync_backend(ws, object(), stages.append, proxy=PROXY, maintenance=object())
  assert calls == [] and stages == []


def test_maintenance_only_backend_rejects_selected_proxy_without_consumption():
  calls, stages = [], []
  def sync(w, lock, *, maintenance): calls.append(maintenance)
  ws = SimpleNamespace(backend=SimpleNamespace(sync=sync))
  with pytest.raises(ConfigError, match="sync-proxy-unsupported"):
    commands.sync_backend(ws, object(), stages.append, proxy=PROXY, maintenance=object())
  assert calls == [] and stages == []


@pytest.mark.parametrize("proxy_mode", ["named", "kwargs"])
def test_explicit_maintenance_and_proxy_forward_same_objects_once(proxy_mode):
  token, lock, result, calls = object(), object(), object(), []
  def named(w, actual, *, maintenance, proxy, progress):
    assert maintenance is token and proxy is PROXY and actual is lock
    calls.append(w)
    return result
  def kwargs(w, actual, *, maintenance, **options):
    return named(w, actual, maintenance=maintenance, **options)
  ws = SimpleNamespace(backend=SimpleNamespace(sync=named if proxy_mode == "named" else kwargs))
  assert commands.sync_backend(ws, lock, lambda stage: None, proxy=PROXY, maintenance=token) is result
  assert calls == [ws]


@pytest.mark.parametrize("failure", [RuntimeError("synthetic"), TypeError("synthetic"), ConfigError("synthetic")])
def test_capable_backend_original_exception_is_not_replaced_or_retried(failure):
  token, calls = object(), []
  def sync(w, lock, *, maintenance, proxy, progress):
    assert maintenance is token and proxy is PROXY
    calls.append(True)
    raise failure
  ws = SimpleNamespace(backend=SimpleNamespace(sync=sync))
  with pytest.raises(type(failure)) as caught:
    commands.sync_backend(ws, object(), lambda stage: None, proxy=PROXY, maintenance=token)
  assert caught.value is failure and calls == [True]


@pytest.mark.parametrize("kind", ["legacy", "positional-only", "kwargs"])
def test_no_proxy_preserves_legacy_call_without_proxy_keyword(kind):
  lock, calls, stages = object(), [], []
  def legacy(w, actual):
    assert actual is lock
    calls.append(True)
  def positional(w, actual, proxy=None, /):
    assert proxy is None
    legacy(w, actual)
  def kwargs(w, actual, **options):
    assert "proxy" not in options
    legacy(w, actual)
  ws = SimpleNamespace(backend=SimpleNamespace(sync={"legacy": legacy, "positional-only": positional,
    "kwargs": kwargs}[kind]))
  commands.sync_backend(ws, lock, stages.append, proxy=None)
  assert calls == [True]


@pytest.mark.parametrize("kwargs_supported", [False, True])
def test_cmd_lock_rejects_positional_proxy_before_backend(tmp_path, monkeypatch, kwargs_supported):
  calls = []
  def positional(w, proxy=None, /): calls.append(True)
  def positional_kwargs(w, proxy=None, /, **options): calls.append(True)
  ws = SimpleNamespace(backend=SimpleNamespace(resolve_lock_for=positional_kwargs if kwargs_supported else positional),
    resolved=SimpleNamespace(data={"machine": {"proxies": {"selected": PROXY}}}))
  monkeypatch.setattr(commands, "workspace", lambda args: ws)
  with pytest.raises(ConfigError) as caught:
    commands.cmd_lock(SimpleNamespace(agent="pi", proxy="selected"))
  assert caught.value.code == "lock-proxy-unsupported" and calls == []


def test_cmd_lock_no_proxy_retains_original_single_argument_backend(monkeypatch):
  calls = []
  def resolve(w): calls.append(w)
  ws = SimpleNamespace(backend=SimpleNamespace(resolve_lock_for=resolve),
    resolved=SimpleNamespace(data={"machine": {}}))
  monkeypatch.setattr(commands, "workspace", lambda args: ws)
  monkeypatch.setattr(commands, "output", lambda *args, **kwargs: 0)
  assert commands.cmd_lock(SimpleNamespace(agent="pi", proxy=None)) == 0
  assert calls == [ws]


def test_cmd_sync_no_proxy_retains_narrow_sync_backend_seam(monkeypatch):
  lock, calls = object(), []
  ws = SimpleNamespace(repository=object(), resolved=SimpleNamespace(data={"machine": {}}),
    backend=SimpleNamespace(read_lock=lambda repo: lock))
  def sync(w, actual, progress):
    assert w is ws and actual is lock and callable(progress)
    calls.append(True)
    return {}
  monkeypatch.setattr(commands, "workspace", lambda args: ws)
  monkeypatch.setattr(commands, "sync_backend", sync)
  monkeypatch.setattr(commands, "output", lambda *args, **kwargs: 0)
  assert commands.cmd_sync(SimpleNamespace(proxy=None)) == 0
  assert calls == [True]


def test_dsh_no_proxy_retains_narrow_dependency_sync_seam(monkeypatch):
  ws, lock, calls = object(), object(), []
  def sync(w, actual, adapter_id, *, progress=None):
    assert w is ws and actual is lock and adapter_id == "dsh"
    calls.append(True)
    return {}
  monkeypatch.setattr(dependencies, "sync", sync)
  assert backends.DshBackend().sync(ws, lock) == {}
  assert calls == [True]


def test_explicit_omp_sync_cli_rejects_proxy_instead_of_ignoring_it(tmp_path, monkeypatch, capsys):
  calls, lock = [], object()
  def sync(w, actual, *, progress=None):
    calls.append("sync")
    return {"installed": True}
  def read_lock(repository):
    calls.append("read_lock")
    return lock
  ws = SimpleNamespace(agent="omp", profile="omp-default", repository=tmp_path / "repository",
    instance=tmp_path / "instance", backend=SimpleNamespace(sync=sync, read_lock=read_lock),
    resolved=SimpleNamespace(data={"machine": {"proxies": {"selected": PROXY}}}))
  monkeypatch.setattr(commands, "workspace", lambda args: ws)
  monkeypatch.setattr(cli, "resolve_selection", lambda args: None)
  assert cli.main(["--local", str(tmp_path / "machine.toml"), "--profile", "omp-default", "sync",
    "--proxy", "selected", "--format", "json"]) == 2
  assert calls == ["read_lock"] and capsys.readouterr().out == ""


@pytest.mark.parametrize("command", ["lock", "sync"])
def test_dependency_commands_ignore_session_proxy_default_without_explicit_selection(monkeypatch, command):
  calls, lock = [], object()
  machine = {"environment": {"proxy": "selected"}, "proxies": {"selected": PROXY}}
  def resolve(w): calls.append("lock")
  def sync(w, actual):
    assert actual is lock
    calls.append("sync")
    return {}
  ws = SimpleNamespace(repository=object(), resolved=SimpleNamespace(data={"machine": machine}),
    backend=SimpleNamespace(resolve_lock_for=resolve, read_lock=lambda repo: lock, sync=sync))
  monkeypatch.setattr(commands, "workspace", lambda args: ws)
  monkeypatch.setattr(commands, "output", lambda *args, **kwargs: 0)
  assert getattr(commands, "cmd_" + command)(SimpleNamespace(agent="pi", proxy=None)) == 0
  assert calls == [command] and machine["environment"]["proxy"] == "selected"


@pytest.mark.parametrize("command", ["lock", "sync"])
def test_explicit_dependency_proxy_uses_override_without_changing_session_default(monkeypatch, command):
  override, calls, lock = {"url": "http://other.example.invalid:8081"}, [], object()
  machine = {"environment": {"proxy": "selected"}, "proxies": {"selected": PROXY, "override": override}}
  def resolve(w, *, proxy): calls.append(proxy)
  def sync(w, actual, *, proxy, progress=None):
    assert actual is lock
    calls.append(proxy)
    return {}
  ws = SimpleNamespace(repository=object(), resolved=SimpleNamespace(data={"machine": machine}),
    backend=SimpleNamespace(resolve_lock_for=resolve, read_lock=lambda repo: lock, sync=sync))
  monkeypatch.setattr(commands, "workspace", lambda args: ws)
  monkeypatch.setattr(commands, "output", lambda *args, **kwargs: 0)
  assert getattr(commands, "cmd_" + command)(SimpleNamespace(agent="pi", proxy="override")) == 0
  assert len(calls) == 1 and calls[0] is override
  assert machine["environment"]["proxy"] == "selected" and machine["proxies"]["selected"] is PROXY


@pytest.mark.parametrize("command", ["lock", "sync"])
def test_rotom_dependency_proxy_reaches_backend_through_real_parsers(tmp_path, monkeypatch, command):
  from rotom import cli as rotom_cli, preferences
  calls, selected, lock = [], [], object()
  local = tmp_path / "machine.toml"
  def resolve(w, *, proxy): calls.append(proxy)
  def sync(w, actual, *, proxy, progress=None):
    assert actual is lock
    calls.append(proxy)
    return {}
  ws = SimpleNamespace(repository=tmp_path / "repository", backend=SimpleNamespace(resolve_lock_for=resolve,
    read_lock=lambda repo: lock, sync=sync), resolved=SimpleNamespace(data={"machine": {
      "proxies": {"selected": PROXY}}}))
  def workspace(args):
    selected.append((args.command, args.profile, args.proxy))
    return ws
  monkeypatch.setattr(commands, "workspace", workspace)
  monkeypatch.setattr(cli, "resolve_selection", lambda args: None)
  monkeypatch.setattr(commands, "output", lambda *args, **kwargs: 0)
  monkeypatch.setattr(preferences, "load_preferences", lambda: SimpleNamespace(get=lambda key: None))
  tool = ["--agent", "pi"] if command == "lock" else []
  assert rotom_cli.main(["--no-input", "agent", "--local", str(local), "--profile", "pi-base", command,
    *tool, "--proxy", "selected", "--format", "json"]) == 0
  assert selected == [(command, "pi-base", "selected")]
  assert len(calls) == 1 and calls[0] is PROXY


def test_omp_lock_without_proxy_stays_scope_free_through_real_cli(monkeypatch, capsys):
  from agentcfg import config
  from agentcfg.omp_dependencies import OmpBackend
  from rotom import cli as rotom_cli, preferences
  calls = []
  def forbidden(*args, **kwargs): pytest.fail("OMP public lock must not read scope or preferences")
  monkeypatch.setattr(commands, "workspace", forbidden)
  monkeypatch.setattr(cli, "resolve_selection", forbidden)
  monkeypatch.setattr(config, "read_local_document", forbidden)
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  monkeypatch.setattr(OmpBackend, "resolve_lock", lambda self, repository: calls.append(repository))
  assert rotom_cli.main(["--no-input", "agent", "lock", "--agent", "omp", "--format", "json"]) == 0
  assert len(calls) == 1
  assert '"locked": true' in capsys.readouterr().out


def test_setup_still_rejects_proxy_flag_before_workspace_or_preferences(monkeypatch):
  from rotom import cli as rotom_cli, preferences
  def forbidden(*args, **kwargs): pytest.fail("unsupported setup proxy must fail during parsing")
  monkeypatch.setattr(commands, "workspace", forbidden)
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  assert rotom_cli.main(["--no-input", "agent", "setup", "--proxy", "selected"]) == 2


def test_setup_core_ignores_session_proxy_default_and_keeps_narrow_sync_seam(operation):
  for workspace in (operation.first, operation.second):
    workspace.resolved = SimpleNamespace(data={"machine": {"environment": {"proxy": "selected"},
      "proxies": {"selected": PROXY}}})
  result = commands._setup_operation(operation.args, progress=operation.progress, preview=operation.preview,
    approve=operation.approve)
  assert result.code == 0 and result.result is operation.result
  assert operation.events.count("sync") == 1 and operation.events.count("apply") == 1


@pytest.mark.parametrize("entry", ["agentcfg", "rotom"])
@pytest.mark.parametrize("command", ["lock", "sync"])
def test_dependency_proxy_help_is_static_and_matches_supported_scope(monkeypatch, capsys, entry, command):
  from agentcfg import config
  from rotom import cli as rotom_cli, preferences
  def forbidden(*args, **kwargs): pytest.fail("static help must not load workspace, machine or preferences")
  monkeypatch.setattr(commands, "workspace", forbidden)
  monkeypatch.setattr(config, "read_local_document", forbidden)
  monkeypatch.setattr(preferences, "load_preferences", forbidden)
  action, args = (cli.main, [command, "--help"]) if entry == "agentcfg" else (
    rotom_cli.main, ["agent", command, "--help"])
  if entry == "agentcfg":
    with pytest.raises(SystemExit) as caught: action(args)
    assert caught.value.code == 0
  else:
    assert action(args) == 0
  text = capsys.readouterr().out
  assert "--proxy" in text and "machine.proxies.NAME" in text
  assert "dsh/pi" in text and "不继承普通会话默认代理" in text
