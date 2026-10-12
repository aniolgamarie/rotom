"""只读挂载计划的真实目录与合成mountinfo；不执行mount/helper/Shell。"""

from copy import deepcopy
import os
from pathlib import Path

import pytest

from agentcfg.pi_shell_mounts import compile_mount_plan, parse_mountinfo
from agentcfg.pi_shell_preparation import prepare_shell
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_shell_preparation import shell_case, file_deny


def public(case):
  value = prepare_shell(**case)
  return {key: value[key] for key in ("resolution", "physical")}


def escaped(path):
  return str(path).replace("\\", "\\134").replace(" ", "\\040")


def mount_row(mount_id, mountpoint, *, root="/", parent=1, device=None, flags="rw", super_flags="rw"):
  info = Path(mountpoint).stat()
  device = device or str(os.major(info.st_dev)) + ":" + str(os.minor(info.st_dev))
  return f"{mount_id} {parent} {device} {escaped(root)} {escaped(mountpoint)} {flags},relatime - ext4 ignored {super_flags}\n"


def baseline(case):
  result = mount_row(1, "/")
  # 私有tmpfs夹具与根文件系统可能不同；合成表保留真实device边界。
  current = Path(case["cwd"]).resolve(strict=True)
  device = current.stat().st_dev
  if device != Path("/").stat().st_dev:
    while current.parent != current and current.parent.stat().st_dev == device:
      current = current.parent
    # 合成权威保留旧绝对逻辑坐标；不是对/proc真实mount root的声明。
    result += mount_row(999999, current, root=str(current))
  return result


def plan(case, **kwargs):
  return compile_mount_plan(public(case), system_roots=(), mountinfo=baseline(case), **kwargs)


def test_minimal_project_plan_is_deterministic_and_has_no_side_effects(shell_case, tmp_path, sentinel_factory):
  project = Path(shell_case["cwd"])
  (project / "code.cpp").write_text("int main() {}")
  sentinel = sentinel_factory(tmp_path)
  result = plan(shell_case)
  assert result == plan(shell_case)
  assert result["network"] == "deny" and result["platform"] == "linux-x86_64"
  assert len(result["seccomp_digest"]) == 64
  project_mount = next(row for row in result["mounts"] if row["path"] == str(project))
  assert project_mount["writable"] is True
  assert result["masks"] == [] and result["symlinks"] == []
  assert all(row["path"] != "/" for row in result["mounts"])
  assert result["cwd"]["path"] == str(project)
  sentinel.assert_unchanged()


def test_nested_git_file_directory_and_explicit_denial_are_masked(shell_case):
  project = Path(shell_case["cwd"])
  (project / ".git").mkdir()
  (project / "sub").mkdir(); (project / "sub/.git").write_text("gitdir: elsewhere")
  (project / "private").mkdir(); (project / "private/secret").write_text("do not read")
  shell_case["permission_policy"]["rules"].append(file_deny("project", "private"))
  result = plan(shell_case)
  assert {(row["path"], row["kind"]) for row in result["masks"]} == {
    (str(project / ".git"), "directory"), (str(project / "sub/.git"), "file"), (str(project / "private"), "directory")}


@pytest.mark.parametrize("kind", ["symlink-git", "hardlink", "fifo"])
def test_unrepresentable_workspace_objects_refuse_entire_plan(shell_case, kind):
  project = Path(shell_case["cwd"])
  if kind == "symlink-git":
    (project / "sub").mkdir(); (project / "sub/.git").symlink_to("/outside")
  elif kind == "hardlink":
    (project / "one").write_text("alias"); os.link(project / "one", project / "two")
  else: os.mkfifo(project / "pipe")
  with pytest.raises((ConfigError, Conflict)): plan(shell_case)


def test_recursive_submount_is_rejected_instead_of_inherited(shell_case):
  project = Path(shell_case["cwd"]); child = project / "nested"; child.mkdir()
  info = baseline(shell_case) + mount_row(2, child, root="/other")
  with pytest.raises(Conflict, match="SUBMOUNT"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_bind_alias_maps_denial_to_visible_path(shell_case):
  project = Path(shell_case["cwd"])
  (project / "restricted").mkdir()
  value = public(shell_case)
  original = str(project.parent / "original")
  value["physical"]["denied_paths"] = [original + "/restricted"]
  info = baseline(shell_case) + mount_row(2, project, root=original)
  result = compile_mount_plan(value, system_roots=(), mountinfo=info)
  assert [row["path"] for row in result["masks"]] == [str(project / "restricted")]


def test_denial_covering_physical_alias_root_is_rejected(shell_case):
  original = str(Path(shell_case["cwd"]).parent / "original")
  value = public(shell_case); value["physical"]["denied_paths"] = [original]
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=original + "/sub")
  with pytest.raises(Conflict): compile_mount_plan(value, system_roots=(), mountinfo=info)


