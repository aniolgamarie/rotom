"""1.3：仅校验合成证据文件，不运行上游算法、原生发现或生产安全策略。"""

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat

import pytest
import yaml


ROOT = Path(__file__).parent / "fixtures" / "native-config"
HOST = "183f08e9c6dde7e36cd2318eaee70b0da08fb35e"
TUI = "78081cebde1ee1b47a561ef57c04f128c5623476"


def read_json(name):
  return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_provenance_covers_every_fixture_without_native_success_claim():
  record = read_json("provenance.json")
  assert record["schema_version"] == 1
  assert record["validation_level"] == "fixture-integrity-only"
  assert record["native_execution"] == "not-run"
  assert record["production_policy_execution"] == "not-run"
  assert record["pins"] == {"host": HOST, "tui": TUI}
  for source in record["sources"].values():
    project = {"host": "deepseek-ai/deepseek-harness", "tui": "ccch1mneyyy/dsh-TUI"}[source["component"]]
    assert source["url"].startswith(
      f"https://github.com/{project}/blob/{record['pins'][source['component']]}/"
    )
    assert source["symbol_or_scope"]
  paths = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()}
  assert paths == set(record["files"]) | {"provenance.json"}
  assert not any(p.is_symlink() for p in ROOT.rglob("*"))
  for name, item in record["files"].items():
    assert not PurePosixPath(name).is_absolute()
    assert ".." not in PurePosixPath(name).parts
    assert item["attribution"] == "synthetic; no upstream file copied"
    assert item["native_status"] == "not-run"
    assert item["expected_behavior"]
    assert item["sources"] and set(item["sources"]) <= set(record["sources"])
    assert bool((ROOT / name).stat().st_mode & stat.S_IXUSR) == item["executable"]
    if not item["executable"]:
      assert not (ROOT / name).stat().st_mode & 0o111


def test_cordis_declared_examples_are_consistent_not_an_algorithm_test():
  data = yaml.safe_load((ROOT / "cordis-cases.yaml").read_text(encoding="utf-8"))
  base = data["base"][0]
  cases = data["cases"]
  assert set(cases) == {"lossy-config", "complete-config", "metadata-only", "omitted-id"}
  assert base["id"] == "session-query-sqlite"
  assert base["disabled"] is False
  assert base["config"]["path"] == ":memory:"
  assert base["config"]["x-rotom-fixture"]["note"] == "中文 {{example}} $() `literal`"
  for case in cases.values():
    assert case["native_status"] == "not-run"
    assert isinstance(case["patches"], list)
    assert len(case["expected"]) == 1
    assert case["expected"][0]["id"] == base["id"]
    assert case["expected"][0]["name"] == base["name"]
    assert case["expected"][0]["disabled"] is False
  lossy = cases["lossy-config"]
  assert lossy["patches"] == [{"id": base["id"], "config": {"openAt": "first-search"}}]
  assert lossy["expected"][0]["config"] == {"openAt": "first-search"}
  complete = cases["complete-config"]
  assert complete["patches"] == complete["expected"]
  assert complete["expected"][0]["config"] == {
    "path": ":memory:", "openAt": "first-search",
    "x-rotom-fixture": base["config"]["x-rotom-fixture"],
  }
  assert cases["metadata-only"]["patches"] == [{"id": base["id"], "disabled": False}]
  assert cases["metadata-only"]["expected"] == data["base"]
  assert cases["omitted-id"]["patches"] == []
  assert cases["omitted-id"]["expected"] == data["base"]


@pytest.mark.parametrize("case_id", [
  "proposed-allowed", "unsafe-scalar", "unknown-tag", "tagged-sequence",
  "untagged-carrier", "quoted-text",
])
def test_js_samples_are_only_composed_into_inert_yaml_nodes(case_id, tmp_path, sentinel_factory):
  sentinel = sentinel_factory(tmp_path)
  samples = read_json("js-cases.json")
  sample = samples["cases"][case_id]
  assert samples["policy_status"] == "proposed-not-implemented"
  assert sample["policy_execution"] == "not-run"
  assert sample["expected_policy"] == {
    "proposed-allowed": "allow-exact-node", "unsafe-scalar": "reject",
    "unknown-tag": "reject", "tagged-sequence": "reject",
    "untagged-carrier": "reject", "quoted-text": "plain-text",
  }[case_id]
  # compose 只生成语法节点，不注册 !!js constructor、不构造/求值任何载体。
  tree = yaml.compose(sample["yaml"], Loader=yaml.SafeLoader)
  row = dict((key.value, value) for key, value in tree.value[0].value)
  assert row["id"].value == "storage-json"
  config = dict((key.value, value) for key, value in row["config"].value)
  node = config["root"]
  assert node.tag == sample["node_tag"]
  assert node.id == sample["node_kind"]
  if node.id == "scalar":
    assert node.value == sample["scalar"]
  elif case_id == "tagged-sequence":
    assert node.value == []
  else:
    assert [(k.value, v.value) for k, v in node.value] == [("__jsExpr", "process.cwd()")]
  # 标准 SafeLoader 拒绝所有未知标签（包括拟允许值）；这不是生产白名单。
  if case_id in {"proposed-allowed", "unsafe-scalar", "unknown-tag", "tagged-sequence"}:
    with pytest.raises(yaml.constructor.ConstructorError):
      yaml.safe_load(sample["yaml"])
  else:
    plain = yaml.safe_load(sample["yaml"])[0]["config"]["root"]
    assert plain == ({"__jsExpr": "process.cwd()"} if case_id == "untagged-carrier" else "process.env.X")
  sentinel.assert_unchanged()


