"""CLI-02：仅初始化框架 TOML，不解析 profile、部署或读取原生凭据。"""

import errno
import os
from pathlib import Path
import stat
import tomllib
import traceback

import pytest

from agentcfg import cli
from agentcfg.config import load_local, load_sources, resolve_config, SourceInputs
from agentcfg.schema import AdapterSchemas, ConfigError, validate_document


CANARY = "synthetic-private-init-canary"
REPOSITORY = Path(__file__).resolve().parents[1]


def destination(machine="work"):
  return Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg/machines" / f"{machine}.toml"


def initialize(machine="work", *, config_home=None):
  from agentcfg.local import initialize_local
  return initialize_local(machine, config_home=config_home or os.environ["XDG_CONFIG_HOME"])


def test_init_local_creates_schema_valid_private_file_without_catalog(isolated_environment, capsys):
  cwd = Path.cwd()
  assert cli.main(["init-local", "--machine", "work"]) == 0
  path = destination()
  document = tomllib.loads(path.read_text(encoding="utf-8"))
  assert document == {
    "schema_version": 1,
    "machine": {"id": "work", "default_profile": "dsh-default"},
    "secrets": {},
  }
  validate_document("local", document)
  local, secrets = load_local(path)
  catalog = load_sources(SourceInputs(), adapter_schemas=AdapterSchemas())
  with pytest.raises(ConfigError):
    resolve_config(catalog, local, profile_id="dsh-default", adapter_schemas=AdapterSchemas())
  assert stat.S_IMODE(path.stat().st_mode) == 0o600
  assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
  assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
  assert Path.cwd() == cwd
  assert "尚未实现" not in capsys.readouterr().err
  assert not (isolated_environment.home / "data/agentcfg").exists()


@pytest.mark.parametrize("xdg", [None, "", "missing"])
@pytest.mark.parametrize("mask", [0o000, 0o077, 0o277])
def test_init_local_missing_hierarchy_and_umask(xdg, mask, isolated_environment, monkeypatch):
  home = isolated_environment.home / "新的 HOME"
  monkeypatch.setenv("HOME", str(home))
  if xdg is None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
  else:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "中文 配置/deeper") if xdg else "")
  root = home / "中文 配置/deeper" if xdg == "missing" else home / ".config"
  previous = os.umask(mask)
  try:
    assert cli.main(["init-local", "--machine", "中文 机器"]) == 0
  finally:
    os.umask(previous)
  for path in (home, *home.rglob("*")):
    assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
  assert (root / "agentcfg/machines/中文 机器.toml").exists()


@pytest.mark.parametrize("machine", ['quote"name', "中文 空格", "literal'$()`name", "emoji-😀"])
def test_init_local_ids_roundtrip_as_literal_toml(machine):
  assert initialize(machine) is None
  assert tomllib.loads(destination(machine).read_text(encoding="utf-8"))["machine"]["id"] == machine


def test_init_local_repeat_preserves_modified_bytes_mode_without_read(monkeypatch, sentinel_factory):
  initialize()
  path = destination()
  path.write_bytes(CANARY.encode() + b"\xff")
  path.chmod(0o640)
  before = sentinel_factory(path)
  real_open = os.open
  def no_read(path, flags, *args, **kwargs):
    assert flags & os.O_DIRECTORY or flags & os.O_WRONLY
    return real_open(path, flags, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Path, "open", lambda *a, **k: pytest.fail("must not read"))
    patch.setattr(os, "open", no_read)
    patch.setattr(os, "read", lambda *a, **k: pytest.fail("must not read"))
    assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()


def test_init_local_second_machine_reuses_containers_not_deployment_ownership(monkeypatch, sentinel_factory):
  from agentcfg.paths import PrivateDirectory
  initialize("first")
  before = sentinel_factory(destination("first"))
  monkeypatch.setattr(PrivateDirectory, "open_owned", lambda *a, **k: pytest.fail("not ownership proof"))
  initialize("second")
  before.assert_unchanged()
  assert sorted(path.name for path in destination().parent.iterdir()) == ["first.toml", "second.toml"]
  assert sorted(path.name for path in destination().parent.parent.iterdir()) == ["machines"]


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "broken", "fifo", "hardlink"])
def test_init_local_existing_target_always_conflicts(kind, isolated_environment, sentinel_factory):
  initialize("first")
  path = destination()
  outside = isolated_environment.home / "existing-private"
  outside.write_bytes(CANARY.encode())
  if kind == "file":
    path.write_bytes(CANARY.encode())
  elif kind == "directory":
    path.mkdir()
  elif kind == "symlink":
    path.symlink_to(outside)
  elif kind == "broken":
    path.symlink_to(outside.with_name("missing"))
  elif kind == "fifo":
    os.mkfifo(path)
  else:
    os.link(outside, path)
  before = sentinel_factory(path)
  outside_before = sentinel_factory(outside)
  assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()
  outside_before.assert_unchanged()