def test_missing_or_symlink_mask_never_creates_a_target(shell_case, tmp_path, sentinel_factory):
  value = public(shell_case)
  value["physical"]["denied_paths"] = [str(Path(shell_case["cwd"]) / "missing")]
  sentinel = sentinel_factory(tmp_path)
  with pytest.raises((ConfigError, Conflict)):
    compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  sentinel.assert_unchanged()


def test_system_aliases_are_recreated_and_writes_cannot_cover_them(shell_case, tmp_path):
  system = tmp_path / "system"; system.mkdir(); (system / "bin").mkdir()
  alias = tmp_path / "bin-alias"; alias.symlink_to(system / "bin")
  result = compile_mount_plan(public(shell_case), system_roots=(str(system), str(alias)), mountinfo=baseline(shell_case))
  assert result["symlinks"] == [{"path": str(alias), "target": str(system / "bin")}]
  assert next(row for row in result["mounts"] if row["path"] == str(system))["writable"] is False
  shell_case["declared_roots"]["system"] = {"path": str(system), "purpose": "write"}
  shell_case["binding"]["write_roots"].append("system")
  with pytest.raises(Conflict):
    compile_mount_plan(public(shell_case), system_roots=(str(system), str(alias)), mountinfo=baseline(shell_case))


def test_writable_child_under_read_root_and_read_child_under_write_root(shell_case):
  project = Path(shell_case["cwd"]); child = project / "child"; child.mkdir()
  shell_case["declared_roots"]["child"] = {"path": str(child), "purpose": "write"}
  shell_case["binding"]["read_roots"].append("child")
  result = plan(shell_case)
  assert next(row for row in result["mounts"] if row["path"] == str(child))["writable"] is True
  shell_case["binding"]["write_roots"] = ["child"]
  result = plan(shell_case)
  assert next(row for row in result["mounts"] if row["path"] == str(project))["writable"] is False
  assert next(row for row in result["mounts"] if row["path"] == str(child))["writable"] is True


def test_readonly_source_and_broad_home_ancestor_fail(shell_case, tmp_path):
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], flags="ro")
  with pytest.raises(Conflict): compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)
  with pytest.raises(Conflict): compile_mount_plan(public(shell_case), system_roots=(str(tmp_path),), mountinfo=baseline(shell_case))


@pytest.mark.parametrize("raw", ["", "broken", "1 1 1:2 / / rw - ext4 source rw\n1 1 1:2 / / rw - ext4 source rw\n", "1 1 1:2 / / rw odd:2 - ext4 source rw\n", "1 1 1:2 / /bad\\099 rw - ext4 source rw\n"])
def test_mountinfo_is_closed_and_escaped_fields_are_checked(raw):
  with pytest.raises(ConfigError): parse_mountinfo(raw)


def test_mountinfo_discards_unneeded_source_and_super_options():
  result = parse_mountinfo("1 1 1:2 / / rw shared:2 - ext4 private-source rw,sensitive-option\n")
  assert "private-source" not in repr(result) and "sensitive-option" not in repr(result)


def test_inventory_limit_fails_without_partial_plan(shell_case):
  (Path(shell_case["cwd"]) / "one").write_text("one")
  (Path(shell_case["cwd"]) / "two").write_text("two")
  with pytest.raises(Conflict, match="INVENTORY_LIMIT"): plan(shell_case, max_entries=1)


@pytest.mark.parametrize("home_kind", ["environment", "passwd"])
def test_home_backing_alias_cannot_be_mounted_as_project(shell_case, home_kind):
  import pwd
  home = os.environ["HOME"] if home_kind == "environment" else pwd.getpwuid(os.geteuid()).pw_dir
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=home)
  with pytest.raises(Conflict, match="MOUNT_SCOPE"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_system_readonly_root_cannot_be_covered_by_physical_write_alias(shell_case, tmp_path):
  system = tmp_path / "system"; system.mkdir()
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=str(system))
  with pytest.raises(Conflict, match="SYSTEM_WRITE"):
    compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=info)


