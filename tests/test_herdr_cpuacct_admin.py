"""管理员辅助器的定位与拒绝边界；默认不使用sudo或内核cgroup写入。"""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
  source = Path(__file__).resolve().parents[1] / "tools/bench/cpuacct_admin.py"
  spec = importlib.util.spec_from_file_location("cpuacct_admin_fixture", source)
  result = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(result)
  return result


def mount_case(tmp_path, monkeypatch, *, source="/tenant/session", mounted_root="/tenant", flags="rw"):
  admin = module()
  mount = tmp_path / "mounted"
  target = mount / "session"
  target.mkdir(parents=True)
  for name in ("cpuacct.usage_user", "cpuacct.usage_sys", "cgroup.procs"):
    (target / name).write_text("0\n")
  contents = {"/proc/self/cgroup": "5:cpu,cpuacct:" + source + "\n",
    "/proc/self/mountinfo": "17 12 0:19 " + mounted_root + " " + str(mount) + " " + flags + " - cgroup cgroup rw,cpu,cpuacct\n"}
  real_path = Path
  def path(value):
    if str(value) in contents:
      return SimpleNamespace(read_text=lambda: contents[str(value)])
    return real_path(value)
  monkeypatch.setattr(admin, "Path", path)
  return admin, target, contents


def test_admin_locates_child_of_original_resource_group(tmp_path, monkeypatch):
  admin, target, _ = mount_case(tmp_path, monkeypatch)
  source, resolved = admin.locate()
  assert source == "/tenant/session"
  assert resolved == target
  assert resolved != target.parent


@pytest.mark.parametrize("source,root,flags", [("/another/session", "/tenant", "rw"),
  ("/tenant/session", "/tenant", "ro"), ("/tenant/../other", "/tenant", "rw")])
def test_admin_rejects_wrong_scope_or_readonly_view(tmp_path, monkeypatch, source, root, flags):
  admin, _, _ = mount_case(tmp_path, monkeypatch, source=source, mounted_root=root, flags=flags)
  with pytest.raises(RuntimeError):
    admin.locate()


def test_admin_refuses_ambiguous_controller(tmp_path, monkeypatch):
  admin, _, contents = mount_case(tmp_path, monkeypatch)
  contents["/proc/self/cgroup"] *= 2
  with pytest.raises(RuntimeError, match="cpuacct_source_not_unique"):
    admin.locate()


@pytest.mark.parametrize("administrator,sudo_uid", [(False, "1001"), (True, ""), (True, "0")])
def test_admin_preflight_never_creates_when_authority_is_missing(monkeypatch, administrator, sudo_uid):
  admin = module()
  monkeypatch.setattr(admin.os, "geteuid", lambda: 0 if administrator else 1001)
  monkeypatch.setenv("SUDO_UID", sudo_uid)
  monkeypatch.setattr("sys.argv", ["cpuacct_admin", "prepare"])
  monkeypatch.setattr(admin, "prepare", lambda *args: pytest.fail("unexpected mutation"))
  with pytest.raises(RuntimeError, match="run_from_your_normal_user_with_sudo"):
    admin.main()


def test_empty_guard_preserves_existing_tasks_and_unknown_children(tmp_path):
  admin = module()
  group = tmp_path / "group"
  group.mkdir()
  (group / "cgroup.procs").write_text("12345\n")
  (group / "tasks").write_text("12345\n")
  fd = os.open(group, os.O_RDONLY | os.O_DIRECTORY)
  try:
    with pytest.raises(RuntimeError, match="group_not_empty"):
      admin.empty(fd)
    assert (group / "cgroup.procs").read_text() == "12345\n"
    (group / "cgroup.procs").write_text("")
    (group / "tasks").write_text("")
    (group / "unknown").mkdir()
    with pytest.raises(RuntimeError, match="unexpected_child_group"):
      admin.empty(fd)
    assert (group / "unknown").is_dir()
  finally:
    os.close(fd)
