"""公共快照只读临时文件，不依赖受管 Worker 或委派控制器。"""

import builtins
import importlib.util

import pytest

from agentcfg.pi_workspace_snapshot import snapshot
from agentcfg.storage import Conflict


def test_snapshot_import_is_independent_of_full_worker_and_delegate_modules(monkeypatch):
  forbidden = ("pi_worker_files", "pi_worker_protocol", "pi_delegate", "pi_codex", "pi_host", "pi_operations")
  original = builtins.__import__
  seen = []
  def guarded(name, globals=None, locals=None, fromlist=(), level=0):
    seen.append(name)
    assert not any(part in name for part in forbidden), name
    return original(name, globals, locals, fromlist, level)
  monkeypatch.setattr(builtins, "__import__", guarded)
  spec = importlib.util.spec_from_file_location("agentcfg._snapshot_import_probe", snapshot.__code__.co_filename)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  assert callable(module.snapshot) and seen


def test_legacy_snapshot_import_is_the_same_public_function():
  from agentcfg.pi_worker_files import snapshot as legacy
  from agentcfg.pi_workspace_snapshot import snapshot as public
  assert legacy is public


def test_content_and_executable_bits_change_snapshot(tmp_path):
  path = tmp_path / "source.txt"; path.write_text("before"); path.chmod(0o600)
  before = snapshot(tmp_path)
  path.write_text("after")
  changed = snapshot(tmp_path)
  assert changed != before
  path.chmod(0o700)
  assert snapshot(tmp_path) != changed
  path.chmod(0o600)
  assert snapshot(tmp_path) == changed


@pytest.mark.parametrize("selected", [False, True])
def test_secret_and_git_contents_do_not_affect_snapshot(tmp_path, selected):
  secret = tmp_path / "secret"; secret.mkdir(); (secret / "credential").write_text("synthetic first")
  git = tmp_path / ".git"; git.mkdir(); (git / "HEAD").write_text("first git metadata")
  code = tmp_path / "code"; code.write_text("business source")
  options = {"source_paths": ["code", "secret/credential"]} if selected else {}
  before = snapshot(tmp_path, protected_roots=[secret], **options)
  (secret / "credential").write_text("synthetic changed")
  (git / "HEAD").write_text("changed git metadata")
  assert snapshot(tmp_path, protected_roots=[secret], **options) == before
  code.write_text("changed business source")
  assert snapshot(tmp_path, protected_roots=[secret], **options) != before


def test_selected_scope_ignores_unselected_changes_and_tracks_missing_files(tmp_path):
  (tmp_path / "code").write_text("source"); (tmp_path / "build").write_text("output")
  options = {"source_paths": ["code", "future", "code"]}
  before = snapshot(tmp_path, **options)
  assert snapshot(tmp_path, source_paths=["future", "code"]) == before
  (tmp_path / "build").write_text("changed output")
  assert snapshot(tmp_path, **options) == before
  (tmp_path / "future").write_text("new source")
  assert snapshot(tmp_path, **options) != before


@pytest.mark.parametrize("selected", [False, True])
def test_symlink_snapshot_tracks_link_text_without_reading_target(tmp_path, selected):
  root = tmp_path / "root"; root.mkdir()
  target = tmp_path / "outside"; target.write_text("outside first")
  link = root / "link"; link.symlink_to(target)
  options = {"source_paths": ["link"]} if selected else {}
  before = snapshot(root, **options)
  target.write_text("outside changed")
  assert snapshot(root, **options) == before
  link.unlink(); link.symlink_to(tmp_path / "missing-target")
  assert snapshot(root, **options) != before


def test_selected_git_scope_is_rejected_and_hardlinks_remain_unsupported(tmp_path):
  with pytest.raises(Conflict, match="SNAPSHOT_SCOPE_INVALID"):
    snapshot(tmp_path, source_paths=[".git/HEAD"])
  import os
  path = tmp_path / "file"; path.write_text("source")
  os.link(path, tmp_path / "alias")
  with pytest.raises(Conflict, match="SNAPSHOT_UNSUPPORTED_FILE"):
    snapshot(tmp_path)