def test_system_alias_denial_maps_to_selected_real_directory(shell_case, tmp_path):
  system = tmp_path / "system"; system.mkdir(); (system / "private").mkdir()
  alias = tmp_path / "system-alias"; alias.symlink_to(system)
  value = public(shell_case); value["physical"]["denied_paths"] = [str(alias / "private")]
  result = compile_mount_plan(value, system_roots=(str(system), str(alias)), mountinfo=baseline(shell_case))
  assert [row["path"] for row in result["masks"]] == [str(system / "private")]


@pytest.mark.parametrize("target", ["cwd", "executable"])
def test_cwd_and_executable_must_stay_outside_masks(shell_case, target):
  value = public(shell_case)
  path = value["physical"]["cwd"] if target == "cwd" else value["physical"]["executable_identity"]["path"]
  value["physical"]["denied_paths"] = [path]
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))


def test_denial_projects_into_every_visible_directory_backing_alias(shell_case):
  project = Path(shell_case["cwd"]); alias = project.parent / "read-alias"; alias.mkdir()
  (project / "private").mkdir(); (alias / "private").mkdir()
  shell_case["declared_roots"]["alias"] = {"path": str(alias), "purpose": "read"}
  shell_case["binding"]["read_roots"].append("alias")
  original = str(project.parent / "original")
  value = public(shell_case); value["physical"]["denied_paths"] = [original + "/private"]
  info = baseline(shell_case) + mount_row(2, project, root=original) + mount_row(3, alias, root=original)
  result = compile_mount_plan(value, system_roots=(), mountinfo=info)
  assert {row["path"] for row in result["masks"]} == {str(project / "private"), str(alias / "private")}


def test_source_fd_device_must_match_mountinfo(shell_case):
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], device="123:456")
  with pytest.raises(Conflict, match="MOUNT_DEVICE"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_workspace_symlink_is_not_followed_and_deny_subtree_not_inventoried(shell_case, monkeypatch):
  project = Path(shell_case["cwd"])
  hidden = project / "hidden"; hidden.mkdir(); os.mkfifo(hidden / "forbidden-if-scanned")
  (project / "shortcut").symlink_to(hidden)
  shell_case["permission_policy"]["rules"].append(file_deny("project", "hidden"))
  original = os.scandir
  visited = []
  hidden_info = hidden.stat()
  def guarded(fd):
    assert type(fd) is int
    info = os.fstat(fd)
    assert (info.st_dev, info.st_ino) != (hidden_info.st_dev, hidden_info.st_ino)
    visited.append(fd)
    return original(fd)
  monkeypatch.setattr(os, "scandir", guarded)
  assert plan(shell_case)["masks"] and visited


def test_parent_mask_removes_redundant_child_mask(shell_case):
  project = Path(shell_case["cwd"]); hidden = project / "hidden"; hidden.mkdir(); (hidden / "nested").mkdir()
  value = public(shell_case)
  value["physical"]["denied_paths"] = [str(hidden / "nested"), str(hidden), str(hidden)]
  result = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  assert [row["path"] for row in result["masks"]] == [str(hidden)]


def test_mutation_during_fd_inventory_refuses_partial_plan(shell_case, monkeypatch):
  project = Path(shell_case["cwd"])
  original = os.scandir
  mutated = False
  def changed(fd):
    nonlocal mutated
    result = original(fd)
    if not mutated:
      (project / "changed").mkdir()
      mutated = True
    return result
  monkeypatch.setattr(os, "scandir", changed)
  with pytest.raises(Conflict, match="ROOT_IDENTITY"): plan(shell_case)


def test_inventory_depth_is_bounded(shell_case):
  path = Path(shell_case["cwd"])
  for _ in range(129):
    path /= "d"
    path.mkdir()
  with pytest.raises(Conflict, match="INVENTORY_LIMIT"): plan(shell_case)


def test_normal_project_below_separate_tmp_mount_is_allowed(shell_case):
  info = baseline(shell_case) + mount_row(2, "/tmp", root="/")
  assert compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)["mounts"]


