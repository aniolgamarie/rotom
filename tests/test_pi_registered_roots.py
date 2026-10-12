"""非Git显式登记只验证临时账户锚，不授予Writer。"""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentcfg import cli
from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.storage import Conflict


@pytest.fixture(autouse=True)
def temporary_filesystem_git_boundary(tmp_path, monkeypatch):
  # 仅隔离自有探测seam；不修改真实/tmp标记，也不改变生产向上查找。
  import agentcfg.pi_registered_roots as module
  original = module._has_git_marker
  monkeypatch.setattr(module, "_has_git_marker", lambda path: original(path) if path.is_relative_to(tmp_path) else False)


@pytest.fixture
def roots(tmp_path):
  home = tmp_path / "account"
  home.mkdir(mode=0o700)
  root = tmp_path / "business"
  root.mkdir(mode=0o700)
  return RegisteredRoots(account_home=home), home, root


def test_missing_query_does_not_create(roots):
  registry, home, root = roots
  assert registry.list() == []
  assert registry.inspect(root)["status"] == "not-registered"
  assert list(home.iterdir()) == []


def test_alias_child_and_idempotent(roots):
  registry, home, root = roots
  first = registry.register(root)
  raw = (home / ".agentcfg-workspaces/registry.json").read_bytes()
  alias = root.parent / "alias"
  alias.symlink_to(root, target_is_directory=True)
  assert registry.register(alias) == first
  child = root / "child"
  child.mkdir()
  assert registry.inspect(child) == first
  assert (home / ".agentcfg-workspaces/registry.json").read_bytes() == raw
  inner = registry.register(child)
  assert inner["record"]["root_id"] != first["record"]["root_id"]
  assert registry.inspect(child) == inner
  first["record"]["root_id"] = "tampered"
  assert registry.inspect(root)["record"]["root_id"] != "tampered"


@pytest.mark.parametrize("fault", ["missing", "replacement"])
def test_diagnostics_preserve_changed_roots(roots, fault):
  registry, home, root = roots
  registry.register(root)
  root.rename(root.with_name("old"))
  if fault == "replacement": root.mkdir()
  expected = "missing" if fault == "missing" else "identity-changed"
  assert registry.list()[0]["status"] == expected
  assert registry.inspect(root)["status"] == expected
  with pytest.raises(Conflict): registry.register(root)


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "bool", "mode", "link", "extra", "anchor", "account"])
def test_corrupt_anchor_rejected(roots, fault):
  registry, home, root = roots
  registry.register(root)
  anchor = home / ".agentcfg-workspaces"
  path = anchor / "registry.json"
  data = json.loads(path.read_bytes())
  if fault == "unknown": data["unknown"] = True
  if fault == "bool": data["schema_version"] = True
  if fault in ("unknown", "bool"): path.write_text(json.dumps(data))
  if fault == "duplicate": path.write_text('{"schema_version":1,"schema_version":1}')
  if fault == "mode": path.chmod(0o644)
  if fault == "link": os.link(path, anchor / "other")
  if fault == "extra": (anchor / "extra").mkdir()
  if fault == "anchor": anchor.rename(home / "old"); anchor.mkdir(mode=0o700)
  if fault == "account": home.rename(home.with_name("old-account")); home.mkdir(mode=0o700)
  with pytest.raises(Conflict): registry.list()


@pytest.mark.parametrize("target", ["home", "ancestor", "anchor", "descendant", "git", "missing", "control"])
def test_forbidden_registration(roots, target):
  registry, home, root = roots
  if target == "home": path = home
  if target == "ancestor": path = home.parent
  if target in ("anchor", "descendant"):
    registry.register(root)
    path = home / ".agentcfg-workspaces"
    if target == "descendant": path = path / "child"; path.mkdir()
  if target == "git": (root / ".git").symlink_to(root / "absent"); path = root
  if target == "missing": path = root / "missing"
  if target == "control": path = str(root) + "\n"
  with pytest.raises(Conflict): registry.register(path)


