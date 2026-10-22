"""只读的结构化项目发现与路径契约；合成 Git 标记不调用 Git/宿主。"""
from copy import deepcopy
from pathlib import Path
import os

import pytest

from termcfg.errors import TermcfgError
from termcfg.work_config import ROOT, WorkSettings


@pytest.fixture
def projects_api():
  from termcfg import work_projects
  return work_projects


@pytest.fixture
def document():
  return {"model": "structured-v1", "herdr_binary": "fixture-herdr", "session": "trial",
    "include_rotom": False, "templates": {"development": {
      "order": ["shell"], "initial": "shell", "tab_types": {"shell": {"label": "Shell", "launcher": "shell"}}}},
    "sources": [], "workspaces": []}


def directory(parent, name, *, git=False):
  path = parent / name
  path.mkdir(parents=True)
  if git:
    (path / ".git").mkdir()
  return path


def settings_for(api, document, tmp_path, *, repo_root=ROOT):
  local = tmp_path / "selected" / "machine.toml"
  local.parent.mkdir(mode=0o700, exist_ok=True)
  work = api.normalize_work(document, local_path=local, home=tmp_path)
  return WorkSettings(local, "fixture-herdr", "trial", repo_root=repo_root,
    model="structured-v1", structured=work)


def source(path, identifier="projects", *, mode="directory", template="development", **extra):
  return {"id": identifier, "path": str(path), "mode": mode, "template": template, **extra}


def project(path, *, template="development", mode="directory"):
  return {"kind": "project", "path": str(path), "mode": mode, "template": template}


def by_project(result):
  return {Path(candidate.key): candidate for candidate in result.candidates if candidate.kind == "project"}


def test_normalize_materializes_only_declared_defaults_without_mutating_input(projects_api, document, tmp_path):
  root = directory(tmp_path, "projects")
  document["sources"] = [source(root)]
  before = deepcopy(document)
  value = projects_api.normalize_work(document, local_path=tmp_path / "machine.toml", home=tmp_path)
  actual = value["sources"][0]
  assert (actual["depth"], actual["exclude_hidden"], actual["exclude"], actual["follow_symlinks"]) == (1, True, [], False)
  assert value["templates"]["development"]["tab_types"]["shell"]["cwd"] == {"from": "workspace_start"}
  assert document == before


def test_normalize_relative_and_home_paths_are_literal_selected_file_relative(projects_api, document, tmp_path, monkeypatch):
  selected = directory(tmp_path, "selected")
  root = directory(selected, "项目 $()")
  home = directory(tmp_path, "caller-home")
  named = directory(home, "named")
  elsewhere = directory(tmp_path, "elsewhere")
  monkeypatch.chdir(elsewhere)
  document["sources"] = [source("项目 $()")]
  document["workspaces"] = [project("项目 $()"), {"kind": "named", "id": "case-a", "title": "调查",
    "template": "development", "start_path": "~/named"}]
  value = projects_api.normalize_work(document, local_path=selected / "machine.toml", home=home)
  assert Path(value["sources"][0]["path"]) == root.resolve()
  assert Path(value["workspaces"][0]["path"]) == root.resolve()
  assert Path(value["workspaces"][1]["start_path"]) == named.resolve()


@pytest.mark.parametrize("shadowed", [False, True])
def test_enabled_builtin_default_reference_validates_even_when_shadowed(projects_api, document, tmp_path, shadowed):
  document.pop("include_rotom")
  document["templates"]["other"] = document["templates"].pop("development")
  if shadowed:
    document["workspaces"] = [project(ROOT, template="other")]
  with pytest.raises(TermcfgError):
    projects_api.normalize_work(document, local_path=tmp_path / "machine.toml", home=tmp_path)


def test_disabled_builtin_has_no_implicit_template_but_explicit_references_validate(projects_api, document, tmp_path):
  document["templates"] = {}
  value = projects_api.normalize_work(document, local_path=tmp_path / "machine.toml", home=tmp_path)
  assert value["include_rotom"] is False
  for extra in ({"rotom_template": "missing"}, {"sources": [source(tmp_path, template="missing")]},
      {"workspaces": [project(tmp_path, template="missing")]}, {"workspaces": [{"kind": "named",
        "id": "case-a", "title": "Case", "template": "missing"}]}):
    value = deepcopy(document)
    value.update(extra)
    with pytest.raises(TermcfgError):
      projects_api.normalize_work(value, local_path=tmp_path / "machine.toml", home=tmp_path)