@pytest.mark.parametrize("platform_id,machine", [("darwin", "x86_64"), ("linux", "aarch64")])
def test_mount_topology_requires_actual_linux_x86_64(shell_case, monkeypatch, platform_id, machine):
  import agentcfg.pi_shell_mounts as module
  monkeypatch.setattr(module.sys, "platform", platform_id)
  monkeypatch.setattr(module.platform, "machine", lambda: machine)
  with pytest.raises(ConfigError, match="mount-platform"): plan(shell_case)


@pytest.mark.parametrize("raw", [
  "1 1 1:2 / / ro,rw - ext4 source rw\n",
  "1 1 1:2 / / relatime - ext4 source rw\n",
  "1 1 1:2 / / rw - ext4 source rw\n1 1 1:2 / / rw - ext4 source rw\n",
  "1 1 1:2 / / rw shared:1 shared:2 - ext4 source rw\n",
  "1 1 1:2 / / rw - ext4 source rw extra\n",
  "0 1 1:2 / / rw - ext4 source rw\n",
  "1 1 4294967296:2 / / rw - ext4 source rw\n",
  "1 1 1:2 / /../escape rw - ext4 source rw\n",
  "1 1 1:2 / / rw - ext4 source\\099 rw\n",
  "1 1 1:2 / / rw - ext4 source rw\r\n",
  "\n1 1 1:2 / / rw - ext4 source rw\n",
])
def test_mountinfo_rejects_malformed_ids_flags_paths_and_unknown_escapes(raw):
  with pytest.raises(ConfigError): parse_mountinfo(raw)


def test_mountinfo_four_kernel_escapes_and_known_optional_fields():
  result = parse_mountinfo("1 1 1:2 / /space\\040tab\\011line\\012slash\\134 rw shared:1 master:2 propagate_from:3 unbindable - ext4 ignored rw\n")
  assert result[0]["mountpoint"] == "/space tab\tline\nslash\\"


def test_mountinfo_size_bound_is_in_utf8_bytes():
  raw = "1 1 1:2 / / rw - ext4 " + "界" * 1500000 + " rw\n"
  with pytest.raises(ConfigError): parse_mountinfo(raw)


def test_system_symlink_loop_fails_with_fixed_error(shell_case, tmp_path):
  alias = tmp_path / "loop"; alias.symlink_to(alias)
  with pytest.raises(ConfigError) as caught:
    compile_mount_plan(public(shell_case), system_roots=(str(alias),), mountinfo=baseline(shell_case))
  assert caught.value.code == "pi-shell-mounts"


@pytest.mark.parametrize("root", ["/original/.git", "/original/.git/objects"])
def test_git_directory_backing_alias_cannot_be_visible_project(shell_case, root):
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=root)
  with pytest.raises(Conflict, match="SHELL_MOUNT_GIT_ALIAS"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_executable_backing_git_alias_is_rejected(shell_case):
  executable = shell_case["binding"]["executable"]
  info = baseline(shell_case) + mount_row(2, executable, root="/original/.git/script")
  with pytest.raises(Conflict, match="SHELL_MOUNT_GIT_ALIAS"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


@pytest.mark.parametrize("relation", ["same", "descendant", "ancestor"])
def test_readonly_policy_is_projected_before_write_backing_alias_check(shell_case, tmp_path, relation):
  readonly = tmp_path / "readonly"; readonly.mkdir()
  shell_case["declared_roots"]["readonly"] = {"path": str(readonly), "purpose": "read"}
  shell_case["permissions"] = {"readonly_roots": ["readonly"]}
  if relation == "same": backing_root = str(readonly)
  elif relation == "descendant": backing_root = str(readonly / "subtree")
  else: backing_root = "/separate-original"
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=backing_root)
  if relation == "ancestor": info += mount_row(3, readonly, root="/separate-original/subtree")
  with pytest.raises(Conflict, match="SHELL_MOUNT_READONLY"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_readonly_backing_alias_is_allowed_for_readonly_project(shell_case, tmp_path):
  readonly = tmp_path / "readonly"; readonly.mkdir()
  shell_case["declared_roots"]["readonly"] = {"path": str(readonly), "purpose": "read"}
  shell_case["permissions"] = {"readonly_roots": ["readonly"]}
  shell_case["binding"]["write_roots"] = []
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=str(readonly))
  result = compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)
  assert all(not row["writable"] for row in result["mounts"])


