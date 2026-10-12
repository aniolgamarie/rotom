"""显式账户CLI仅临时passwd账户/私有源文档，默认无SDK/进程/网络。"""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import cli, pi_reviewer_authority_cli as module
from agentcfg.pi_reviewer_authority import FILE
from agentcfg.pi_reviewer_authority_protocol import encode_authority
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from test_pi_reviewer_authority import authority


@pytest.fixture
def fixture(tmp_path, monkeypatch):
  import agentcfg.pi_registered_roots as roots
  from agentcfg.secrets import SecretStore
  from agentcfg.pi_reviewer_account import ReviewerAccountLedger
  home = tmp_path / "account"; home.mkdir(mode=0o700)
  monkeypatch.setattr(roots.pwd, "getpwuid", lambda _: SimpleNamespace(pw_dir=str(home)))
  def forbidden(*args, **kwargs): raise AssertionError("unrelated configuration/SDK/budget access")
  monkeypatch.setattr(cli, "resolve_selection", forbidden)
  monkeypatch.setattr(SecretStore, "__init__", forbidden)
  monkeypatch.setattr(ReviewerAccountLedger, "__init__", forbidden)
  source = tmp_path / "document.json"; source.write_bytes(encode_authority(authority())); source.chmod(0o600)
  return home, source


def invoke(action, source=None, expected=None, format="json"):
  args = ["pi-reviewer-authority", action, "--format", format]
  if source is not None: args += ["--document", str(source)]
  if expected is not None: args += ["--expected-identity", expected]
  return cli.main(args)


def test_actual_main_create_show_update_without_selection(fixture, capsys):
  home, source = fixture
  assert invoke("create", source) == 0
  created = json.loads(capsys.readouterr().out)
  assert set(created) == {"schema_version", "status", "authority", "product_gate"}
  assert created["status"] == "created" and created["product_gate"] is False
  assert invoke("show") == 0
  observed = json.loads(capsys.readouterr().out)
  assert observed["status"] == "observed" and observed["authority"] == created["authority"]
  value = authority(); value["generation"] = 2; value["limits"]["max_calls"] = 10
  source.write_bytes(encode_authority(value))
  assert invoke("update", source, created["authority"]["identity"]) == 0
  updated = json.loads(capsys.readouterr().out)
  assert updated["status"] == "updated" and updated["authority"]["document"] == value
  assert str(home) not in json.dumps(updated) and {p.name for p in (home / ".agentcfg-workspaces").iterdir()} == {"registry.json", FILE}


def test_human_show_expired_is_passive_and_explicit_non_enable(fixture, capsys):
  home, source = fixture
  assert invoke("create", source) == 0; capsys.readouterr()
  assert invoke("show", format="human") == 0
  output = capsys.readouterr().out
  assert "1" in output and "synthetic" in output and "启用" in output and str(home) not in output


@pytest.mark.parametrize("selector", [["--machine", "private-canary"], ["--local", "private-canary"], ["--profile", "pi-full"]])
def test_account_cli_rejects_global_selectors_before_configuration(fixture, selector, capsys):
  home, _ = fixture
  with pytest.raises(SystemExit) as error: cli.main([*selector, "pi-reviewer-authority", "show"])
  assert error.value.code == 2 and list(home.iterdir()) == []
  assert "private-canary" not in capsys.readouterr().err


@pytest.mark.parametrize("tail", [["show", "--document", "SYNTHETIC_PRIVATE"], ["create"], ["update", "--document", "SYNTHETIC_PRIVATE"],
  ["create", "--account-home", "SYNTHETIC_PRIVATE"], ["reset"], ["delete"], ["show", "--format", "auto"]])
def test_closed_cli_arguments_do_not_echo_private_values(fixture, tail, capsys):
  with pytest.raises(SystemExit) as error: cli.main(["pi-reviewer-authority", *tail])
  assert error.value.code == 2 and "SYNTHETIC_PRIVATE" not in capsys.readouterr().err


@pytest.mark.parametrize("fault", ["mode", "hardlink", "symlink", "fifo", "missing", "oversize", "duplicate", "unknown", "invalid", "parent-link"])
def test_invalid_source_zero_store_lookup(fixture, tmp_path, monkeypatch, fault, capsys):
  home, source = fixture
  if fault == "mode": source.chmod(0o644)
  if fault == "hardlink": os.link(source, tmp_path / "second")
  if fault == "symlink": source.unlink(); source.symlink_to(tmp_path / "outside")
  if fault == "fifo": source.unlink(); os.mkfifo(source, 0o600)
  if fault == "missing": source.unlink()
  if fault == "oversize": source.write_bytes(b" " * 16385)
  if fault == "duplicate": source.write_bytes(source.read_bytes().replace(b'"generation":', b'"generation":1,"generation":'))
  if fault == "unknown":
    value = authority(); value["route"]["headers"] = {"Authorization": "SYNTHETIC_PRIVATE"}; source.write_text(json.dumps(value))
  if fault == "invalid": source.write_bytes(b"SYNTHETIC_PRIVATE")
  if fault == "parent-link":
    parent = tmp_path / "linked"; parent.symlink_to(tmp_path, target_is_directory=True); source = parent / source.name
  monkeypatch.setattr(module, "ReviewerAuthorityStore", lambda *a, **k: pytest.fail("invalid source constructed store"))
  assert invoke("create", source) == 2
  output = capsys.readouterr(); assert "SYNTHETIC_PRIVATE" not in output.out + output.err and str(source) not in output.out + output.err
  assert list(home.iterdir()) == []


