"""T025 Base领域资源完整传输与能力隔离；纯解析/渲染，不执行迁入脚本。"""

from pathlib import Path
import re
import stat

from agentcfg.config import LocalConfig, resolve_config
from agentcfg.render import render_candidate
from agentcfg.workspace import load_public_catalog


ROOT = Path(__file__).resolve().parents[1]


def candidate(prompts=None):
  catalog, adapters = load_public_catalog(repository=ROOT)
  overrides = {} if prompts is None else {"agent_options": {"resources": {"prompts": prompts}}}
  local = LocalConfig({"schema_version": 1, "machine": {"id": "base-domain-test"},
    "overrides": {"profiles": {"pi-base": overrides}}})
  config = resolve_config(catalog, local, profile_id="pi-base", adapter_schemas=catalog.adapter_schemas)
  rendered = render_candidate(config, adapter=adapters["pi"], adapter_schemas=catalog.adapter_schemas,
    lock_identity="synthetic-offline-resource-lock", skill_root=ROOT, skill_target_root="pi-home/skills")
  return config.data, {artifact.target.path: artifact for artifact in rendered.artifacts}


def test_base_domain_reference_is_selected_copied_and_relative_link_resolves():
  data, artifacts = candidate()
  source = ROOT / "shared/skills/cpp-database-kernel/references/database-contracts.md"
  assert source.is_file(), "Base database knowledge reference missing"
  target = "pi-home/skills/cpp-database-kernel/references/database-contracts.md"
  assert target in artifacts and artifacts[target].content == source.read_bytes()
  body = artifacts["pi-home/skills/cpp-database-kernel/SKILL.md"].content.decode()
  links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", body)
  assert "references/database-contracts.md" in links
  for link in links:
    if "://" in link or link.startswith("#"): continue
    path = Path("pi-home/skills/cpp-database-kernel") / link.split("#", 1)[0]
    assert path.as_posix() in artifacts, "relative domain resource not copied"
  assert "cpp-database-kernel" in data["profile"]["skills"]


def test_base_copies_complete_selected_packages_preserving_exec_and_private_modes():
  data, artifacts = candidate()
  for name in data["profile"]["skills"]:
    source = ROOT / "shared/skills" / name
    expected = {path.relative_to(source).as_posix(): path for path in source.rglob("*") if path.is_file()}
    copied = {path.removeprefix("pi-home/skills/" + name + "/"): artifact for path, artifact in artifacts.items()
      if path.startswith("pi-home/skills/" + name + "/")}
    assert copied.keys() == expected.keys()
    assert {"SKILL.md", "LICENSE"} <= copied.keys()
    for relative, path in expected.items():
      assert copied[relative].content == path.read_bytes()
      source_mode = stat.S_IMODE(path.stat().st_mode)
      assert copied[relative].mode == (0o700 if source_mode & 0o111 else 0o600)
      assert bool(copied[relative].mode & 0o111) == bool(source_mode & 0o111)


def test_base_default_and_explicit_ordinary_prompts_do_not_load_full_schedulers():
  data, artifacts = candidate()
  default = {path for path in artifacts if path.startswith("pi-home/prompts/")}
  assert default == {"pi-home/prompts/" + name + ".md" for name in ("implement", "plan", "review")}
  assert "model-delegate" not in data["profile"]["skills"]
  assert set(data["profile"]["plugins"]) == {"pi-todo", "loop-guard", "colorful-footer"}
  forbidden = (b"model_delegate", b"kernel_task", b"kernel-orchestrate", b"superpowers", b"openspec")
  for path, artifact in artifacts.items():
    if path.endswith(".md"): assert not any(word in artifact.content.lower() for word in forbidden)
  optional = ("commit", "debug", "docs", "explain", "perf", "pr", "refactor", "security", "test")
  for name in optional:
    _, selected = candidate(["ordinary-" + name])
    prompts = {path: artifact for path, artifact in selected.items() if path.startswith("pi-home/prompts/")}
    assert prompts.keys() == {"pi-home/prompts/" + name + ".md"}
    assert next(iter(prompts.values())).content == (ROOT / "agents/pi/prompts/ordinary" / (name + ".md")).read_bytes()
    assert not any(word in next(iter(prompts.values())).content.lower() for word in forbidden)