def test_readonly_superblock_refuses_writable_project(shell_case):
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=shell_case["cwd"], flags="rw", super_flags="ro")
  with pytest.raises(Conflict, match="SHELL_MOUNT_READONLY"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_readonly_project_remains_available_on_readonly_superblock(shell_case):
  shell_case["binding"]["write_roots"] = []
  info = baseline(shell_case) + mount_row(2, shell_case["cwd"], root=shell_case["cwd"], flags="rw", super_flags="ro")
  result = compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)
  assert all(not row["writable"] for row in result["mounts"])


@pytest.mark.parametrize("mount_flags,super_flags,expected", [("rw", "rw", True), ("ro", "rw", False),
  ("rw", "ro", False), ("ro", "ro", False)])
def test_parser_writable_requires_both_mount_and_superblock_rw(mount_flags, super_flags, expected):
  rows = parse_mountinfo(f"1 1 1:2 / / {mount_flags} - ext4 ignored {super_flags}\n")
  assert rows[0]["writable"] is expected


@pytest.mark.parametrize("super_flags", ["sensitive-option", "ro,rw", "rw,rw", "rw,,relatime"])
def test_superblock_options_require_exactly_one_ro_or_rw(super_flags):
  with pytest.raises(ConfigError):
    parse_mountinfo(f"1 1 1:2 / / rw - ext4 ignored {super_flags}\n")


def test_mountinfo_accepts_distinct_ids_stacked_at_same_point():
  rows = parse_mountinfo("45 23 0:20 / /proc/sys/fs/binfmt_misc rw - autofs source rw\n"
    "282 45 0:45 / /proc/sys/fs/binfmt_misc rw - binfmt_misc source rw\n")
  assert [row["mount_id"] for row in rows] == [45, 282]
  assert rows[0]["mountpoint"] == rows[1]["mountpoint"]


def test_unqueried_unrelated_stacked_mountpoint_does_not_block_plan(shell_case):
  info = baseline(shell_case) + "45 23 0:20 / /proc/sys/fs/binfmt_misc rw - autofs source rw\n" + \
    "282 45 0:45 / /proc/sys/fs/binfmt_misc rw - binfmt_misc source rw\n"
  assert compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info) == plan(shell_case)


@pytest.mark.parametrize("target", ["source", "executable", "denied", "readonly", "special"])
def test_queried_deepest_stacked_mountpoint_fails_closed(shell_case, tmp_path, target):
  value = public(shell_case)
  if target == "source": path = Path(shell_case["cwd"])
  elif target == "executable": path = Path(shell_case["binding"]["executable"])
  elif target == "special": path = Path("/proc")
  else:
    path = tmp_path / "unselected-policy"; path.mkdir()
    value["physical"]["denied_paths" if target == "denied" else "readonly_paths"] = [str(path)]
  info = baseline(shell_case) + mount_row(2, path) + mount_row(3, path, root="/different", parent=2)
  with pytest.raises(Conflict, match="^SHELL_MOUNT_AMBIGUOUS$"):
    compile_mount_plan(value, system_roots=(), mountinfo=info)


def test_duplicate_mount_id_still_refused_even_at_different_points(shell_case):
  info = baseline(shell_case) + mount_row(1, shell_case["cwd"])
  with pytest.raises(ConfigError, match="pi-shell-mountinfo"): parse_mountinfo(info)