@pytest.mark.parametrize("change", ["duplicate-order", "different-key-set", "missing-initial"])
def test_template_order_and_initial_references_fail_instead_of_repair(projects_api, document, tmp_path, change):
  template = document["templates"]["development"]
  if change == "duplicate-order":
    template["order"] = ["shell", "shell"]
  elif change == "different-key-set":
    template["order"] = ["other"]
  else:
    template["initial"] = "other"
  with pytest.raises(TermcfgError) as error:
    projects_api.normalize_work(document, local_path=tmp_path / "machine.toml", home=tmp_path)
  assert error.value.code == 2


def test_source_template_type_and_named_ids_and_nested_unknown_fields_are_strict(projects_api, document, tmp_path):
  root = directory(tmp_path, "projects")
  valid = deepcopy(document)
  valid["sources"] = [source(root)]
  valid["workspaces"] = [{"kind": "named", "id": "case-a", "title": "Case", "template": "development"}]
  variants = []
  for location in ("source", "template", "type", "named", "nested"):
    value = deepcopy(valid)
    if location == "source":
      value["sources"][0]["id"] = "tail\n"
    elif location == "template":
      value["templates"]["9invalid"] = value["templates"].pop("development")
      value["sources"][0]["template"] = value["workspaces"][0]["template"] = "9invalid"
    elif location == "type":
      types = value["templates"]["development"]["tab_types"]
      types["中"] = types.pop("shell")
      value["templates"]["development"].update(order=["中"], initial="中")
    elif location == "named":
      value["workspaces"][0]["id"] = "with.dot"
    else:
      value["templates"]["development"]["tab_types"]["shell"]["command"] = "not a launcher"
    variants.append(value)
  for value in variants:
    with pytest.raises(TermcfgError):
      projects_api.normalize_work(value, local_path=tmp_path / "machine.toml", home=tmp_path)


@pytest.mark.parametrize("marker", ["directory", "file"])
def test_git_boundary_uses_checkout_not_external_worktree_metadata(projects_api, tmp_path, marker, monkeypatch, sentinel_factory):
  checkout = directory(tmp_path, "checkout")
  sub = directory(checkout, "src/deep")
  outside = directory(tmp_path, "external-metadata")
  (outside / "sentinel").write_bytes(b"synthetic metadata sentinel")
  sentinel = sentinel_factory(outside)
  if marker == "directory":
    (checkout / ".git").mkdir()
  else:
    (checkout / ".git").write_text("gitdir: " + str(outside / "unreadable-target") + "\n")
  real_open = Path.open
  def guarded(path, *args, **kwargs):
    if path.is_relative_to(outside):
      pytest.fail("external Git metadata followed")
    return real_open(path, *args, **kwargs)
  monkeypatch.setattr(Path, "open", guarded)
  assert projects_api.canonical_boundary(sub, "git") == checkout.resolve()
  sentinel.assert_unchanged()


def test_directory_mode_keeps_exact_selected_boundary_inside_a_checkout(projects_api, tmp_path, monkeypatch):
  checkout = directory(tmp_path, "checkout", git=True)
  sub = directory(checkout, "business/sub")
  monkeypatch.chdir(checkout)
  assert projects_api.canonical_boundary("business/sub", "directory") == sub.resolve()
  assert projects_api.canonical_boundary(sub, "git") == checkout.resolve()


def test_git_discovery_default_depth_hidden_exclusion_and_no_source_root_candidate(projects_api, document, tmp_path):
  root = directory(tmp_path, "source", git=True)
  visible = directory(root, "visible", git=True)
  directory(root, ".hidden", git=True)
  directory(root, "cache", git=True)
  directory(root, "container/nested", git=True)
  document["sources"] = [source(root, mode="git", exclude=["cache"])]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {visible.resolve()}
  assert isinstance(result.candidates, tuple) and isinstance(result.diagnostics, tuple)


def test_git_depth_two_prunes_hidden_and_excluded_subtrees(projects_api, document, tmp_path):
  root = directory(tmp_path, "source")
  top = directory(root, "top", git=True)
  nested = directory(root, "container/nested")
  (nested / ".git").write_text("gitdir: /synthetic/shared-metadata/worktrees/nested\n")
  directory(root, "container/deeper/too-deep", git=True)
  directory(root, ".hidden/repo", git=True)
  directory(root, "skip/repo", git=True)
  document["sources"] = [source(root, mode="git", depth=2, exclude=["skip"])]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {top.resolve(), nested.resolve()}
  document["sources"][0].update(exclude_hidden=False, exclude=[])
  refreshed = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(refreshed)) == {top.resolve(), nested.resolve(),
    (root / ".hidden/repo").resolve(), (root / "skip/repo").resolve()}


