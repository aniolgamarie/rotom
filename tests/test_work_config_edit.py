"""单一私人 TOML 的保留式修改；编辑器与进程全部为替身。"""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit

from termcfg.errors import TermcfgError
from termcfg.work_config import read_settings


def local_settings(tmp_path):
  parent = tmp_path / "private"
  parent.mkdir(mode=0o700)
  path = parent / "local.toml"
  path.write_text('# retained header\nschema_version = 1\n[machine]\nid = "fixture"\n'
    'editor = "/opt/fixture-editor" # retained editor\n'
    '[machine.work]\nmodel = "structured-v1"\nherdr_binary = "fixture-herdr"\nsession = "trial"\n'
    'include_rotom = false\n# retained type\n'
    '[machine.work.templates.dev]\norder = ["shell"]\ninitial = "shell"\n'
    '[machine.work.templates.dev.tab_types.shell]\nlabel = "Shell"\nlauncher = "shell"\n')
  path.chmod(0o600)
  return read_settings(local=path)


def propose(settings, operation="named-add", **values):
  from termcfg.work_edit import preview
  values = {"id": "case-a", "title": "调查", "template": "dev", **values} if operation == "named-add" else values
  return preview(settings, operation, values)


def test_preview_has_only_work_fragment_and_zero_filesystem_effects(tmp_path, sentinel_factory):
  settings = local_settings(tmp_path)
  before = sentinel_factory(tmp_path)
  proposal = propose(settings)
  assert proposal.changed
  assert "调查" in proposal.fragment
  assert "retained header" not in proposal.fragment and "[machine]" not in proposal.fragment
  before.assert_unchanged()


def test_source_preview_retains_actual_candidates_and_canonical_boundary(tmp_path, sentinel_factory):
  settings = local_settings(tmp_path)
  root = tmp_path / "projects"
  root.mkdir()
  (root / "first").mkdir()
  (root / "second").mkdir()
  before = sentinel_factory(tmp_path)
  proposal = propose(settings, "source-add", id="projects", path=str(root), mode="directory", template="dev")
  assert {item.key for item in proposal.discovery.candidates} == {str(root / "first"), str(root / "second")}
  assert all(item.mode == "directory" and item.origin == "source:projects" for item in proposal.discovery.candidates)
  assert str(root) in proposal.fragment
  before.assert_unchanged()


