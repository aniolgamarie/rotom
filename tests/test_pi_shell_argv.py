"""纯 bwrap argv 编译；假 FD、不执行 helper 或 Shell。"""

from copy import deepcopy
import json
import os

import pytest

from agentcfg.pi_shell_argv import compile_argv
from agentcfg.schema import ConfigError


@pytest.fixture
def case():
  plan = {"schema_version": 1, "platform": "linux-x86_64", "network": "deny",
    "mounts": [
      {"path": "/usr", "kind": "directory", "identity": "a" * 64, "writable": False, "role": "system"},
      {"path": "/tmp/project", "kind": "directory", "identity": "b" * 64, "writable": True, "role": "workspace"},
      {"path": "/tmp/project/child", "kind": "directory", "identity": "c" * 64, "writable": True, "role": "workspace"},
      {"path": "/usr/bin/bash", "kind": "file", "identity": {"path": "/usr/bin/bash", "device": 1,
        "inode": 2, "uid": 0, "sha256": "d" * 64}, "writable": False, "role": "executable"}],
    "symlinks": [{"path": "/bin", "target": "/usr/bin"}],
    "masks": [{"path": "/tmp/project/.git", "kind": "directory", "identity": "e" * 64},
      {"path": "/tmp/project/private", "kind": "file", "identity": "f" * 64}],
    "cwd": {"path": "/tmp/project/child", "identity": "0" * 64}, "seccomp_digest": "1" * 64}
  return {"plan": plan, "source_fds": {row["path"]: fd for fd, row in enumerate(plan["mounts"], 10)},
    "script_fd": 20, "seccomp_fd": 21, "mask_fds": {"/tmp/project/private": 22}}


def position(argv, *parts):
  for index in range(len(argv) - len(parts) + 1):
    if argv[index:index + len(parts)] == parts: return index
  raise AssertionError("expected fixed argv fragment missing")


def test_exact_isolation_env_and_bash_contract_without_side_effects(case, monkeypatch):
  before = deepcopy(case)
  def forbidden(*args, **kwargs): raise AssertionError("pure compiler performed IO")
  for name in ("open", "close", "fstat", "dup", "write", "read", "memfd_create"):
    monkeypatch.setattr(os, name, forbidden)
  monkeypatch.setenv("SYNTHETIC_PRIVATE", "private script sentinel")
  argv = compile_argv(**case)
  assert type(argv) is tuple and all(type(arg) is str for arg in argv)
  assert argv[:14] == ("--unshare-user", "--disable-userns", "--assert-userns-disabled", "--unshare-pid",
    "--unshare-net", "--unshare-ipc", "--unshare-uts", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
    "--clearenv", "--setenv", "HOME")
  env = [(argv[index + 1], argv[index + 2]) for index, value in enumerate(argv) if value == "--setenv"]
  assert env == [("HOME", "/.rotom-shell/home"), ("TMPDIR", "/tmp"), ("PATH", "/usr/bin:/bin"),
    ("LANG", "C.UTF-8"), ("LC_ALL", "C.UTF-8"), ("TERM", "dumb")]
  assert argv[-5:] == ("--", "/usr/bin/bash", "--noprofile", "--norc", "/.rotom-shell/script")
  assert "-c" not in argv and "-e" not in argv and "-u" not in argv
  assert "private script sentinel" not in json.dumps(argv)
  assert case == before


def test_sources_are_parent_first_symlinks_first_and_masks_last(case):
  argv = compile_argv(**case)
  alias = position(argv, "--symlink", "/usr/bin", "/bin")
  system = position(argv, "--ro-bind-fd", "10", "/usr")
  project = position(argv, "--bind-fd", "11", "/tmp/project")
  child = position(argv, "--bind-fd", "12", "/tmp/project/child")
  executable = position(argv, "--ro-bind-fd", "13", "/usr/bin/bash")
  script = position(argv, "--perms", "0400", "--ro-bind-data", "20", "/.rotom-shell/script")
  filtering = position(argv, "--seccomp", "21")
  directory_mask = position(argv, "--perms", "0000", "--tmpfs", "/tmp/project/.git", "--remount-ro", "/tmp/project/.git")
  file_mask = position(argv, "--perms", "0000", "--ro-bind-data", "22", "/tmp/project/private")
  assert alias < system and project < child
  assert max(system, project, child, executable, script, filtering) < min(directory_mask, file_mask)
  assert position(argv, "--tmpfs", "/.rotom-shell") < project
  assert position(argv, "--tmpfs", "/tmp") < project
  assert position(argv, "--proc", "/proc") < project
  assert position(argv, "--dev", "/dev") < project
  assert all(argv[index + 1].startswith("/.rotom-shell") for index, value in enumerate(argv) if value == "--dir")
  assert position(argv, "--chdir", "/tmp/project/child") > file_mask