def test_stacked_child_mounts_still_refused_without_guessing_layers(shell_case):
  child = Path(shell_case["cwd"]) / "nested"; child.mkdir()
  info = baseline(shell_case) + mount_row(2, child) + mount_row(3, child, parent=2)
  with pytest.raises(Conflict, match="^SHELL_MOUNT_SUBMOUNT$"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def test_unique_deeper_mount_cannot_disambiguate_hidden_ancestor_branch(shell_case, tmp_path):
  parent = tmp_path / "layer"; parent.mkdir()
  project = parent / "project"; project.mkdir()
  shell_case["cwd"] = str(project)
  shell_case["declared_roots"]["project"]["path"] = str(project)
  info = baseline(shell_case) + mount_row(2, parent, root="/lower") + mount_row(3, parent, root="/upper", parent=2) + \
    mount_row(4, project, root="/unique", parent=3)
  with pytest.raises(Conflict, match="^SHELL_MOUNT_AMBIGUOUS$"):
    compile_mount_plan(public(shell_case), system_roots=(), mountinfo=info)


def deny_child_open(monkeypatch, parent, error):
  original = os.open
  expected = parent.stat()
  attempts = []
  def opened(path, flags, mode=0o777, *, dir_fd=None):
    if path == "auditd" and dir_fd is not None:
      info = os.fstat(dir_fd)
      if (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
        attempts.append(path)
        raise OSError(error, "synthetic inventory failure")
    return original(path, flags, mode, dir_fd=dir_fd)
  monkeypatch.setattr(os, "open", opened)
  return attempts


@pytest.mark.parametrize("error", [13, 1])
def test_system_unreadable_directory_becomes_identity_mask(shell_case, tmp_path, monkeypatch, error):
  from agentcfg.activity import digest
  system = tmp_path / "system"; system.mkdir()
  blocked = system / "auditd"; blocked.mkdir()
  canary = blocked / "canary"; canary.write_bytes(b"unchanged")
  before = canary.stat()
  info = blocked.stat()
  expected = digest((info.st_dev, info.st_ino, info.st_uid, info.st_mode))
  attempts = deny_child_open(monkeypatch, system, error)
  result = compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=baseline(shell_case))
  assert result["masks"] == [{"path": str(blocked), "kind": "directory", "identity": expected}]
  assert attempts == ["auditd"]
  assert canary.read_bytes() == b"unchanged" and canary.stat() == before


@pytest.mark.parametrize("role,error", [("workspace", 13), ("workspace", 1), ("system", 5)])
def test_inventory_permission_fallback_is_only_system_eacces_eperm(shell_case, tmp_path, monkeypatch, role, error):
  root = Path(shell_case["cwd"]) if role == "workspace" else tmp_path / "system"
  if role == "system": root.mkdir()
  (root / "auditd").mkdir()
  deny_child_open(monkeypatch, root, error)
  with pytest.raises(ConfigError, match="pi-shell-mounts"):
    compile_mount_plan(public(shell_case), system_roots=(str(root),) if role == "system" else (),
      mountinfo=baseline(shell_case))


def test_system_permission_mask_projects_to_workspace_alias(shell_case, tmp_path, monkeypatch):
  system = tmp_path / "system"; system.mkdir(); (system / "auditd").mkdir()
  project = Path(shell_case["cwd"]); (project / "auditd").mkdir()
  shell_case["binding"]["write_roots"] = []
  info = baseline(shell_case) + mount_row(2, system, root="/shared") + mount_row(3, project, root="/shared")
  deny_child_open(monkeypatch, system, 13)
  result = compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=info)
  assert {(row["path"], row["kind"]) for row in result["masks"]} == {
    (str(system / "auditd"), "directory"), (str(project / "auditd"), "directory")}


@pytest.mark.parametrize("target", ["cwd", "executable"])
def test_system_permission_mask_cannot_hide_cwd_or_executable(shell_case, tmp_path, monkeypatch, target):
  system = tmp_path / "system"; system.mkdir(); (system / "auditd").mkdir()
  project = Path(shell_case["cwd"]); (project / "auditd").mkdir()
  shell_case["binding"]["write_roots"] = []
  if target == "cwd": shell_case["cwd"] = str(project / "auditd")
  else:
    exe = project / "auditd/bash"; exe.write_bytes(b"synthetic"); exe.chmod(0o700)
    shell_case["binding"]["executable"] = str(exe)
  info = baseline(shell_case) + mount_row(2, system, root="/shared") + mount_row(3, project, root="/shared")
  deny_child_open(monkeypatch, system, 13)
  with pytest.raises(Conflict, match="^PERMISSION_DENIED$"):
    compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=info)


@pytest.mark.parametrize("error", [13, 1])
def test_system_root_permission_failure_cannot_be_masked(shell_case, tmp_path, monkeypatch, error):
  system = tmp_path / "auditd"; system.mkdir()
  deny_child_open(monkeypatch, tmp_path, error)
  with pytest.raises(ConfigError, match="pi-shell-mounts"):
    compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=baseline(shell_case))