@pytest.mark.parametrize("position", ["home", "ancestor", "config", "agentcfg", "machines"])
@pytest.mark.parametrize("broken", [False, True])
def test_init_local_rejects_every_symlink_component(position, broken, isolated_environment, monkeypatch, sentinel_factory):
  base = isolated_environment.home / "test-home"
  root = base / "ancestor/config"
  positions = {
    "home": base, "ancestor": base / "ancestor", "config": root,
    "agentcfg": root / "agentcfg", "machines": root / "agentcfg/machines",
  }
  link = positions[position]
  link.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
  if position == "machines":
    link.parent.chmod(0o700)
  outside = isolated_environment.home / "symlink-outside"
  if not broken:
    outside.mkdir(mode=0o700)
  link.symlink_to(outside, target_is_directory=True)
  monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
  before = sentinel_factory(outside)
  assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()
  assert link.is_symlink()


@pytest.mark.parametrize("position,mode", [
  ("ancestor", 0o777), ("config", 0o777), ("config", 0o1777),
  ("agentcfg", 0o755), ("agentcfg", 0o1700), ("machines", 0o750), ("machines", 0o770),
])
def test_init_local_unsafe_containers_not_repaired(position, mode, isolated_environment, monkeypatch, sentinel_factory):
  ancestor = isolated_environment.home / "ancestor"
  root = ancestor / "config"
  namespace = root / "agentcfg"
  machines = namespace / "machines"
  machines.mkdir(parents=True, mode=0o700)
  namespace.chmod(0o700)
  selected = {"ancestor": ancestor, "config": root, "agentcfg": namespace, "machines": machines}[position]
  selected.chmod(mode)
  monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
  before = sentinel_factory(ancestor)
  assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()


@pytest.mark.parametrize("position", ["config", "agentcfg", "machines"])
def test_init_local_foreign_owner_conflicts(position, monkeypatch, sentinel_factory):
  initialize("first")
  root = destination().parent.parent.parent
  target = {"config": root, "agentcfg": root / "agentcfg", "machines": root / "agentcfg/machines"}[position]
  identity = target.stat().st_ino
  before = sentinel_factory(root)
  real_fstat = os.fstat
  def foreign(fd):
    info = real_fstat(fd)
    if info.st_ino == identity:
      values = list(info)
      values[4] = os.geteuid() + 1000
      return os.stat_result(values)
    return info
  monkeypatch.setattr(os, "fstat", foreign)
  assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()


@pytest.mark.parametrize("relative", [".", "new-private/config", "src/agentcfg"])
def test_init_local_repository_destination_refused_before_writes(relative, monkeypatch):
  root = REPOSITORY / relative
  monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
  monkeypatch.setattr(os, "mkdir", lambda *a, **k: pytest.fail("repository write"))
  monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("repository traversal"))
  assert cli.main(["init-local", "--machine", "work"]) == 4


@pytest.mark.parametrize("machine", ["", ".", "..", "a/b", "a\\b", "bad\n", "bad\x00", "bad\x7f", "bad\ud800", None])
def test_init_local_invalid_id_is_typed_sanitized_no_mutation(machine, monkeypatch):
  from agentcfg.local import InitializationError
  monkeypatch.setattr(os, "mkdir", lambda *a, **k: pytest.fail("invalid input wrote"))
  with pytest.raises(InitializationError) as caught:
    initialize(machine)
  assert caught.value.exit_code == 2