def test_settings_sample_declares_unregistered_preservation_not_schema_acceptance():
  sample = yaml.safe_load((ROOT / "settings-case.yaml").read_text(encoding="utf-8"))
  assert sample["native_status"] == "not-run"
  assert sample["operation"] == {"namespace": "agent-presets", "replace_user_section": {}}
  assert sample["before"]["agent-presets"] == {"default": "standard"}
  assert sample["expected_document"]["agent-presets"] == {}
  assert sample["before"]["rotom-fixture-unregistered"] == sample["expected_document"]["rotom-fixture-unregistered"]
  assert set(sample["before"]) == set(sample["expected_document"])
  assert sample["unknown_namespace_is_native_schema"] is False


def test_discovery_expectations_reference_active_preset_and_literal_rule():
  data = read_json("discovery.json")
  assert data["native_status"] == "not-run"
  assert data["preset"] == "standard"
  assert data["disabled_host_rows"] == ["agent-instructions", "skill-filesystem"]
  assert data["active_scope"] == "preset"
  assert data["rule_target"] == "$DSH_HOME/AGENTS.md"
  assert data["skill_target"] == "$DSH_HOME/skills/rotom-local-nav"
  assert data["rule_order"] == [
    "$DSH_HOME/AGENTS.md", "project/AGENTS.md", "project/CLAUDE.md",
    "project/AGENTS.local.md", "project/sub/AGENTS.md",
  ]
  assert data["cwd"] == "project/sub"
  assert data["project_root_marker"] == "project/.git"
  assert data["same_scope_skill_ranks"] == {
    "project/.dsh/skills": 100, "project/.agents/skills": 200,
    "customSkillDirs": 300, "$DSH_HOME/skills": 400,
    "$DSH_AGENTS_HOME/skills": 500, "bundledSkillDir": 600,
  }
  assert data["nearest_scope_wins_before_rank"] is True
  assert (ROOT / "rule.md").read_text(encoding="utf-8") == (
    "请使用中文说明；优先使用 nvim。\n"
    "普通示例 {{example}} 保持字面，不执行 `$()`。\n"
    "先定位相关目录和符号，再按需读取；不要默认建立全仓库索引。\n"
  )


def test_complete_synthetic_skill_copies_as_data_without_invocation(tmp_path, fake_subprocess):
  package = ROOT / "skill" / "rotom-local-nav"
  copy = tmp_path / "副本"
  shutil.copytree(package, copy)
  expected = {"SKILL.md", "资料/局部说明.txt", "scripts/show-note.sh"}
  assert {str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file()} == expected
  for relative in expected:
    assert (copy / relative).read_bytes() == (package / relative).read_bytes()
    assert stat.S_IMODE((copy / relative).stat().st_mode) == stat.S_IMODE((package / relative).stat().st_mode)
  text = (copy / "SKILL.md").read_text(encoding="utf-8")
  _, frontmatter, body = text.split("---", 2)
  metadata = yaml.safe_load(frontmatter)
  assert metadata["name"] == "rotom-local-nav"
  assert metadata["description"].startswith("Synthetic fixture")
  assert re.fullmatch(r"[a-z]+(?:-[a-z]+)*", metadata["name"])
  assert "资料/局部说明.txt" in body and "scripts/show-note.sh" in body
  assert "{{example}}" in (copy / "资料/局部说明.txt").read_text(encoding="utf-8")
  assert (copy / "scripts/show-note.sh").stat().st_mode & stat.S_IXUSR
  assert fake_subprocess.calls == []