def test_default_uses_passwd_and_ignores_environment(roots, monkeypatch):
  registry, home, root = roots
  import agentcfg.pi_registered_roots as module
  monkeypatch.setattr(module.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(home)))
  monkeypatch.setenv("HOME", "/unavailable")
  monkeypatch.setenv("XDG_CONFIG_HOME", "/unavailable")
  assert RegisteredRoots().register(root) == registry.inspect(root)


def test_busy_and_unsupported_flock(roots, monkeypatch):
  registry, home, root = roots
  import agentcfg.pi_registered_roots as module
  for error in (BlockingIOError(), OSError()):
    def busy(*args): raise error
    with monkeypatch.context() as patch:
      patch.setattr(module.fcntl, "flock", busy)
      with pytest.raises(Conflict): registry.register(root)
  assert list(home.iterdir()) == []


def test_cli_without_selection_or_secret_loading(roots, monkeypatch, capsys):
  registry, home, root = roots
  import agentcfg.pi_registered_roots as module
  monkeypatch.setattr(module, "RegisteredRoots", lambda: registry)
  monkeypatch.setattr(cli, "resolve_selection", lambda args: pytest.fail("selection read"))
  assert cli.main(["workspace", "register", "--path", str(root), "--format", "json"]) == 0
  assert json.loads(capsys.readouterr().out)["status"] == "current"
  before = (home / ".agentcfg-workspaces/registry.json").read_bytes()
  assert cli.main(["workspace", "inspect", "--path", str(root), "--format", "json"]) == 0
  assert json.loads(capsys.readouterr().out) == registry.inspect(root)
  assert (home / ".agentcfg-workspaces/registry.json").read_bytes() == before
  assert cli.main(["workspace", "list", "--format", "json"]) == 0
  for selector in ("--local", "--machine", "--profile"):
    with pytest.raises(SystemExit) as error: cli.build_parser().parse_args([selector, "unread", "workspace", "list"])
    assert error.value.code == 2


@pytest.mark.parametrize("fault", ["unsafe-home", "unsafe-root", "anchor-symlink", "record-symlink", "large", "duplicate-root", "identity-bool", "digest"])
def test_additional_private_boundaries(roots, fault, tmp_path):
  registry, home, root = roots
  if fault == "unsafe-home":
    home.chmod(0o777)
    with pytest.raises(Conflict): registry.list()
    return
  if fault == "unsafe-root":
    root.chmod(0o777)
    with pytest.raises(Conflict): registry.register(root)
    return
  if fault == "anchor-symlink":
    (home / ".agentcfg-workspaces").symlink_to(root)
    with pytest.raises(Conflict): registry.list()
    return
  registry.register(root)
  path = home / ".agentcfg-workspaces/registry.json"
  data = json.loads(path.read_bytes())
  if fault == "record-symlink":
    backup = tmp_path / "backup"
    path.rename(backup); path.symlink_to(backup)
  if fault == "large": path.write_bytes(b" " * (1024 * 1024 + 1))
  if fault == "duplicate-root": data["roots"].append(data["roots"][0])
  if fault == "identity-bool": data["roots"][0]["filesystem_identity"]["uid"] = True
  if fault == "digest": data["roots"][0]["root_id"] = "f" * 64
  if fault in ("duplicate-root", "identity-bool", "digest"): path.write_text(json.dumps(data))
  with pytest.raises(Conflict): registry.list()


def test_exact_permissions_and_unrelated_siblings(roots):
  registry, home, root = roots
  registry.register(root)
  anchor = home / ".agentcfg-workspaces"
  assert anchor.stat().st_mode & 0o777 == 0o700
  assert (anchor / "registry.json").stat().st_mode & 0o777 == 0o600
  sibling = home / "unrelated-business"
  sibling.mkdir(mode=0o700)
  assert registry.register(sibling)["status"] == "current"


def test_missing_registry_cannot_be_recreated(roots):
  registry, home, root = roots
  registry.register(root)
  (home / ".agentcfg-workspaces/registry.json").unlink()
  with pytest.raises(Conflict): registry.register(root)
  assert not (home / ".agentcfg-workspaces/registry.json").exists()