@pytest.mark.parametrize("value", ["relative", "~other/config", "/bad/../config", "/$HOME/config", "/bad\n"])
def test_init_local_invalid_config_path_is_usage(value, monkeypatch, capsys):
  monkeypatch.setenv("XDG_CONFIG_HOME", value)
  monkeypatch.setattr(os, "mkdir", lambda *a, **k: pytest.fail("invalid input wrote"))
  assert cli.main(["init-local", "--machine", "work"]) == 2
  assert value not in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "/bad\ud800", None, 123])
def test_init_local_invalid_api_config_path(value, monkeypatch):
  from agentcfg.local import InitializationError, initialize_local
  monkeypatch.setattr(os, "mkdir", lambda *a, **k: pytest.fail("invalid input wrote"))
  with pytest.raises(InitializationError) as caught:
    initialize_local("work", config_home=value)
  assert caught.value.exit_code == 2


@pytest.mark.parametrize("operation", ["mkdir", "open", "write", "fchmod", "fstat"])
def test_init_local_io_failures_close_all_fds_and_are_sanitized(operation, monkeypatch, capsys):
  from agentcfg.local import InitializationError
  opened = set()
  real_open, real_close = os.open, os.close
  def tracked_open(*args, **kwargs):
    if operation == "open" and args[0] == "work.toml":
      raise PermissionError(CANARY)
    fd = real_open(*args, **kwargs)
    opened.add(fd)
    return fd
  def tracked_close(fd):
    real_close(fd)
    opened.discard(fd)
  real_operation = getattr(os, operation)
  def denied(*args, **kwargs):
    if operation == "fstat" and len(opened) < 2:
      return real_operation(*args, **kwargs)
    raise OSError(errno.EACCES, CANARY)
  with monkeypatch.context() as patch:
    patch.setattr(os, "open", tracked_open)
    patch.setattr(os, "close", tracked_close)
    if operation != "open":
      patch.setattr(os, operation, denied)
    with pytest.raises(InitializationError) as caught:
      initialize()
    assert caught.value.exit_code == 6
    assert CANARY not in "".join(traceback.format_exception(caught.value))
    assert not opened
  # 部分失败不是事务；只留下本次新建对象，不删除或修复已有内容。
  if operation == "write":
    assert destination().read_bytes() == b""
    assert stat.S_IMODE(destination().stat().st_mode) == 0o600


@pytest.mark.parametrize("loop", ["config-home", "namespace"])
def test_init_local_parent_close_failure_releases_child(loop, isolated_environment, monkeypatch, sentinel_factory, capsys):
  initialize("first")
  before = sentinel_factory(isolated_environment.home)
  root = Path(os.environ["XDG_CONFIG_HOME"])
  target = root.name if loop == "config-home" else "agentcfg"
  opened = set()
  parent_fd = child_fd = None
  parent_close_attempts = 0
  injected = False
  real_open, real_close = os.open, os.close
  def tracked_open(path, flags, *args, **kwargs):
    nonlocal parent_fd, child_fd
    fd = real_open(path, flags, *args, **kwargs)
    opened.add(fd)
    if path == target:
      parent_fd, child_fd = kwargs["dir_fd"], fd
    return fd
  def tracked_close(fd):
    nonlocal injected, parent_close_attempts
    if fd == parent_fd:
      parent_close_attempts += 1
    real_close(fd)
    opened.discard(fd)
    if fd == parent_fd and not injected:
      injected = True
      raise OSError(errno.EIO, CANARY)
  try:
    with monkeypatch.context() as patch:
      patch.setattr(os, "open", tracked_open)
      patch.setattr(os, "close", tracked_close)
      assert cli.main(["init-local", "--machine", "work"]) == 6
    assert injected
    assert child_fd is not None
    assert CANARY not in capsys.readouterr().err
    before.assert_unchanged()
    assert not opened
    assert parent_close_attempts == 1
    with pytest.raises(OSError) as caught:
      os.fstat(child_fd)
    assert caught.value.errno == errno.EBADF
  finally:
    # 红灯验证也释放泄漏句柄，避免影响后续测试。
    for fd in opened:
      real_close(fd)


@pytest.mark.parametrize("written", ["short", "zero", "failure"])
def test_init_local_cli_write_results(written, monkeypatch, capsys):
  real_write = os.write
  def write(fd, data):
    if written == "zero":
      return 0
    if written == "failure":
      raise OSError(CANARY)
    return real_write(fd, data[:2])
  monkeypatch.setattr(os, "write", write)
  assert cli.main(["init-local", "--machine", "work"]) == (0 if written == "short" else 6)
  assert CANARY not in capsys.readouterr().err
  if written == "short":
    assert tomllib.loads(destination().read_text())["machine"]["id"] == "work"