@pytest.mark.parametrize("expected", ["", "a" * 63, "A" * 64, "SYNTHETIC_PRIVATE"])
def test_malformed_expected_rejects_before_store(fixture, monkeypatch, expected):
  home, source = fixture
  monkeypatch.setattr(module, "ReviewerAuthorityStore", lambda *a, **k: pytest.fail("bad expected constructed store"))
  assert invoke("update", source, expected) == 2 and list(home.iterdir()) == []


@pytest.mark.parametrize("fault", ["leaf", "parent"])
def test_source_replacement_during_read_never_constructs_store(fixture, tmp_path, monkeypatch, fault):
  home, source = fixture
  parent = tmp_path / "private-source"; parent.mkdir(mode=0o700)
  source.rename(parent / source.name); source = parent / source.name
  original = module.os.read; fired = []
  def read(fd, size):
    data = original(fd, size)
    if not fired:
      fired.append(True)
      if fault == "leaf":
        source.rename(parent / "detached"); source.write_bytes(data); source.chmod(0o600)
      else:
        parent.rename(tmp_path / "detached-parent"); parent.mkdir(mode=0o700)
        source.write_bytes(data); source.chmod(0o600)
    return data
  monkeypatch.setattr(module.os, "read", read)
  monkeypatch.setattr(module, "ReviewerAuthorityStore", lambda *a, **k: pytest.fail("changed source constructed store"))
  assert invoke("create", source) == 2 and fired and list(home.iterdir()) == []


def test_update_rejects_increase_and_old_expected_without_modifying_authority(fixture, capsys):
  home, source = fixture; assert invoke("create", source) == 0
  old = json.loads(capsys.readouterr().out)["authority"]
  target = home / ".agentcfg-workspaces" / FILE; raw = target.read_bytes()
  value = authority(); value["generation"] = 2; value["limits"]["max_calls"] = 21; source.write_bytes(encode_authority(value))
  assert invoke("update", source, old["identity"]) == 2 and target.read_bytes() == raw
  capsys.readouterr(); value["limits"]["max_calls"] = 10; source.write_bytes(encode_authority(value))
  assert invoke("update", source, old["identity"]) == 0; capsys.readouterr(); after = target.read_bytes()
  assert invoke("update", source, old["identity"]) == 4 and target.read_bytes() == after


@pytest.mark.parametrize("fault", ["before", "after"])
def test_cli_update_ack_loss_is_fixed_and_not_retried(fixture, monkeypatch, capsys, fault):
  home, source = fixture; assert invoke("create", source) == 0
  old = json.loads(capsys.readouterr().out)["authority"]
  value = authority(); value["generation"] = 2; source.write_bytes(encode_authority(value))
  original = Tree.replace; writes = []
  def replace(tree, name, data, *args, **kwargs):
    if name != FILE: return original(tree, name, data, *args, **kwargs)
    writes.append(name)
    if fault == "after": original(tree, name, data, *args, **kwargs)
    raise OSError("SYNTHETIC_PRIVATE")
  monkeypatch.setattr(Tree, "replace", replace)
  assert invoke("update", source, old["identity"]) == 4 and writes == [FILE]
  output = capsys.readouterr(); assert "SYNTHETIC_PRIVATE" not in output.out + output.err
  assert invoke("show") == 0
  observed = json.loads(capsys.readouterr().out)
  assert observed["authority"]["document"]["generation"] == (1 if fault == "before" else 2)


def test_cli_default_format_and_help_document_contract(fixture, capsys):
  home, source = fixture
  assert cli.main(["pi-reviewer-authority", "create", "--document", str(source)]) == 0
  assert "未启用" in capsys.readouterr().out
  with pytest.raises(SystemExit) as error: cli.main(["pi-reviewer-authority", "create", "--help"])
  assert error.value.code == 0 and "0600" in capsys.readouterr().out


def test_source_foreign_uid_rejects_before_store(fixture, monkeypatch):
  home, source = fixture; original = module.os.stat
  def stat(path, *args, **kwargs):
    info = original(path, *args, **kwargs)
    if path == source.name and kwargs.get("follow_symlinks") is False and kwargs.get("dir_fd") is not None:
      fields = {key: getattr(info, key) for key in ("st_mode", "st_uid", "st_nlink", "st_size")}
      fields["st_uid"] += 1
      return SimpleNamespace(**fields)
    return info
  monkeypatch.setattr(module.os, "stat", stat)
  monkeypatch.setattr(module, "ReviewerAuthorityStore", lambda *a, **k: pytest.fail("foreign source constructed store"))
  assert invoke("create", source) == 2 and list(home.iterdir()) == []


def test_private_source_read_error_fixed_and_zero_store(fixture, monkeypatch, capsys):
  home, source = fixture
  monkeypatch.setattr(module.os, "read", lambda *a: (_ for _ in ()).throw(OSError("SYNTHETIC_PRIVATE_READ")))
  monkeypatch.setattr(module, "ReviewerAuthorityStore", lambda *a, **k: pytest.fail("unreadable source constructed store"))
  assert invoke("create", source) == 2 and list(home.iterdir()) == []
  output = capsys.readouterr()
  assert "SYNTHETIC_PRIVATE_READ" not in output.out + output.err and str(source) not in output.out + output.err