def test_single_link_requirement_even_without_unknown_anchor_content(roots):
  registry, home, root = roots
  registry.register(root)
  os.link(home / ".agentcfg-workspaces/registry.json", root / "outside-link")
  with pytest.raises(Conflict): registry.list()


@pytest.mark.parametrize("level", ["root", "parent", "temporary-root"])
@pytest.mark.parametrize("kind", ["directory", "broken-symlink"])
def test_git_markers_at_each_real_temporary_ancestor(roots, tmp_path, level, kind):
  registry, home, root = roots
  child = root / "deep" / "child"
  child.mkdir(parents=True)
  directory = {"root": child, "parent": root, "temporary-root": tmp_path}[level]
  marker = directory / ".git"
  if kind == "directory": marker.mkdir()
  else: marker.symlink_to(directory / "absent")
  with pytest.raises(Conflict): registry.register(child)
  assert list(home.iterdir()) == []


def test_production_search_reaches_external_ancestor(roots, tmp_path, monkeypatch):
  registry, home, root = roots
  import agentcfg.pi_registered_roots as module
  visited = []
  external = tmp_path.parent
  def marker(directory):
    visited.append(directory)
    return directory == external
  monkeypatch.setattr(module, "_has_git_marker", marker)
  with pytest.raises(Conflict): registry.register(root)
  assert external in visited and visited[:2] == [root, tmp_path]
  assert list(home.iterdir()) == []


def test_sticky_account_is_not_a_safe_anchor(roots):
  registry, home, root = roots
  home.chmod(0o1777)
  with pytest.raises(Conflict): registry.list()
  with pytest.raises(Conflict): RegisteredRoots(account_home=home)


def test_inode_zero_rejected(roots):
  registry, home, root = roots
  registry.register(root)
  path = home / ".agentcfg-workspaces/registry.json"
  data = json.loads(path.read_bytes())
  data["roots"][0]["filesystem_identity"]["inode"] = 0
  path.write_text(json.dumps(data))
  with pytest.raises(Conflict): registry.list()


@pytest.mark.parametrize("ancestor", [False, True])
def test_non_git_record_changes_when_git_marker_appears(roots, ancestor):
  registry, home, root = roots
  registered = registry.register(root)
  (root.parent if ancestor else root).joinpath(".git").mkdir()
  assert registry.list() == [{"record": registered["record"], "status": "identity-changed"}]
  assert registry.inspect(root)["status"] == "identity-changed"
  with pytest.raises(Conflict): registry.register(root)


@pytest.mark.parametrize("alias", [False, True])
def test_first_registration_inside_home(roots, alias):
  registry, home, _ = roots
  business = home / "notes"
  business.mkdir(mode=0o700)
  target = business
  if alias:
    target = home / "notes-alias"
    target.symlink_to(business, target_is_directory=True)
  observed = registry.register(target)
  assert observed["status"] == "current"
  assert observed["record"]["canonical_path"] == str(business)
  assert registry.inspect(business) == observed


@pytest.mark.parametrize("replacement", [False, True])
def test_unrelated_registration_preserves_unavailable_record(roots, replacement):
  registry, home, root = roots
  old = registry.register(root)
  root.rename(root.with_name("old-business"))
  if replacement: root.mkdir(mode=0o700)
  sibling = root.parent / "new-business"
  sibling.mkdir(mode=0o700)
  new = registry.register(sibling)
  status = "identity-changed" if replacement else "missing"
  assert registry.list() == [{"record": old["record"], "status": status}, new]
  with pytest.raises(Conflict): registry.register(root)
  assert registry.inspect(root)["status"] == status


def test_moved_original_physical_root_cannot_be_rebound(roots):
  registry, home, root = roots
  registry.register(root)
  moved = root.with_name("moved-business")
  root.rename(moved)
  with pytest.raises(Conflict): registry.register(moved)
  assert registry.list()[0]["status"] == "missing"