def test_preserving_save_and_idempotent_repeat(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  result = save(propose(settings))
  after = settings.local_path.read_bytes()
  assert result.changed and b"# retained header" in after and b"# retained editor" in after
  assert b"# retained type" in after
  assert settings.local_path.stat().st_mode & 0o777 == 0o600
  result = save(propose(read_settings(local=settings.local_path)))
  assert not result.changed and settings.local_path.read_bytes() == after


def test_conflicting_repeat_refuses_without_write(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  save(propose(settings))
  before = settings.local_path.read_bytes()
  with pytest.raises(TermcfgError) as error:
    propose(read_settings(local=settings.local_path), title="Different")
  assert error.value.code == 2 and settings.local_path.read_bytes() == before


def test_observed_external_edit_refuses_stale_proposal(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  proposal = propose(settings)
  settings.local_path.write_bytes(settings.local_path.read_bytes() + b"\n# manual edit\n")
  before = settings.local_path.read_bytes()
  with pytest.raises(TermcfgError) as error:
    save(proposal)
  assert error.value.code == 4 and settings.local_path.read_bytes() == before


def test_project_cli_path_uses_invocation_cwd_and_git_actual_boundary(tmp_path, monkeypatch):
  settings = local_settings(tmp_path)
  checkout = tmp_path / "project with space"
  checkout.mkdir()
  (checkout / ".git").mkdir()
  (checkout / "nested").mkdir()
  monkeypatch.chdir(tmp_path)
  proposal = propose(settings, "project-add", path="project with space/nested", mode="git", template="dev")
  work = tomlkit.parse(proposal.fragment).unwrap()
  assert work["workspaces"][0]["path"] == str(checkout)


@pytest.mark.parametrize("mode", ["source-add", "project-add"])
def test_registration_does_not_create_missing_directories(tmp_path, mode):
  settings = local_settings(tmp_path)
  destination = tmp_path / "absent"
  values = {"path": str(destination), "mode": "directory", "template": "dev"}
  if mode == "source-add":
    values["id"] = "projects"
  with pytest.raises(TermcfgError) as error:
    propose(settings, mode, **values)
  assert error.value.code == 2 and not destination.exists()


def fake_editor(tmp_path, monkeypatch, change=None, code=0, check=None):
  from termcfg import work_edit
  executable = tmp_path / "fixture editor"
  executable.write_text("synthetic, never executed")
  executable.chmod(0o700)
  monkeypatch.setattr(work_edit, "resolve_executable", lambda _: str(executable))
  def run(argv, **kwargs):
    assert argv[0] == str(executable) and len(argv) == 2
    staged = Path(argv[1])
    assert staged.stat().st_mode & 0o777 == 0o600
    content = staged.read_text()
    assert "schema_version" not in content and "fixture-editor" not in content
    if check:
      check(staged)
    if change:
      staged.write_text(change(content))
    return SimpleNamespace(returncode=code)
  return run


def test_fragment_editor_only_stages_work_and_preserves_noop_bytes(tmp_path, monkeypatch):
  from termcfg.work_edit import edit
  settings = local_settings(tmp_path)
  before = settings.local_path.read_bytes()
  paths = []
  result = edit(settings, run=fake_editor(tmp_path, monkeypatch, check=paths.append))
  assert not result.changed and settings.local_path.read_bytes() == before
  assert paths and all(not p.exists() for p in paths)


@pytest.mark.parametrize("code,change,expected", [(27, None, 27), (0, lambda _: 'unknown = true\n', 2)])
def test_editor_failure_or_invalid_edit_preserves_original(tmp_path, monkeypatch, code, change, expected):
  from termcfg.work_edit import edit
  settings = local_settings(tmp_path)
  before = settings.local_path.read_bytes()
  with pytest.raises(TermcfgError) as error:
    edit(settings, run=fake_editor(tmp_path, monkeypatch, change, code))
  assert error.value.code == expected and settings.local_path.read_bytes() == before


def test_editor_merges_work_only_and_detects_parallel_manual_edit(tmp_path, monkeypatch):
  from termcfg.work_edit import edit
  settings = local_settings(tmp_path)
  def outside(_):
    settings.local_path.write_bytes(settings.local_path.read_bytes() + b"\n# outside\n")
  before = settings.local_path.read_bytes() + b"\n# outside\n"
  with pytest.raises(TermcfgError) as error:
    edit(settings, run=fake_editor(tmp_path, monkeypatch,
      lambda text: text.replace('session = "trial"', 'session = "changed"'), check=outside))
  assert error.value.code == 4 and settings.local_path.read_bytes() == before


def test_symlink_machine_file_and_unrelated_secret_resolution_are_refused(tmp_path, monkeypatch):
  from agentcfg.secrets import SecretStore
  monkeypatch.setattr(SecretStore, "resolve", lambda *a, **k: pytest.fail("secret resolution"))
  settings = local_settings(tmp_path)
  proposal = propose(settings)
  original = settings.local_path.with_suffix(".original")
  settings.local_path.rename(original)
  settings.local_path.symlink_to(original)
  from termcfg.work_edit import save
  with pytest.raises(TermcfgError) as error:
    save(proposal)
  assert error.value.code == 4 and original.read_bytes() == proposal.original


def test_cooperating_writer_is_serialized_across_replacement(tmp_path):
  from termcfg.work_edit import config_lock
  settings = local_settings(tmp_path)
  with config_lock(settings.local_path, timeout=0):
    with pytest.raises(TermcfgError) as error:
      with config_lock(settings.local_path, timeout=0):
        pytest.fail("second writer acquired lock")
    assert error.value.code == 4


def test_named_rename_preserves_comments_in_all_workspace_array_entries(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  with settings.local_path.open("a") as stream:
    stream.write('\n# first context\n[[machine.work.workspaces]]\nkind = "named"\nid = "case-a"\n'
      'title = "First" # title annotation\ntemplate = "dev"\n'
      '# second context\n[[machine.work.workspaces]]\nkind = "named"\nid = "case-b"\n'
      'title = "Second"\ntemplate = "dev"\n')
  save(propose(read_settings(local=settings.local_path), "named-rename", id="case-a", title="Renamed"))
  content = settings.local_path.read_text()
  assert "# first context" in content and "# second context" in content and "# title annotation" in content
  assert 'title = "Second"' in content and 'title = "Renamed"' in content


def test_source_add_saves_rule_without_mutating_or_snapshotting_discovered_projects(tmp_path, sentinel_factory):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  root = tmp_path / "business-source"
  root.mkdir()
  child = root / "project-a"
  child.mkdir()
  (child / ".git").write_text("gitdir: /synthetic/unreadable-metadata/project-a\n")
  before = sentinel_factory(root)
  proposal = propose(settings, "source-add", id="projects", path=str(root), mode="git", template="dev")
  assert save(proposal).changed
  ordinary = tomlkit.parse(settings.local_path.read_text()).unwrap()["machine"]["work"]
  assert ordinary["sources"] == [{"id": "projects", "path": str(root), "mode": "git", "template": "dev"}]
  assert ordinary.get("workspaces", []) == [] and "project-a" not in proposal.fragment
  before.assert_unchanged()


def test_manual_relative_source_and_explicit_cli_defaults_are_compatible_noop(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  root = settings.local_path.parent / "projects"
  root.mkdir()
  with settings.local_path.open("a") as stream:
    stream.write('\n# manually maintained source\n[[machine.work.sources]]\n'
      'id = "projects"\npath = "projects"\nmode = "directory"\ntemplate = "dev"\n')
  fresh = read_settings(local=settings.local_path)
  before = settings.local_path.read_bytes()
  inode = settings.local_path.stat().st_ino
  proposal = propose(fresh, "source-add", id="projects", path=str(root), mode="directory", template="dev",
    depth=1, exclude_hidden=True, exclude=[], follow_symlinks=False)
  assert not proposal.changed and not save(proposal).changed
  assert settings.local_path.read_bytes() == before and settings.local_path.stat().st_ino == inode


def test_inline_secret_is_never_staged_hashed_or_copied_outside_necessary_machine_publish(tmp_path, monkeypatch):
  import hashlib
  from agentcfg.storage import Tree
  from termcfg import work_edit
  settings = local_settings(tmp_path)
  canary = b"SYNTHETIC-CONFIG-EDIT-SECRET-CANARY"
  with settings.local_path.open("ab") as stream:
    stream.write(b'\n[secrets]\nselected = "' + canary + b'"\n')
  monkeypatch.setattr("agentcfg.config.load_secrets", lambda *a, **k: pytest.fail("credentials loaded"))
  settings = read_settings(local=settings.local_path)
  real_new, real_replace, real_hash = Tree.write_new, Tree.replace, hashlib.sha256
  publishes = []
  def new(tree, name, data):
    assert canary not in data, "secret-bearing editor staging"
    return real_new(tree, name, data)
  def replace(tree, name, data, *args, **kwargs):
    if data is not None and canary in data:
      assert tree.root == settings.local_path.parent and name == settings.local_path.name
      publishes.append(name)
    return real_replace(tree, name, data, *args, **kwargs)
  class CheckedDigest:
    def __init__(self, wrapped):
      self.wrapped = wrapped
    def update(self, data):
      assert canary not in data, "secret-bearing whole-file digest update"
      self.wrapped.update(data)
    def __getattr__(self, name):
      return getattr(self.wrapped, name)
  def hash_plain(data=b"", *args, **kwargs):
    assert canary not in data, "secret-bearing whole-file digest"
    return CheckedDigest(real_hash(data, *args, **kwargs))
  monkeypatch.setattr(Tree, "write_new", new)
  monkeypatch.setattr(Tree, "replace", replace)
  monkeypatch.setattr(hashlib, "sha256", hash_plain)
  staged_paths = []
  def inspect(staged):
    staged_paths.append(staged)
    assert canary not in staged.read_bytes()
    assert "[secrets]" not in staged.read_text()
  result = work_edit.edit(settings, run=fake_editor(tmp_path, monkeypatch,
    lambda text: text.replace('session = "trial"', 'session = "changed"'), check=inspect))
  assert result.changed and canary.decode() not in result.fragment
  assert publishes == [settings.local_path.name]
  assert canary in settings.local_path.read_bytes()
  assert staged_paths and all(not path.exists() for path in staged_paths)
  for path in Path(os.environ["XDG_STATE_HOME"]).rglob("*"):
    if path.is_file():
      assert canary not in path.read_bytes()
  assert {path.name for path in settings.local_path.parent.iterdir()} == {settings.local_path.name}


def test_changed_unsafe_permissions_refuse_with_manual_work_fragment(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  proposal = propose(settings)
  before = settings.local_path.read_bytes()
  settings.local_path.chmod(0o644)
  with pytest.raises(TermcfgError) as error:
    save(proposal)
  assert error.value.code == 4 and settings.local_path.read_bytes() == before
  assert settings.local_path.stat().st_mode & 0o777 == 0o644
  assert getattr(error.value, "fragment", None) == proposal.fragment
  assert "[machine]" not in error.value.fragment


@pytest.mark.parametrize("operation", ["preview", "editor"])
def test_initial_unsafe_configuration_refuses_before_read_or_lock_with_fragment(tmp_path, monkeypatch,
    sentinel_factory, operation):
  from agentcfg.storage import Tree
  from termcfg import work_edit
  settings = local_settings(tmp_path)
  settings.local_path.chmod(0o400)
  original = Tree.open_read
  from contextlib import contextmanager
  @contextmanager
  def read(tree, path, **kwargs):
    with original(tree, path, **kwargs) as (stream, info):
      class Guard:
        def read(self, *args):
          pytest.fail("unsafe body was read")
      yield Guard(), info
  monkeypatch.setattr(Tree, "open_read", read)
  before = sentinel_factory(tmp_path)
  with pytest.raises(TermcfgError) as error:
    if operation == "preview":
      propose(settings)
    else:
      work_edit.edit(settings, run=lambda *a, **k: pytest.fail("editor launched"))
  assert error.value.code == 4 and getattr(error.value, "fragment", None)
  before.assert_unchanged()


def test_readonly_filesystem_refuses_with_manual_fragment_and_unchanged_machine(tmp_path, monkeypatch):
  import errno
  from agentcfg.storage import Tree
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  proposal = propose(settings)
  before = settings.local_path.read_bytes()
  original = Tree.replace
  def readonly(tree, name, *args, **kwargs):
    if tree.root == settings.local_path.parent and name == settings.local_path.name:
      raise OSError(errno.EROFS, "synthetic read-only filesystem")
    return original(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", readonly)
  with pytest.raises(TermcfgError) as error:
    save(proposal)
  assert error.value.code == 6 and settings.local_path.read_bytes() == before
  assert getattr(error.value, "fragment", None) == proposal.fragment


def test_fragment_editor_on_readonly_mount_keeps_validated_manual_edit(tmp_path, monkeypatch):
  import errno
  from agentcfg.storage import Tree
  from termcfg.work_edit import edit
  settings = local_settings(tmp_path)
  before = settings.local_path.read_bytes()
  original = Tree.replace
  def readonly(tree, name, *args, **kwargs):
    if tree.root == settings.local_path.parent:
      raise OSError(errno.EROFS, "synthetic read-only filesystem")
    return original(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", readonly)
  with pytest.raises(TermcfgError) as error:
    edit(settings, run=fake_editor(tmp_path, monkeypatch,
      lambda content: content.replace('session = "trial"', 'session = "edited"')))
  assert error.value.code == 6 and 'session = "edited"' in error.value.fragment
  assert settings.local_path.read_bytes() == before


def test_fresh_save_after_manual_edit_preserves_manual_content(tmp_path):
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  stale = propose(settings)
  with settings.local_path.open("a") as stream:
    stream.write("\n# accepted manual edit between saves\n")
  changed = settings.local_path.read_bytes()
  with pytest.raises(TermcfgError) as error:
    save(stale)
  assert error.value.code == 4 and settings.local_path.read_bytes() == changed
  fresh = read_settings(local=settings.local_path)
  assert save(propose(fresh)).changed
  after = settings.local_path.read_bytes()
  assert b"# accepted manual edit between saves" in after
  assert [item["id"] for item in read_settings(local=settings.local_path).structured["workspaces"]] == ["case-a"]


def test_directory_fsync_failure_after_replace_reports_uncertain_without_claiming_rollback(tmp_path, monkeypatch):
  import stat
  from termcfg.work_edit import save
  settings = local_settings(tmp_path)
  proposal = propose(settings)
  before = settings.local_path.read_bytes()
  real_replace, real_fsync = os.replace, os.fsync
  published = []
  def replace(source, target, *args, **kwargs):
    result = real_replace(source, target, *args, **kwargs)
    if target == settings.local_path.name:
      published.append(True)
    return result
  def fsync(fd):
    if published and stat.S_ISDIR(os.fstat(fd).st_mode):
      raise OSError("synthetic post-replace directory fsync failure")
    return real_fsync(fd)
  monkeypatch.setattr(os, "replace", replace)
  monkeypatch.setattr(os, "fsync", fsync)
  with pytest.raises(TermcfgError) as error:
    save(proposal)
  assert published and error.value.code == 6
  assert "uncertain" in error.value.reason and "rollback" not in error.value.reason
  assert settings.local_path.read_bytes() == proposal.output != before
  assert getattr(error.value, "fragment", None) == proposal.fragment