def test_readonly_workspace_is_never_bound_writable(case):
  for row in case["plan"]["mounts"]: row["writable"] = False
  argv = compile_argv(**case)
  assert "--bind-fd" not in argv
  assert position(argv, "--ro-bind-fd", "11", "/tmp/project")


@pytest.mark.parametrize("mutation", ["missing-source", "extra-source", "missing-mask", "extra-mask", "reused-source",
  "script-source", "seccomp-script", "mask-script", "stdio", "bool", "text"])
def test_fd_maps_are_exact_unique_integer_descriptors(case, mutation):
  if mutation == "missing-source": del case["source_fds"]["/usr"]
  elif mutation == "extra-source": case["source_fds"]["/extra"] = 30
  elif mutation == "missing-mask": case["mask_fds"].clear()
  elif mutation == "extra-mask": case["mask_fds"]["/extra"] = 30
  elif mutation == "reused-source": case["source_fds"]["/usr"] = 11
  elif mutation == "script-source": case["script_fd"] = 10
  elif mutation == "seccomp-script": case["seccomp_fd"] = 20
  elif mutation == "mask-script": case["mask_fds"]["/tmp/project/private"] = 20
  else: case["script_fd"] = {"stdio": 2, "bool": True, "text": "20"}[mutation]
  with pytest.raises(ConfigError, match="pi-shell-argv"): compile_argv(**case)


@pytest.mark.parametrize("location", ["plan", "mount", "mask", "alias", "cwd", "identity"])
def test_unknown_fields_are_rejected(case, location):
  selected = {"plan": case["plan"], "mount": case["plan"]["mounts"][0], "mask": case["plan"]["masks"][0],
    "alias": case["plan"]["symlinks"][0], "cwd": case["plan"]["cwd"], "identity": case["plan"]["mounts"][-1]["identity"]}[location]
  selected["command"] = "private unaccepted script"
  with pytest.raises(ConfigError) as caught: compile_argv(**case)
  assert "private unaccepted script" not in str(caught.value)


@pytest.mark.parametrize("path", ["/", "/tmp", "/.rotom-shell", "/.rotom-shell/child", "/proc", "/proc/child", "/dev", "/sys", "relative", "/tmp/../escape", "/tmp/back\\slash"])
def test_reserved_or_noncanonical_mount_paths_are_rejected(case, path):
  mount = case["plan"]["mounts"][1]
  case["source_fds"][path] = case["source_fds"].pop(mount["path"])
  mount["path"] = path
  with pytest.raises(ConfigError): compile_argv(**case)


@pytest.mark.parametrize("alias_path", ["/tmp/project/bin", "/tmp/project", "/tmp", "/usr/bin", "/.rotom-shell/bin", "/proc/bin"])
def test_alias_destination_cannot_overlap_any_source_or_reserved_root(case, alias_path):
  case["plan"]["symlinks"][0]["path"] = alias_path
  with pytest.raises(ConfigError): compile_argv(**case)


@pytest.mark.parametrize("mutation", ["uncovered-target", "masked-target", "cwd-mask", "exe-mask", "private-mask", "outside-mask", "system-write", "exe-write", "duplicate-mount", "duplicate-mask", "duplicate-alias", "wrong-platform", "wrong-network", "bad-identity"])
def test_inconsistent_or_unrepresentable_plan_is_rejected(case, mutation):
  plan = case["plan"]
  if mutation == "uncovered-target": plan["symlinks"][0]["target"] = "/outside"
  elif mutation == "masked-target": plan["masks"].append({"path": "/usr/bin", "kind": "directory", "identity": "a" * 64})
  elif mutation == "cwd-mask": plan["masks"][0]["path"] = plan["cwd"]["path"]
  elif mutation == "exe-mask":
    path = plan["mounts"][-1]["path"]
    case["mask_fds"][path] = case["mask_fds"].pop(plan["masks"][1]["path"])
    plan["masks"][1]["path"] = path
  elif mutation == "private-mask": plan["masks"][0]["path"] = "/.rotom-shell"
  elif mutation == "outside-mask": plan["masks"][0]["path"] = "/outside"
  elif mutation == "system-write": plan["mounts"][0]["writable"] = True
  elif mutation == "exe-write": plan["mounts"][-1]["writable"] = True
  elif mutation == "duplicate-mount": plan["mounts"].append(deepcopy(plan["mounts"][0]))
  elif mutation == "duplicate-mask": plan["masks"].append(deepcopy(plan["masks"][0]))
  elif mutation == "duplicate-alias": plan["symlinks"].append(deepcopy(plan["symlinks"][0]))
  elif mutation == "wrong-platform": plan["platform"] = "linux-aarch64"
  elif mutation == "wrong-network": plan["network"] = "allow"
  else: plan["mounts"][0]["identity"] = "invalid"
  with pytest.raises(ConfigError): compile_argv(**case)