def test_directory_discovery_enumerates_independent_children_without_git_requirement(projects_api, document, tmp_path):
  root = directory(tmp_path, "source")
  first = directory(root, "plain")
  second = directory(root, "checkout", git=True)
  directory(first, "nested")
  document["sources"] = [source(root)]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {first.resolve(), second.resolve()}
  assert all(candidate.mode == "directory" for candidate in result.candidates)


def test_default_discovery_does_not_follow_directory_links(projects_api, document, tmp_path):
  root = directory(tmp_path, "source")
  outside = directory(tmp_path, "outside")
  (root / "alias").symlink_to(outside, target_is_directory=True)
  document["sources"] = [source(root)]
  assert not projects_api.discover(settings_for(projects_api, document, tmp_path)).candidates


def test_following_links_is_contained_cycle_safe_and_canonical_deduplicated(projects_api, document, tmp_path):
  root = directory(tmp_path, "source")
  checkout = directory(root, "checkout", git=True)
  outside = directory(tmp_path, "outside", git=True)
  (root / "alias").symlink_to(checkout, target_is_directory=True)
  (root / "escape").symlink_to(outside, target_is_directory=True)
  (root / "cycle").symlink_to(root, target_is_directory=True)
  document["sources"] = [source(root, mode="git", depth=4, follow_symlinks=True)]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {checkout.resolve()}


def test_unreadable_source_is_diagnostic_while_other_candidates_remain(projects_api, document, tmp_path, monkeypatch):
  root = directory(tmp_path, "source")
  useful = directory(tmp_path, "explicit")
  document["sources"] = [source(root)]
  document["workspaces"] = [project(useful)]
  settings = settings_for(projects_api, document, tmp_path)
  for name in ("listdir", "scandir"):
    original = getattr(os, name)
    def denied(path, *args, _original=original, **kwargs):
      if not isinstance(path, int) and Path(path) == root:
        raise PermissionError("synthetic unreadable source")
      return _original(path, *args, **kwargs)
    monkeypatch.setattr(os, name, denied)
  result = projects_api.discover(settings)
  assert set(by_project(result)) == {useful.resolve()} and result.diagnostics


def test_explicit_project_overrides_source_and_builtin_for_same_boundary(projects_api, document, tmp_path):
  document["include_rotom"] = True
  document["templates"]["explicit"] = deepcopy(document["templates"]["development"])
  document["sources"] = [source(ROOT.parent)]
  document["workspaces"] = [project(ROOT, template="explicit")]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  matching = [candidate for candidate in result.candidates if candidate.kind == "project" and Path(candidate.key) == ROOT.resolve()]
  assert len(matching) == 1 and matching[0].template == "explicit"


def test_most_specific_source_selects_template_for_canonical_duplicate(projects_api, document, tmp_path):
  root = directory(tmp_path, "source")
  inner = directory(root, "inner")
  checkout = directory(inner, "checkout", git=True)
  document["templates"]["specific"] = deepcopy(document["templates"]["development"])
  document["sources"] = [source(root, "wide", mode="git", depth=2),
    source(inner, "narrow", mode="git", template="specific")]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert by_project(result)[checkout.resolve()].template == "specific"


def test_compatible_alias_project_registrations_coalesce(projects_api, document, tmp_path):
  root = directory(tmp_path, "project")
  alias = tmp_path / "alias"
  alias.symlink_to(root, target_is_directory=True)
  document["workspaces"] = [project(root), project(alias)]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {root.resolve()}


def test_equal_priority_incompatible_project_definitions_fail(projects_api, document, tmp_path):
  root = directory(tmp_path, "project")
  document["templates"]["other"] = deepcopy(document["templates"]["development"])
  document["workspaces"] = [project(root), project(root, template="other")]
  with pytest.raises(TermcfgError):
    projects_api.discover(settings_for(projects_api, document, tmp_path))


def test_duplicate_source_id_with_different_boundary_fails(projects_api, document, tmp_path):
  first = directory(tmp_path, "first")
  second = directory(tmp_path, "second")
  document["sources"] = [source(first), source(second)]
  with pytest.raises(TermcfgError):
    projects_api.normalize_work(document, local_path=tmp_path / "machine.toml", home=tmp_path)


