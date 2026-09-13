"""4.2/4.3：真实包字节、路径边界及 loader→resolver→候选；不运行包脚本。"""

import importlib
import os
from pathlib import Path
import re
import traceback

import pytest
import yaml

from agentcfg import config, render, schema
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from test_config_resolution import ResolutionAdapter, resolution_inputs, resolve


REPO = Path(__file__).resolve().parents[1]
LITERAL = "中文 {{example}} $() `backticks`\r\n".encode()


def skills_api():
  assert importlib.util.find_spec("agentcfg.skills") is not None, "skill package collector missing"
  return importlib.import_module("agentcfg.skills")


@pytest.fixture
def package(tmp_path):
  root = tmp_path / "repository"
  skill = root / "shared/skills/one"
  files = {
    "SKILL.md": b"---\nname: one\ndescription: Use when testing packages\n---\n[guide](references/guide.md)\n",
    "references/guide.md": b"[asset](../assets/\xe4\xb8\xad\xe6\x96\x87/data.bin)\n",
    "assets/中文/data.bin": b"\x00\xff" + LITERAL,
    "scripts/nested/check.sh": b"#!/bin/sh\nprintf executed > MUST-NOT-EXIST\n",
    "ordinary.txt": LITERAL,
    ".hidden": b"ordinary hidden resource\n",
  }
  for name, content in files.items():
    path = skill / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
  (skill / "scripts/nested/check.sh").chmod(0o751)
  return root, skill, files


def collect(package, **kwargs):
  return skills_api().collect_skills(package[0], {"one": {"path": "shared/skills/one"}},
                                     target_root=kwargs.get("target_root", "native/skills"))


def test_collect_skills_complete_nested_bytes_modes_no_writes(package, sentinel_factory):
  before = sentinel_factory(package[0].parent)
  first = collect(package)
  assert first == collect(package)
  assert [a.target.path for a in first] == sorted("native/skills/one/" + name for name in package[2])
  assert {a.target.path.removeprefix("native/skills/one/"): a.content for a in first} == package[2]
  assert all(type(a) is Artifact and a.target.ownership is Ownership.FILE
             and a.target.serialization == "bytes" and a.target.selector is None for a in first)
  assert {a.target.path: a.mode for a in first if a.mode == 0o700} == {
    "native/skills/one/scripts/nested/check.sh": 0o700}
  assert all(a.mode == 0o600 for a in first if not a.target.path.endswith("check.sh"))
  before.assert_unchanged()


@pytest.mark.parametrize("mode,expected", [(0o644, 0o600), (0o001, 0o700), (0o010, 0o700), (0o100, 0o700), (0o4755, 0o700)])
def test_collect_skills_preserves_only_executable_intent(package, mode, expected):
  script = package[1] / "scripts/nested/check.sh"
  script.chmod(mode | 0o400)
  assert next(a.mode for a in collect(package) if a.target.path.endswith("check.sh")) == expected


@pytest.mark.parametrize("path", ["../one", "/absolute", "shared//one", "shared/./one", "shared/../one", "shared\\one", "one\nprivate"])
def test_collect_skills_rejects_unsafe_source_target_and_override_paths(package, path):
  api = skills_api()
  for definition in ({"path": path}, {"path": "shared/skills/one", "override": path}):
    with pytest.raises(api.SkillError):
      api.collect_skills(package[0], {"one": definition}, target_root="native/skills")
  with pytest.raises(api.SkillError):
    collect(package, target_root=path)


@pytest.mark.parametrize("name", ["..", "/absolute", "one/two", "one\\two", "bad\nname"])
def test_collect_skills_rejects_unsafe_stable_ids(package, name):
  api = skills_api()
  with pytest.raises(api.SkillError):
    api.collect_skills(package[0], {name: {"path": "shared/skills/one"}}, target_root="skills")


@pytest.mark.parametrize("position", ["root", "ancestor", "package", "intermediate", "file", "broken", "skill"])
def test_collect_skills_rejects_symlinks_at_every_layer(package, position, tmp_path, sentinel_factory):
  api = skills_api()
  root, skill, _ = package
  external = tmp_path / "outside"
  external.mkdir()
  (external / "private").write_bytes(b"synthetic-private-resource")
  if position == "root":
    link = tmp_path / "linked-root"
    link.symlink_to(root, target_is_directory=True)
    root = link
  elif position == "ancestor":
    link = tmp_path / "linked-parent"
    link.symlink_to(tmp_path, target_is_directory=True)
    root = link / "repository"
  elif position == "package":
    skill.rename(skill.with_name("real"))
    skill.symlink_to(skill.with_name("real"), target_is_directory=True)
  elif position == "intermediate":
    (skill / "assets/link").symlink_to(external, target_is_directory=True)
  elif position == "skill":
    (skill / "SKILL.md").unlink()
    (skill / "SKILL.md").symlink_to(external / "private")
  else:
    (skill / "assets/link").symlink_to(external / ("missing" if position == "broken" else "private"))
  before = sentinel_factory(tmp_path)
  with pytest.raises(api.SkillError) as caught:
    api.collect_skills(root, {"one": {"path": "shared/skills/one"}}, target_root="skills")
  assert caught.value.__context__ is None and caught.value.__cause__ is None
  assert "synthetic-private-resource" not in "".join(traceback.format_exception(caught.value))
  before.assert_unchanged()