@pytest.mark.parametrize("kind", ["fifo", "socket-stat"])
def test_system_special_object_masks_parent_and_all_aliases(shell_case, tmp_path, monkeypatch, kind):
  import stat
  from agentcfg.activity import digest
  system = tmp_path / "system"; system.mkdir()
  parent = system / "service"; parent.mkdir(); endpoint = parent / "endpoint"; os.mkfifo(endpoint)
  canary = parent / "canary"; canary.write_bytes(b"unchanged")
  before = canary.stat()
  project = Path(shell_case["cwd"]); (project / "service").mkdir()
  shell_case["binding"]["write_roots"] = []
  if kind == "socket-stat":
    original = os.stat
    def info(path, *args, **kwargs):
      value = original(path, *args, **kwargs)
      if path == "endpoint" and kwargs.get("dir_fd") is not None:
        values = list(value); values[0] = stat.S_IFSOCK | 0o600
        return os.stat_result(values)
      return value
    monkeypatch.setattr(os, "stat", info)
  mountinfo = baseline(shell_case) + mount_row(2, system, root="/shared") + mount_row(3, project, root="/shared")
  result = compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=mountinfo)
  assert result["masks"] == sorted([
    {"path": str(parent), "kind": "directory", "identity": digest(tuple(getattr(parent.stat(), key) for key in ("st_dev", "st_ino", "st_uid", "st_mode")))},
    {"path": str(project / "service"), "kind": "directory", "identity": digest(tuple(getattr((project / "service").stat(), key) for key in ("st_dev", "st_ino", "st_uid", "st_mode")))}],
    key=lambda row: (len(Path(row["path"]).parts), row["path"]))
  assert canary.read_bytes() == b"unchanged" and canary.stat() == before


@pytest.mark.parametrize("target", ["source-root", "cwd", "executable", "workspace"])
def test_special_object_parent_mask_cannot_cover_protected_roots(shell_case, tmp_path, target):
  system = tmp_path / "system"; system.mkdir()
  parent = system if target == "source-root" else system / "service"
  if parent != system: parent.mkdir()
  project = Path(shell_case["cwd"])
  if target == "workspace": parent = project
  os.mkfifo(parent / "endpoint")
  shell_case["binding"]["write_roots"] = []
  (project / "service").mkdir()
  if target == "cwd": shell_case["cwd"] = str(project / "service")
  if target == "executable":
    exe = project / "service/bash"; exe.write_bytes(b"synthetic"); exe.chmod(0o700)
    shell_case["binding"]["executable"] = str(exe)
  mountinfo = baseline(shell_case) + mount_row(2, system, root="/shared") + mount_row(3, project, root="/shared")
  expected = "SHELL_MOUNT_OBJECT" if target == "workspace" else "PERMISSION_DENIED"
  with pytest.raises(Conflict, match="^" + expected + "$"):
    compile_mount_plan(public(shell_case), system_roots=(str(system),), mountinfo=mountinfo)


def test_masked_git_internal_writer_directory_does_not_change_public_plan(shell_case):
  git = Path(shell_case["cwd"]) / ".git"; git.mkdir()
  (git / "HEAD").write_bytes(b"ref: refs/heads/fixture\n")
  value = public(shell_case)
  before = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  (git / "agentcfg").mkdir(mode=0o700)
  (git / "agentcfg/write-lease.json").write_bytes(b"synthetic writer record")
  after = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  assert after == before


@pytest.mark.parametrize("change", ["replace", "chmod", "type"])
def test_directory_mask_identity_still_binds_replacement_mode_and_type(shell_case, change):
  project = Path(shell_case["cwd"])
  hidden = project / "private"; hidden.mkdir(mode=0o700)
  shell_case["permission_policy"]["rules"].append(file_deny("project", "private"))
  value = public(shell_case)
  before = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  if change == "chmod": hidden.chmod(0o750)
  else:
    hidden.rename(project / "previous-private")
    if change == "replace": hidden.mkdir(mode=0o700)
    else: hidden.write_bytes(b"now a file")
  after = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  assert after != before
  assert after["masks"][0]["identity"] != before["masks"][0]["identity"]
  assert after["masks"][0]["kind"] == ("file" if change == "type" else "directory")


def test_file_mask_retains_full_metadata_snapshot_identity(shell_case):
  from agentcfg.activity import digest
  from agentcfg.pi_shell_mounts import _snapshot
  hidden = Path(shell_case["cwd"]) / "private"; hidden.write_bytes(b"unchanged length")
  shell_case["permission_policy"]["rules"].append(file_deny("project", "private"))
  value = public(shell_case)
  before = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  assert before["masks"][0]["identity"] == digest(_snapshot(hidden.stat()))
  info = hidden.stat(); os.utime(hidden, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
  after = compile_mount_plan(value, system_roots=(), mountinfo=baseline(shell_case))
  assert after["masks"][0]["identity"] != before["masks"][0]["identity"]