def test_duplicate_display_names_keep_distinct_canonical_identities(projects_api, document, tmp_path):
  first = directory(tmp_path, "first/same")
  second = directory(tmp_path, "second/same")
  document["workspaces"] = [project(first), project(second)]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {first.resolve(), second.resolve()}
  assert {candidate.title for candidate in result.candidates} == {"same"}


def test_named_contexts_can_share_home_while_retaining_distinct_ids(projects_api, document, tmp_path):
  document["workspaces"] = [{"kind": "named", "id": identifier, "title": "Same title",
    "template": "development", "start_path": str(tmp_path)} for identifier in ("case-a", "case-b")]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert {candidate.key for candidate in result.candidates} == {"case-a", "case-b"}
  assert all(candidate.kind == "named" and Path(candidate.start_path) == tmp_path.resolve() for candidate in result.candidates)


def test_builtin_uses_verified_executing_root_not_cwd_and_candidates_are_frozen(projects_api, document, tmp_path, monkeypatch):
  document["include_rotom"] = True
  monkeypatch.chdir(tmp_path)
  result = projects_api.discover(settings_for(projects_api, document, tmp_path))
  assert set(by_project(result)) == {ROOT.resolve()}
  candidate = next(iter(result.candidates))
  with pytest.raises((AttributeError, TypeError)):
    candidate.title = "not mutable"


def test_unverified_executing_root_diagnoses_without_hiding_other_candidates(projects_api, document, tmp_path):
  invalid = directory(tmp_path, "unverified-executing-root")
  valid = directory(tmp_path, "configured")
  document["include_rotom"] = True
  document["workspaces"] = [project(valid)]
  result = projects_api.discover(settings_for(projects_api, document, tmp_path, repo_root=invalid))
  assert set(by_project(result)) == {valid.resolve()} and result.diagnostics


def test_refresh_reenumerates_source_without_persisting_discovery_snapshot(projects_api, document, tmp_path, sentinel_factory):
  root = directory(tmp_path, "source")
  document["sources"] = [source(root)]
  settings = settings_for(projects_api, document, tmp_path)
  before = sentinel_factory(tmp_path)
  assert not projects_api.discover(settings).candidates
  before.assert_unchanged()
  added = directory(root, "later")
  before = sentinel_factory(tmp_path)
  assert set(by_project(projects_api.discover(settings))) == {added.resolve()}
  before.assert_unchanged()


def test_resolve_project_uses_cli_cwd_then_configured_directory_boundary(projects_api, document, tmp_path, monkeypatch):
  root = directory(tmp_path, "project")
  sub = directory(root, "business/sub")
  document["workspaces"] = [project(root)]
  settings = settings_for(projects_api, document, tmp_path)
  monkeypatch.chdir(root)
  result = projects_api.resolve_project(settings, "business/sub")
  assert result.kind == "project" and Path(result.key) == root.resolve()
  assert projects_api.canonical_boundary(sub, "directory") == sub.resolve()


def test_missing_explicit_boundary_fails_without_mkdir_or_fallback(projects_api, tmp_path):
  missing = tmp_path / "missing"
  for mode in ("git", "directory"):
    with pytest.raises(TermcfgError):
      projects_api.canonical_boundary(missing, mode)
  assert not missing.exists()
def test_public_structured_example_with_fixture_paths(tmp_path):
  import tomlkit
  from termcfg.work_config import ROOT, settings_from_document
  source = (ROOT / "examples/work-structured.toml").read_text()
  assert source.isascii()
  doc = tomlkit.parse(source).unwrap()
  for name in ("projects", "cases", "cases/current"):
    (tmp_path / name).mkdir(parents=True, exist_ok=True)
  for item in doc["machine"]["work"]["sources"]:
    item["path"] = str(tmp_path / item["path"].lstrip("/"))
  for item in doc["machine"]["work"]["workspaces"]:
    if item["kind"] == "project":
      item["path"] = str(tmp_path / item["path"].lstrip("/"))
  settings = settings_from_document(doc, local=tmp_path / "local.toml")
  assert settings.structured["templates"]["development"]["order"] == ["shell", "edit", "build", "test", "agent"]
  assert settings.structured["templates"]["investigation"]["order"] == ["code", "agent", "problem"]