def test_collect_skills_rejects_special_files_without_opening_them(package, monkeypatch):
  api = skills_api()
  fifo = package[1] / "assets/fifo"
  os.mkfifo(fifo)
  original = os.open

  def checked(path, *args, **kwargs):
    assert path != "fifo", "must reject special files before opening"
    return original(path, *args, **kwargs)

  monkeypatch.setattr(os, "open", checked)
  with pytest.raises(api.SkillError):
    collect(package)


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_collect_skills_requires_regular_top_level_skill_markdown(package, kind):
  api = skills_api()
  main = package[1] / "SKILL.md"
  main.unlink()
  if kind == "directory":
    main.mkdir()
  with pytest.raises(api.SkillError):
    collect(package)


def test_collect_skills_rejects_file_identity_change_before_read(package, monkeypatch):
  api = skills_api()
  original = os.open

  def swap(path, *args, **kwargs):
    if path == "ordinary.txt":
      victim = package[1] / path
      victim.rename(victim.with_name("old.txt"))
      victim.write_bytes(b"changed")
    return original(path, *args, **kwargs)

  monkeypatch.setattr(os, "open", swap)
  with pytest.raises(api.SkillError):
    collect(package)


def test_collect_skills_rejects_overlapping_source_packages(package):
  api = skills_api()
  (package[1] / "assets/SKILL.md").write_bytes(b"nested skill")
  for definitions in (
    {"one": {"path": "shared/skills/one"}, "alias": {"path": "shared/skills/one"}},
    {"one": {"path": "shared/skills/one"}, "child": {"path": "shared/skills/one/assets"}},
  ):
    with pytest.raises(api.SkillError):
      api.collect_skills(package[0], definitions, target_root="skills")


def test_collect_skills_ignores_unselected_packages_and_keeps_stable_registry_name(package):
  api = skills_api()
  (package[0] / "shared/skills/unselected").symlink_to("missing")
  assert api.collect_skills(package[0], {}, target_root="skills") == ()
  result = api.collect_skills(package[0], {"stable-name": {"path": "shared/skills/one"}}, target_root="skills")
  assert all(a.target.path.startswith("skills/stable-name/") for a in result)


def load_registries(tmp_path, texts):
  paths = []
  for index, text in enumerate(texts):
    path = tmp_path / f"skills-{index}.toml"
    path.write_text("schema_version = 1\n" + text)
    paths.append(path)
  return config.load_sources(config.SourceInputs(registries=tuple(paths)), adapter_schemas=schema.AdapterSchemas())


def test_load_sources_explicit_whole_package_override_keeps_both_source_identities(tmp_path):
  result = load_registries(tmp_path, [
    '[skills.one]\npath = "shared/skills/one"\n',
    '[skills.one]\npath = "agents/fixture/skills/one"\noverride = "shared/skills/one"\n',
  ])
  assert result.registry["skills"]["one"] == {
    "path": "agents/fixture/skills/one", "override": "shared/skills/one"}


@pytest.mark.parametrize("definitions", [
  ['path = "shared/skills/one"', 'path = "agents/fixture/skills/one"'],
  ['path = "agents/fixture/skills/one"\noverride = "shared/skills/one"'],
  ['path = "shared/skills/one"', 'path = "agents/fixture/skills/one"\noverride = "wrong"'],
  ['path = "shared/skills/one"', 'path = "shared/skills/one"\noverride = "shared/skills/one"'],
  ['path = "shared/skills/one"', 'path = "agents/fixture/skills/one"\noverride = "shared/skills/one"',
   'path = "third/one"\noverride = "agents/fixture/skills/one"'],
  ['path = "../escape"'],
  ['path = "shared/skills/one"', 'path = "/escape"\noverride = "shared/skills/one"'],
])
def test_load_sources_rejects_implicit_wrong_repeated_overrides_and_unsafe_paths(tmp_path, definitions):
  with pytest.raises(schema.ConfigError):
    load_registries(tmp_path, ["[skills.one]\n" + text for text in definitions])


def test_load_sources_other_registry_duplicates_still_fail(tmp_path):
  with pytest.raises(schema.ConfigError):
    load_registries(tmp_path, ['[rules.one]\npath = "one.md"\n'] * 2)


class SkillAdapter(ResolutionAdapter):
  def managed_targets(self, data):
    return super().managed_targets(data) + (ManagedTarget("native/skills", Ownership.FILE, "skill-directory"),)


