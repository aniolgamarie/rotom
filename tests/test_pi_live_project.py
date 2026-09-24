"""实网夹具的创建和检查不启动模型或真实 Git。"""
import json
import pytest
from agentcfg.pi_live_project import prepare_project, inspect_project
from agentcfg.storage import Conflict


def make_project(path):
  calls = []
  def git(argv, **kwargs):
    calls.append(argv)
    assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null"
    if "init" in argv: (path / ".git").mkdir(mode=0o700)
  result = prepare_project(path, run=git, git="/fixture/git")
  assert result["model_calls"] == 0 and len(calls) == 3
  return inspect_project(path)


def test_prepare_requires_new_path_and_preserves_existing_project(tmp_path):
  path = tmp_path / "project"
  marker = make_project(path)
  assert len(marker["nonce"]) == 64
  with pytest.raises(Conflict): prepare_project(path, run=lambda *a, **k: pytest.fail("must not run"))
  assert inspect_project(path) == marker


@pytest.mark.parametrize("change", ["source", "extra", "nonce", "marker-symlink"])
def test_probe_rejects_modified_inputs_or_foreign_project(tmp_path, change):
  path = tmp_path / "project"; make_project(path)
  if change == "source": (path / "code.txt").write_text("foreign content")
  elif change == "extra": (path / "foreign.txt").write_text("business data")
  elif change == "nonce":
    marker = json.loads((path / "agentcfg-live-project.json").read_text()); marker["nonce"] = "bad"
    (path / "agentcfg-live-project.json").write_text(json.dumps(marker))
  else:
    (path / "agentcfg-live-project.json").unlink(); (path / "agentcfg-live-project.json").symlink_to(tmp_path / "foreign")
  with pytest.raises((Conflict, OSError, ValueError)): inspect_project(path)
