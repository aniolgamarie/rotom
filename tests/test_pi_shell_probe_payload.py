"""原生探针payload的离线oracle；不启动进程或真实socket。"""

import errno
import importlib.util
import json
import os
from pathlib import Path

import pytest


SOURCE = Path(__file__).parent / "fixtures/pi/shell-helper-probe/payload.py"
NONCE = "a" * 32
NAMES = {"project_write", "project_read", "readonly_read", "readonly_write_blocked", "outside_read_blocked",
  "outside_write_blocked", "deny_read_blocked", "deny_write_blocked", "git_read_blocked", "git_write_blocked",
  "private_home_write", "private_tmp_write", "env_clean", "fds_only_stdio", "inet_socket_denied",
  "inet6_socket_denied", "unix_socket_denied", "socketpair_works", "system_readonly"}


@pytest.fixture
def case(tmp_path, monkeypatch):
  spec = importlib.util.spec_from_file_location("synthetic_probe_payload", SOURCE)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  roots = {key: tmp_path / ("probe-" + key) for key in ("project", "readonly", "outside", "home", "tmp")}
  for root in roots.values(): root.mkdir()
  (roots["project"] / "private").mkdir()
  (roots["project"] / "nested/.git").mkdir(parents=True)
  for path, content in ((roots["readonly"] / "canary", b"probe-readonly\n"),
      (roots["outside"] / "canary", b"probe-outside\n"), (roots["project"] / "private/canary", b"deny"),
      (roots["project"] / "nested/.git/canary", b"git")):
    path.write_bytes(content)
  monkeypatch.setattr(module, "ROOTS", roots)
  monkeypatch.setattr(module, "WORK_ROOT", tmp_path)
  monkeypatch.setattr(module, "_namespace_links", lambda: {name: name + ":[123]" for name in ("pid", "net", "user", "mnt", "ipc", "uts")})
  monkeypatch.setattr(module, "_open_fds", lambda: (0, 1, 2))
  monkeypatch.setattr(module, "_mountinfo", lambda: "1 0 8:1 / /usr ro - ext4 source rw\n")
  monkeypatch.setattr(module, "_environment", lambda: {"HOME": "/.rotom-shell/home", "TMPDIR": "/tmp", "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "PWD": str(tmp_path / "project"), "SHLVL": "1", "_": "/usr/bin/python3.11"})
  sockets = []
  def denied(*args): raise PermissionError(errno.EPERM, "synthetic denied")
  monkeypatch.setattr(module.socket, "socket", denied)
  class End:
    def __init__(self): self.closed = False
    def sendall(self, data): assert data == b"probe"
    def recv(self, amount): return b"probe"[:amount]
    def close(self): self.closed = True
  def pair():
    result = (End(), End()); sockets.extend(result); return result
  monkeypatch.setattr(module.socket, "socketpair", pair)
  return module, roots, sockets


def test_unisolated_filesystem_does_not_claim_denials(case):
  module, roots, sockets = case
  report = module.observe(NONCE)
  assert set(report) == {"schema_version", "phase", "nonce", "observations", "namespaces"}
  assert report["schema_version"] == 1 and report["phase"] == "payload" and report["nonce"] == NONCE
  values = report["observations"]
  assert set(values) == NAMES and all(type(v) is bool for v in values.values())
  assert all(values[k] for k in ("project_write", "project_read", "readonly_read", "private_home_write", "private_tmp_write",
    "env_clean", "fds_only_stdio", "inet_socket_denied", "inet6_socket_denied", "unix_socket_denied", "socketpair_works", "system_readonly"))
  assert all(not values[k] for k in NAMES if k.endswith("_blocked"))
  assert (roots["project"] / "positive").read_bytes() == (NONCE + "\n").encode()
  assert not (roots["home"] / "positive").exists() and not (roots["tmp"] / "positive").exists()
  assert all(s.closed for s in sockets)
  assert str(roots["project"]) not in json.dumps(report)


@pytest.mark.parametrize("error", [errno.EACCES, errno.EPERM, errno.ENOENT, errno.ENOTDIR, errno.EROFS, errno.EIO, errno.EMFILE, errno.EEXIST])
def test_only_expected_filesystem_errors_count_as_denial(case, monkeypatch, error):
  module, _, _ = case
  def fail(*args, **kwargs): raise OSError(error, "private underlying error")
  monkeypatch.setattr(module, "_read", fail)
  monkeypatch.setattr(module, "_create", fail)
  values = module.observe(NONCE)["observations"]
  assert values["outside_read_blocked"] is (error in (errno.EACCES, errno.EPERM, errno.ENOENT, errno.ENOTDIR, errno.EROFS))
  assert values["readonly_write_blocked"] is values["outside_read_blocked"]
  assert not values["project_write"] and not values["readonly_read"]


@pytest.mark.parametrize("error", [errno.EACCES, errno.ENOSYS, errno.EIO])
def test_socket_denials_require_exact_eperm(case, monkeypatch, error):
  module, _, _ = case
  def fail(*args): raise OSError(error, "private socket error")
  monkeypatch.setattr(module.socket, "socket", fail)
  values = module.observe(NONCE)["observations"]
  assert all(not values[name] for name in ("inet_socket_denied", "inet6_socket_denied", "unix_socket_denied"))


@pytest.mark.parametrize("change", ["extra", "home", "pwd", "shlvl", "underscore", "missing"])
def test_environment_is_exact_and_never_reported(case, monkeypatch, change):
  module, _, _ = case; env = module._environment()
  if change == "extra": env["PRIVATE_TOKEN"] = "secret-value-sentinel"
  elif change == "missing": del env["TERM"]
  else: env[{"home": "HOME", "pwd": "PWD", "shlvl": "SHLVL", "underscore": "_"}[change]] = "secret-value-sentinel"
  monkeypatch.setattr(module, "_environment", lambda: env)
  report = module.observe(NONCE)
  assert not report["observations"]["env_clean"] and "secret-value-sentinel" not in json.dumps(report)


def test_fds_extra_and_rw_system_mount_are_not_success(case, monkeypatch):
  module, _, _ = case
  monkeypatch.setattr(module, "_open_fds", lambda: (0, 1, 2, 99))
  monkeypatch.setattr(module, "_mountinfo", lambda: "1 0 8:1 / /usr rw - ext4 source rw\n")
  values = module.observe(NONCE)["observations"]
  assert not values["fds_only_stdio"] and not values["system_readonly"]


@pytest.mark.parametrize("nonce", ["", "A" * 32, "a" * 31, "a" * 33, None])
def test_invalid_nonce_rejected_before_probe(case, monkeypatch, nonce):
  module, _, _ = case
  monkeypatch.setattr(module, "_read", lambda _: pytest.fail("input must reject first"))
  with pytest.raises(ValueError): module.observe(nonce)


def test_main_reports_fixed_error_and_one_json_line(case, capsys, monkeypatch):
  module, _, _ = case
  assert module.main(["--payload", NONCE]) == 0
  output = capsys.readouterr(); assert len(output.out.splitlines()) == 1 and not output.err
  assert json.loads(output.out)["nonce"] == NONCE
  def fail(nonce): raise RuntimeError("private underlying path")
  monkeypatch.setattr(module, "observe", fail)
  assert module.main(["--payload", NONCE]) == 5
  output = capsys.readouterr(); assert output.out == "" and output.err == "shell-probe-payload-failed\n"
  assert module.main(["--unknown", NONCE]) == 5
  assert "private" not in capsys.readouterr().err


def test_import_has_no_probe_actions(monkeypatch, capsys):
  def forbidden(*args, **kwargs): pytest.fail("probe at import")
  monkeypatch.setattr(os, "readlink", forbidden)
  spec = importlib.util.spec_from_file_location("fresh_payload", SOURCE)
  value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
  assert capsys.readouterr().out == ""


def test_unexpected_exception_cannot_be_a_successful_denial(case, monkeypatch):
  module, _, _ = case
  def fail(path): raise RuntimeError("secret-exception")
  monkeypatch.setattr(module, "_read", fail)
  with pytest.raises(RuntimeError): module.observe(NONCE)


@pytest.mark.parametrize("name", ["pid", "net", "user", "mnt", "ipc", "uts"])
def test_namespace_values_are_strict_and_do_not_expose_targets(case, monkeypatch, name):
  module, _, _ = case; values = module._namespace_links(); values[name] = "/private/namespace-target"
  monkeypatch.setattr(module, "_namespace_links", lambda: values)
  with pytest.raises(ValueError): module.observe(NONCE)


def test_successful_socket_creation_is_failure_and_socket_is_closed(case, monkeypatch):
  module, _, _ = case
  created = []
  class End:
    def close(self): created.append("closed")
  monkeypatch.setattr(module.socket, "socket", lambda *args: End())
  values = module.observe(NONCE)["observations"]
  assert not any(values[name] for name in ("inet_socket_denied", "inet6_socket_denied", "unix_socket_denied"))
  assert created == ["closed"] * 3


def test_socketpair_failure_closes_both_ends(case, monkeypatch):
  module, _, sockets = case
  original = module.socket.socketpair
  def pair():
    left, right = original()
    def fail(data): raise OSError(errno.EIO, "secret-socketpair")
    left.sendall = fail
    return left, right
  monkeypatch.setattr(module.socket, "socketpair", pair)
  assert not module.observe(NONCE)["observations"]["socketpair_works"]
  assert all(end.closed for end in sockets)


def test_actual_open_fds_ignores_only_closed_scan_fd(case, monkeypatch, tmp_path):
  module, _, _ = case
  fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  closed = os.dup(fd); os.close(closed)
  spec = importlib.util.spec_from_file_location("fd_probe_payload", SOURCE)
  actual = importlib.util.module_from_spec(spec); spec.loader.exec_module(actual)
  try:
    with monkeypatch.context() as scoped:
      scoped.setattr(actual.os, "listdir", lambda path: ["0", "1", "2", str(fd), str(closed)])
      assert actual._open_fds() == tuple(sorted((0, 1, 2, fd)))
  finally: os.close(fd)


def test_installed_location_defines_work_roots_and_bash_pwd(monkeypatch):
  spec = importlib.util.spec_from_file_location("dynamic_payload", SOURCE)
  value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
  expected = SOURCE.parent.parent
  assert value.WORK_ROOT == expected
  assert all(value.ROOTS[name] == expected / name for name in ("project", "readonly", "outside"))
  assert value.ROOTS["home"] == Path("/.rotom-shell/home") and value.ROOTS["tmp"] == Path("/tmp")
  env = {"HOME": "/.rotom-shell/home", "TMPDIR": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8", "TERM": "dumb", "PWD": str(expected / "project")}
  monkeypatch.setattr(value, "_environment", lambda: env)
  assert value._env_clean()
  env["PWD"] = "/work/project"
  assert not value._env_clean()
