import pytest
from agentcfg.pi_readseek_selection import decode_git_paths, git_queries, requested_categories, selection_manifest
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def test_selection_preserves_original_defaults_and_explicit_category_combinations():
  assert requested_categories({}) == ["cached", "others"]
  assert requested_categories({"cached": True, "ignored": True}) == ["cached", "ignored"]
  assert requested_categories({"ignored": True}) == ["ignored"]
  assert git_queries("/fixture with spaces", {"cached": True}) == {
    "cached": ["-C", "/fixture with spaces", "ls-files", "-z", "--cached"]}
  with pytest.raises(ConfigError): requested_categories({"cached": 1})


def test_git_paths_are_nul_delimited_and_unrepresentable_names_fail_explicitly():
  assert decode_git_paths(b"target/tracked\0space name\0target/tracked\0") == ["space name", "target/tracked"]
  for value in (b"missing terminator", b"../outside\0", b".git/config\0", b"/absolute\0", b"\xff\0", b"line\nbreak\0"):
    with pytest.raises((ConfigError, Conflict)): decode_git_paths(value)


def test_rg_selection_argv_excludes_git_metadata_at_the_source(tmp_path):
  """rg --files --hidden 会列出.git；worker绝不能接收Git元数据，必须源头排除（decode拒绝是纵深防线）。"""
  from types import SimpleNamespace
  from agentcfg.pi_readseek_select import selection_jobs
  project = tmp_path / "project"; (project / ".git").mkdir(parents=True)
  binding = {"executable": "/usr/bin/rg", "args": [], "version": "fixture", "project_root": "project",
    "read_roots": ["project"], "write_roots": [], "timeout_seconds": 30}
  manifest = {"options": {"readseek": {"rg_tool_ref": "rg"},
      "paths": {"roots": {"project": {"path": str(project), "purpose": "project"}}},
      "external_tools": {"rg": binding}, "permissions": {"denied_roots": []}},
    "permission_policy": {"rules": [{"id": "fixture-rg", "kind": "command", "effect": "allow",
      "tool_ids": ["bash"], "operations": ["execute"], "command_ref": "tool:rg"}]}}
  workspaces = SimpleNamespace(identify=lambda _project: {"worktree_path": str(project), "git_dir_path": str(project / ".git")})
  host = SimpleNamespace(manifest=lambda: manifest, config={"protected_roots": []}, store=SimpleNamespace(workspaces=workspaces))
  pending = {"project": str(project), "path": str(project), "cwd": str(project), "params": {}, "tool": "readSeek_grep",
    "ticket": {"timeout_seconds": 300, "write": False}}
  jobs = selection_jobs(SimpleNamespace(host=host), pending)
  assert len(jobs) == 1 and jobs[0]["category"] == "rg"
  argv = jobs[0]["check"]["argv"]
  prefix = argv[1:argv.index("--")]
  assert "!.git" in prefix and "!**/.git/**" in prefix and "!.readseek" in prefix


def test_native_shim_never_adds_files_removed_by_file_policy():
  snapshot = {"snapshot_root": "/snapshot", "snapshot_digest": "a" * 64, "entries": [{"path": "target/tracked"}]}
  value = selection_manifest(snapshot, {"cached": ["target/tracked", "denied"], "others": []})
  assert value["categories"] == {"cached": ["target/tracked"], "others": []}
  with pytest.raises(Conflict, match="EXPANDED"): selection_manifest(snapshot, {"cached": []})