def test_init_local_repository_double_slash_refused(monkeypatch):
  monkeypatch.setenv("XDG_CONFIG_HOME", "/" + str(REPOSITORY / "new-private"))
  monkeypatch.setattr(os, "mkdir", lambda *a, **k: pytest.fail("repository write"))
  monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("repository traversal"))
  assert cli.main(["init-local", "--machine", "work"]) == 4


def test_init_local_first_creation_never_reads_credentials(monkeypatch):
  real_open = os.open
  def no_read(path, flags, *args, **kwargs):
    assert flags & os.O_DIRECTORY or flags & os.O_WRONLY
    return real_open(path, flags, *args, **kwargs)
  monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("must not read"))
  monkeypatch.setattr(os, "open", no_read)
  monkeypatch.setattr(os, "read", lambda *a, **k: pytest.fail("must not read"))
  assert cli.main(["init-local", "--machine", "work"]) == 0


@pytest.mark.parametrize("position", ["agentcfg", "machines"])
def test_init_local_regular_file_namespace_is_not_adopted(position, sentinel_factory):
  root = Path(os.environ["XDG_CONFIG_HOME"])
  if position == "machines":
    (root / "agentcfg").mkdir(mode=0o700)
    target = root / "agentcfg/machines"
  else:
    target = root / "agentcfg"
  target.write_bytes(CANARY.encode())
  before = sentinel_factory(root)
  assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()


@pytest.mark.parametrize("race", ["file", "directory-open", "directory-create", "identity"])
def test_init_local_races_never_follow_links(race, isolated_environment, monkeypatch, sentinel_factory):
  initialize("first")
  root = destination().parent.parent
  outside = isolated_environment.home / "race-outside"
  outside.mkdir(mode=0o700)
  before = sentinel_factory(outside)
  real_open, real_mkdir = os.open, os.mkdir
  if race == "directory-create":
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root.parent / "new-config"))
  def racing_open(path, flags, mode=0o777, *, dir_fd=None):
    if race == "file" and path == "work.toml":
      os.symlink(outside / "new", path, dir_fd=dir_fd)
    elif race in ("directory-open", "identity") and path == "machines":
      os.rename(path, "old-machines", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
      if race == "identity":
        real_mkdir(path, 0o700, dir_fd=dir_fd)
      else:
        os.symlink(outside, path, dir_fd=dir_fd)
    return real_open(path, flags, mode, dir_fd=dir_fd)
  def racing_mkdir(path, mode=0o777, *, dir_fd=None):
    real_mkdir(path, mode, dir_fd=dir_fd)
    if path == "agentcfg":
      os.rename(path, "old-agentcfg", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
      os.symlink(outside, path, dir_fd=dir_fd)
  monkeypatch.setattr(os, "open", racing_open)
  if race == "directory-create":
    monkeypatch.setattr(os, "mkdir", racing_mkdir)
  assert cli.main(["init-local", "--machine", "work"]) == 4
  before.assert_unchanged()


def test_init_local_inaccessible_new_directory_not_repaired(monkeypatch):
  if os.geteuid() == 0:
    pytest.skip("root 可绕过目录访问权限")
  target = Path(os.environ["XDG_CONFIG_HOME"]) / "agentcfg"
  previous = os.umask(0o777)
  try:
    assert cli.main(["init-local", "--machine", "work"]) == 6
    assert stat.S_IMODE(target.stat().st_mode) == 0
  finally:
    os.umask(previous)
    # 仅恢复测试新建目录供 pytest 清理；生产初始化不修复权限。
    target.chmod(0o700)


@pytest.mark.parametrize("home", [None, "relative-home"])
def test_init_local_invalid_home_never_uses_real_home(home, monkeypatch):
  monkeypatch.delenv("XDG_CONFIG_HOME")
  if home is None:
    monkeypatch.delenv("HOME")
  else:
    monkeypatch.setenv("HOME", home)
  monkeypatch.setattr(os, "mkdir", lambda *a, **k: pytest.fail("invalid HOME wrote"))
  assert cli.main(["init-local", "--machine", "work"]) == 2
