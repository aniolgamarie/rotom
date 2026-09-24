"""仅检查沙箱调用意图，不运行 bwrap、宿主或业务检查。"""

from copy import deepcopy
from pathlib import Path

import pytest

from agentcfg.pi_checks import compile_check, linux_verifier_argv
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def fixture(tmp_path):
  candidate = tmp_path / "candidate"
  candidate.mkdir()
  (candidate / ".git").write_text("gitdir: fictional-metadata")
  executable = tmp_path / "check-tool"
  executable.write_text("synthetic checker, never execute")
  executable.chmod(0o700)
  binding = {"executable": str(executable), "args": ["--literal", "a b", "a b"], "project_root": "project", "timeout_seconds": 30, "foreground": True}
  return binding, candidate, executable


def test_verifier_has_no_network_no_real_home_and_preserves_exact_argv(tmp_path):
  binding, candidate, executable = fixture(tmp_path)
  check = compile_check(binding, candidate=candidate, executable=executable, read_roots=[executable])
  argv = linux_verifier_argv(check, temporary=tmp_path / "check-tmp", system_roots=())
  assert "--unshare-all" in argv
  assert ("--ro-bind", str(candidate / ".git"), str(candidate / ".git")) == argv[argv.index(str(candidate / ".git")) - 1:argv.index(str(candidate / ".git")) + 2]
  assert argv[-4:] == (str(executable), "--literal", "a b", "a b")
  assert str(Path.home()) not in argv
  assert ("--ro-bind", "/", "/") not in tuple(zip(argv, argv[1:], argv[2:]))


def test_nonforeground_and_changed_argv_cannot_borrow_a_check_binding(tmp_path):
  binding, candidate, executable = fixture(tmp_path)
  binding["foreground"] = False
  with pytest.raises(ConfigError):
    compile_check(binding, candidate=candidate, executable=executable)
  binding["foreground"] = True
  check = compile_check(binding, candidate=candidate, executable=executable)
  check["argv"].append("--changed")
  with pytest.raises(Conflict):
    linux_verifier_argv(check, temporary=tmp_path / "temporary")


def test_changed_executable_cannot_reuse_previous_admission(tmp_path):
  binding, candidate, executable = fixture(tmp_path)
  check = compile_check(binding, candidate=candidate, executable=executable)
  executable.write_text("changed checker")
  with pytest.raises(Conflict):
    linux_verifier_argv(check, temporary=tmp_path / "temporary")


def test_macos_policy_is_closed_no_network_and_keeps_literal_denied_paths(tmp_path):
  from agentcfg.pi_checks import macos_verifier_policy
  binding, candidate, executable = fixture(tmp_path)
  check = compile_check(binding, candidate=candidate, executable=executable)
  policy = macos_verifier_policy(check, temporary=tmp_path / "temporary", denied_paths=[candidate / '.env"private'])
  assert "(deny default)" in policy and "(deny network*)" in policy
  assert "(allow default)" not in policy
  assert '.env\\"private' in policy
  check["argv"].append("--unapproved")
  with pytest.raises(Conflict):
    macos_verifier_policy(check, temporary=tmp_path / "temporary")


def test_linux_denied_files_use_private_readonly_zero_permission_views(tmp_path):
  binding, candidate, executable = fixture(tmp_path)
  secret = candidate / ".env"
  secret.write_text("synthetic credential sentinel")
  directory = candidate / "private"
  directory.mkdir()
  check = compile_check(binding, candidate=candidate, executable=executable)
  argv = linux_verifier_argv(check, temporary=tmp_path / "temporary", denied_paths=[secret, directory], denied_fds={str(secret): 19})
  assert argv[0] == "/usr/bin/bwrap"
  assert ("--cap-drop", "ALL") in tuple(zip(argv, argv[1:]))
  at = argv.index("--ro-bind-data")
  assert argv[at - 2:at + 3] == ("--perms", "000", "--ro-bind-data", "19", str(secret))
  assert ("--remount-ro", str(directory)) in tuple(zip(argv, argv[1:]))
  assert secret.read_text() == "synthetic credential sentinel"
  with pytest.raises(ConfigError, match="not-representable"):
    linux_verifier_argv(check, temporary=tmp_path / "temporary", denied_paths=[candidate / "absent"])
  assert not (candidate / "absent").exists()


def test_macos_private_scratch_does_not_get_denied_with_the_rest_of_state(tmp_path):
  from agentcfg.pi_checks import compile_check, macos_verifier_policy
  executable = tmp_path / "fake-check"; executable.write_text("fixture"); executable.chmod(0o700)
  project = tmp_path / "project"; project.mkdir()
  state = tmp_path / "private-state"; temporary = state / "activity/job-home"
  check = compile_check({"executable": str(executable), "args": [], "project_root": "project", "timeout_seconds": 5, "foreground": True}, candidate=project, executable=executable)
  policy = macos_verifier_policy(check, temporary=temporary, denied_paths=[state])
  assert '(require-not (subpath "' + str(temporary) + '"))' in policy
  assert '(require-all (subpath "' + str(state) + '")' in policy
  with pytest.raises(ConfigError, match="temporary-denied"):
    macos_verifier_policy(check, temporary=temporary, denied_paths=[temporary])


def test_macos_terminal_writes_are_limited_to_own_device(tmp_path):
  from agentcfg.activity import digest
  from agentcfg.pi_checks import macos_verifier_policy
  binding, candidate, executable = fixture(tmp_path)
  check = compile_check(binding, candidate=candidate, executable=executable)
  check["terminal_size"] = [24, 80]
  check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
  policy = macos_verifier_policy(check, temporary=tmp_path / "temporary", terminal_device="/dev/ttys012")
  assert '(allow file-write* file-ioctl (literal "/dev/ttys012") (literal "/dev/tty"))' in policy
  assert '(allow file-write* file-ioctl (subpath "/dev"))' not in policy
  for device in (None, "/dev/ttys", "/dev/ttys0/other", '/dev/ttys0"'):
    with pytest.raises(ConfigError, match="pi-terminal-device"):
      macos_verifier_policy(check, temporary=tmp_path / "temporary", terminal_device=device)
  with pytest.raises(Conflict, match="TERMINAL_DENIED"):
    macos_verifier_policy(check, temporary=tmp_path / "temporary", terminal_device="/dev/ttys012", denied_paths=["/dev"])