def skill_candidate(catalog, local, adapter, root):
  return render.render_candidate(resolve(catalog, local), adapter=adapter,
    adapter_schemas=catalog.adapter_schemas, lock_identity="fixture-lock",
    skill_root=root, skill_target_root="native/skills")


def test_selected_skills_real_loader_resolver_candidate_tracks_bytes_mode_paths(package, tmp_path, sentinel_factory):
  catalog, local, _, paths = resolution_inputs(tmp_path)
  adapter = SkillAdapter()
  # 显式重新加载来源，而不是构造平行的候选测试模型。
  override = tmp_path / "agent-skills.toml"
  override.write_text('schema_version = 1\n[skills.one]\npath = "agents/fixture/skills/one"\noverride = "shared/skills/one"\n')
  replacement = package[0] / "agents/fixture/skills/one"
  replacement.parent.mkdir(parents=True)
  package[1].rename(replacement)
  catalog = config.load_sources(config.SourceInputs((paths["registry"], override), (paths["profile"],), {
    "fixture-json": config.AdapterSources(*(paths[key] for key in ("agent", "bindings", "plugins")))}),
    adapter_schemas=catalog.adapter_schemas)
  before = sentinel_factory(tmp_path)
  first = skill_candidate(catalog, local, adapter, package[0])
  assert skill_candidate(catalog, local, adapter, package[0]) == first
  assert len(first.artifacts) == len(package[2]) + 1
  assert {a.target.path.removeprefix("native/skills/one/"): a.content for a in first.artifacts
          if a.target.path != "native.json"} == package[2]
  before.assert_unchanged()
  asset = replacement / "assets/中文/data.bin"
  asset.write_bytes(b"new asset")
  second = skill_candidate(catalog, local, adapter, package[0])
  assert second.generation != first.generation
  script = replacement / "scripts/nested/check.sh"
  script.chmod(0o600)
  third = skill_candidate(catalog, local, adapter, package[0])
  assert third.generation != second.generation
  asset.rename(asset.with_name("renamed.bin"))
  assert skill_candidate(catalog, local, adapter, package[0]).generation != third.generation
  catalog.profiles["fixture-default"]["skills"] = []
  empty = skill_candidate(catalog, local, adapter, package[0])
  assert [a.target.path for a in empty.artifacts] == ["native.json"]


@pytest.mark.parametrize("ownership,serialization", [(Ownership.RUNTIME, "skill-directory"),
  (Ownership.INITIALIZE, "skill-directory"), (Ownership.FILE, "bytes")])
def test_skill_candidate_requires_explicit_exclusive_directory_declaration(package, tmp_path, ownership, serialization):
  catalog, local, _, _ = resolution_inputs(tmp_path)

  class WrongScope(ResolutionAdapter):
    def managed_targets(self, data):
      return super().managed_targets(data) + (ManagedTarget("native/skills", ownership, serialization),)

  with pytest.raises(render.RenderError):
    skill_candidate(catalog, local, WrongScope(), package[0])
  with pytest.raises(render.RenderError):
    skill_candidate(catalog, local, ResolutionAdapter(), package[0])


def test_skill_candidate_rejects_conflicting_targets_and_scope_artifacts(package, tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)

  class Conflict(SkillAdapter):
    def managed_targets(self, data):
      return super().managed_targets(data) + (ManagedTarget("native/skills/one/ordinary.txt", Ownership.FILE, "bytes"),)

  with pytest.raises(render.RenderError):
    skill_candidate(catalog, local, Conflict(), package[0])

  class ScopeArtifact(SkillAdapter):
    def render(self, data):
      return super().render(data) + (Artifact(self.managed_targets(data)[-1], b"not a directory"),)

  with pytest.raises(render.RenderError):
    skill_candidate(catalog, local, ScopeArtifact(), package[0])


def test_repository_navigation_package_relative_links_survive_collection():
  api = skills_api()
  artifacts = api.collect_skills(REPO, {"repo-navigation": {"path": "shared/skills/repo-navigation"}}, target_root="skills")
  contents = {a.target.path.removeprefix("skills/repo-navigation/"): a.content for a in artifacts}
  frontmatter = yaml.safe_load(contents["SKILL.md"].decode().split("---", 2)[1])
  assert frontmatter["name"] == "repo-navigation" and frontmatter["description"]
  links = re.findall(r"\]\(([^)]+)\)", contents["SKILL.md"].decode())
  assert links
  for link in links:
    assert link in contents, "package-relative reference missing"
  rules = tuple({"path": "shared/rules/" + name} for name in ("chinese.md", "terminal.md", "cpp-local-search.md"))
  expected = b"\n\n".join((REPO / rule["path"]).read_bytes() for rule in rules)
  assert render.render_rules(REPO, rules, {}) == expected
