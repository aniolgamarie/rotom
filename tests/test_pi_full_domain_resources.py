"""现代Full调度知识随能力来源加载；不运行SDK、脚本或发送模型请求。"""
import json
from pathlib import Path
import re
import yaml
from agentcfg.model_delegate_actions import capture_delegate_action

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
  "model-delegate-modern": ("managed-delegation", "unified-delegate"),
  "task-keeper-modern": ("managed-workflow", "task-workflow"),
}


def test_modern_scheduler_skills_are_owned_full_only_package_resources():
  declaration = json.loads((ROOT / "agents/pi/dependencies-modern.json").read_text())
  bindings = declaration["capability_bindings"]
  for source, (name, capability) in PACKAGES.items():
    path = "skills/" + name
    package_root = ROOT / "agents/pi/packages" / source
    package = json.loads((package_root / "package.json").read_text())
    assert package["pi"]["skills"] == ["./" + path]
    assert declaration["sources"][source]["resources"]["skills"] == [path]
    assert bindings["catalog"]["resource_profiles"][source] == ["pi-full"]
    assert bindings["catalog"]["resource_profiles"][source + "-skill"] == ["pi-full"]
    owners = [p for p in bindings["providers"].values() if p["source_id"] == source]
    assert len(owners) == 1 and owners[0]["capability_id"] == capability
    assert source in owners[0]["resource_ids"]
    assert source + "-skill" in owners[0]["resource_ids"]
    assert source not in declaration["profiles"]["pi-base"]["source_ids"]
    skill = package_root / path / "SKILL.md"
    frontmatter = yaml.safe_load(skill.read_text().split("---", 2)[1])
    assert frontmatter["name"] == name and frontmatter["description"]
    # 自包含现代知识不引入历史脚本或复制另一套领域参考。
    assert not list(skill.parent.glob("scripts/*"))
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", skill.read_text()):
      if "://" not in target: assert (skill.parent / target).is_file()


def test_delegate_skill_examples_use_real_closed_schema3_capture():
  text = (ROOT / "agents/pi/packages/model-delegate-modern/skills/managed-delegation/SKILL.md").read_text()
  examples = [json.loads(raw) for raw in re.findall(r"```json\n(.*?)\n```", text, re.S)]
  assert {value["action"] for value in examples} == {"submit", "message", "continue", "cancel"}
  for value in examples:
    captured = capture_delegate_action(value)
    assert captured["action"] == value["action"]
    assert not {"budget", "source_ref", "origin", "role"} & value.keys()
  assert examples[0]["mode"] in {"review", "investigate"}
  assert examples[0].get("allow_workspace_write", False) is False


def test_workflow_skill_documents_only_the_actual_modern_actions():
  text = (ROOT / "agents/pi/packages/task-keeper-modern/skills/managed-workflow/SKILL.md").read_text()
  examples = [json.loads(raw) for raw in re.findall(r"```json\n(.*?)\n```", text, re.S)]
  assert examples == [
    {"action": "submit", "goal": "检查项目的恢复路径并报告证据，不修改业务文件。"},
    {"action": "status", "job_id": "actual-job-id"},
    {"action": "cancel", "job_id": "actual-job-id"},
  ]
  assert not any(word in text for word in ("kernel-orchestrate", "model_role", '"action":"fix"', '"action":"resume"'))


def test_real_full_render_keeps_domain_packages_identical_and_optional_scheduling_closed():
  from agentcfg.config import LocalConfig, resolve_config
  from agentcfg.render import render_candidate
  from agentcfg.workspace import load_public_catalog
  from test_pi_base_domain_resources import candidate
  catalog, adapters = load_public_catalog(repository=ROOT)
  config = resolve_config(catalog, LocalConfig({"schema_version": 1, "machine": {"id": "full-domain-test"}}),
    profile_id="pi-full", adapter_schemas=catalog.adapter_schemas)
  rendered = render_candidate(config, adapter=adapters["pi"], adapter_schemas=catalog.adapter_schemas,
    lock_identity="synthetic-offline-resource-lock", skill_root=ROOT, skill_target_root="pi-home/skills")
  artifacts = {row.target.path: row for row in rendered.artifacts}
  _, base = candidate()
  domain = lambda rows: {path: (row.content, row.mode) for path, row in rows.items() if path.startswith("pi-home/skills/")}
  assert domain(artifacts) == domain(base)
  manifest = json.loads(artifacts["pi-home/agentcfg-manifest.json"].content)
  assert {"model-delegate", "task-keeper"} <= set(manifest["plugins"])
  assert manifest["options"]["model_delegate"]["enabled"] is False
  assert manifest["options"]["task_keeper"]["enabled"] is False
  # 包内调度Skill由installed能力选择，不加入共享领域资源或Base配置。
  assert not any("managed-delegation" in path or "managed-workflow" in path for path in artifacts)
