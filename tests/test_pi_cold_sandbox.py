"""冷重建文件/环境边界的命令意图；不启动安装器、沙箱或网络。"""
from pathlib import Path
from types import SimpleNamespace
import pytest
from agentcfg.pi_cold_sandbox import isolated_runner
from agentcfg.schema import ConfigError


def programs(tmp_path):
  result = {}
  for name in ("node", "npm", "git", "uv"):
    path = tmp_path / "toolchains" / name / "bin" / name
    path.parent.mkdir(parents=True); path.write_text("synthetic executable, never run"); path.chmod(0o700)
    result[name] = str(path)
  return result


def test_linux_cold_commands_cannot_see_parent_home_or_reference_checkout(tmp_path):
  tools = programs(tmp_path)
  base = tmp_path / "new target"; base.mkdir(mode=0o700)
  home = base / "home"; home.mkdir()
  checkout = base / "checkout"; checkout.mkdir()
  calls = []
  runner = isolated_runner(base, "pi-managed", tools["uv"], lambda argv, **kwargs: calls.append((argv, kwargs)),
    programs=tools, system="linux", system_roots=(), trust_paths=())
  runner([tools["uv"], "sync", "--locked"], cwd=checkout, env={"HOME": str(home), "PATH": "/old-home/bin"})
  argv, options = calls[0]
  assert "--unshare-all" in argv and "--share-net" in argv and "--die-with-parent" in argv
  assert "/old-home/bin" not in options["env"]["PATH"] and str(Path.home()) not in argv
  assert ("--bind", str(base), str(base)) in tuple(zip(argv, argv[1:], argv[2:]))
  assert ("--ro-bind", "/", "/") not in tuple(zip(argv, argv[1:], argv[2:]))
  import sys
  assert (base / "tool-bin/python3").resolve() == Path(sys._base_executable).resolve()
  assert argv[-3:] == [str(base / "tool-bin/uv"), "sync", "--locked"]
  with pytest.raises(ConfigError): runner(["synthetic"], cwd=tmp_path, env={"HOME": str(home)})


def test_macos_cold_policy_has_explicit_toolchain_roots_and_fresh_writable_target(tmp_path):
  tools = programs(tmp_path)
  base = tmp_path / "new"; base.mkdir(mode=0o700)
  runner = isolated_runner(base, "pi-default", tools["uv"], lambda *a, **k: None, programs=tools, system="darwin", system_roots=(), trust_paths=(), architecture="arm64", developer_root=tmp_path / "toolchains")
  policy = (base / "cold-install.sb").read_text()
  assert "(deny default)" in policy and "(allow network*)" in policy
  assert '(allow file-read* file-write* (subpath "' + str(base) + '"))' in policy
  assert str(Path.home()) not in policy


def test_cold_sandbox_does_not_mount_ambient_certificate_file_overrides(tmp_path, monkeypatch):
  from agentcfg import pi_cold_sandbox as cold
  tools = programs(tmp_path)
  base = tmp_path / "new"; base.mkdir(mode=0o700)
  home = base / "home"; home.mkdir()
  private = tmp_path / "old-private-value"; private.write_text("synthetic unselected")
  monkeypatch.setattr(cold.ssl, "get_default_verify_paths", lambda: SimpleNamespace(cafile=str(private), capath=str(private.parent), openssl_cafile=None, openssl_capath=None))
  calls = []
  runner = isolated_runner(base, "pi-default", tools["uv"], lambda argv, **kwargs: calls.append(argv), programs=tools, system="linux", system_roots=())
  runner(["synthetic"], cwd=base, env={"HOME": str(home)})
  assert str(private) not in calls[0]


def test_intel_cold_sandbox_binds_source_build_tools_and_explicit_sdk(tmp_path):
  tools = programs(tmp_path)
  for name in ("zig", "make", "python3", "patch"):
    path = tmp_path / "toolchains" / name / "bin" / name
    path.parent.mkdir(parents=True); path.write_text("fake"); path.chmod(0o700); tools[name] = str(path)
  sdk = tmp_path / "sdk"; sdk.mkdir()
  base = tmp_path / "new"; base.mkdir(mode=0o700)
  isolated_runner(base, "pi-default", tools["uv"], lambda *a, **k: None, programs=tools, system="darwin",
    system_roots=(), trust_paths=(), architecture="x86_64", developer_root=sdk)
  policy = (base / "cold-install.sb").read_text()
  assert str(sdk) in policy and str(Path(tools["zig"]).parent.parent) in policy
  assert (base / "tool-bin/zig").resolve() == Path(tools["zig"])


def test_system_trust_alias_and_target_both_remain_readable_without_ambient_overrides(tmp_path):
  tools = programs(tmp_path)
  base = tmp_path / "new"; base.mkdir(mode=0o700)
  home = base / "home"; home.mkdir()
  target = tmp_path / "system-trust.pem"; target.write_text("synthetic public CA")
  alias = tmp_path / "ssl/cert.pem"; alias.parent.mkdir(); alias.symlink_to(target)
  calls = []
  run = isolated_runner(base, "pi-default", tools["uv"], lambda argv, **kwargs: calls.append(argv),
    programs=tools, system="linux", system_roots=(), trust_paths=[alias])
  run(["synthetic"], cwd=base, env={"HOME": str(home)})
  triples = tuple(zip(calls[0], calls[0][1:], calls[0][2:]))
  assert ("--ro-bind", str(alias), str(alias)) in triples
  assert ("--ro-bind", str(target), str(target)) in triples
