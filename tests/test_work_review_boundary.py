"""审查导出是人工交接材料，work不能读取/广播/删除它。"""

from pathlib import Path

from termcfg.herdr import Deadline
from termcfg.work import enter_project, open_role
from termcfg.work_config import WorkSettings
from work_helpers import FakeHerdr


def test_editor_and_agent_open_preserve_all_review_exports(tmp_path, monkeypatch, sentinel_factory):
  review = tmp_path / "avalon-state"
  review.mkdir()
  for name in ("review.json", "review.md", "prompt.md", "checksums.json", "unselected-private.txt"):
    (review / name).write_text("synthetic selected or unselected review material\n")
  sentinel = sentinel_factory(review)
  real_open, real_iterdir = Path.open, Path.iterdir
  def guarded_open(path, *a, **k):
    if path == review or review in path.parents:
      raise AssertionError("work read review material")
    return real_open(path, *a, **k)
  def guarded_iterdir(path):
    if path == review or review in path.parents:
      raise AssertionError("work scanned review material")
    return real_iterdir(path)
  api = FakeHerdr(deadline=Deadline())
  ws = enter_project(api, tmp_path)
  caller = next(iter(api.panes))
  settings = WorkSettings(tmp_path / "local", "herdr", "main")
  # 替换明确工具准备点，不开放任何实际宿主执行入口。
  monkeypatch.setattr("termcfg.work.prepare_tool", lambda *a: ["/synthetic/tool"])
  with monkeypatch.context() as guard:
    guard.setattr(Path, "open", guarded_open)
    guard.setattr(Path, "iterdir", guarded_iterdir)
    for role in ("edit", "pi", "dsh", "codex"):
      pane = open_role(api, settings, role, caller_id=caller)
      assert pane["workspace_id"] == ws["workspace_id"]
  sentinel.assert_unchanged()
  requests = str(api.requests)
  assert "synthetic selected" not in requests
  assert "unselected-private" not in requests
  assert not any("send" in name or name == "agent.start" for name, _ in api.requests)
