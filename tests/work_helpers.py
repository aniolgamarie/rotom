"""Herdr 官方公开响应的离线替身；不启动宿主或绑定 socket。"""
from copy import deepcopy
from collections import Counter
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

FIXTURES = Path(__file__).parent / "fixtures" / "herdr-native" / "v1"


def native_responses(version="v1"):
  """v2 仅叠加已准入 wire 结果，绝不把能力哨兵当成功。"""
  if version not in ("v1", "v2"):
    raise ValueError("unknown synthetic fixture version")
  result = json.loads((FIXTURES / "responses.json").read_text())
  if version == "v2":
    root = FIXTURES.parent / "v2"
    source = json.loads((root / "source.json").read_text())
    additions = json.loads((root / "responses.json").read_text())
    for method in source["coverage"]["wire_result_methods"]:
      result[method] = additions[method]
  return result


def private_roots(tmp_path, monkeypatch):
  """只在测试临时目录建立当前用户的私有配置与状态根。"""
  root = tmp_path / "work-private"
  root.mkdir(mode=0o700)
  paths = {name: root / name for name in ("home", "config", "state", "data", "cache", "bin")}
  for path in paths.values():
    path.mkdir(mode=0o700)
    assert path.stat().st_uid == os.getuid() and stat.S_IMODE(path.stat().st_mode) == 0o700
  for name, key in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
      ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
    monkeypatch.setenv(name, str(paths[key]))
  return SimpleNamespace(root=root, **paths)


def private_file(path, content=b"synthetic private fixture\n"):
  """独占创建 0600 普通文件；不覆盖既有文件或跟随链接。"""
  descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
  with os.fdopen(descriptor, "wb") as stream:
    stream.write(content)
  assert path.stat().st_uid == os.getuid() and stat.S_IMODE(path.stat().st_mode) == 0o600
  return path


class FakeExecCalled(BaseException):
  """模拟 exec 不返回，避免测试调用者误走成功后的回退路径。"""


class FakeExec:
  def __init__(self, *executables):
    self.executables = {os.fspath(path) for path in executables}
    self.calls = []
    self.error = None

  def __call__(self, executable, argv, env=None):
    assert os.fspath(executable) in self.executables, "unprepared synthetic executable"
    assert isinstance(argv, (list, tuple)) and argv, "explicit argv required"
    self.calls.append({"executable": os.fspath(executable), "argv": list(argv),
      "cwd": Path.cwd(), "env": dict(os.environ if env is None else env)})
    if self.error is not None:
      raise self.error
    raise FakeExecCalled()


class FakeSocket:
  def __init__(self, factory):
    self.factory = factory
    self.closed = False
    self.timeouts = []

  def settimeout(self, timeout):
    self.timeouts.append(timeout)

  def connect(self, path):
    self.factory.paths.append(path)
    if self.factory.connect_error:
      raise self.factory.connect_error

  def sendall(self, data):
    self.request = json.loads(data)
    self.factory.requests.append(self.request)

  def recv(self, size):
    if hasattr(self, "read"):
      return b""
    self.read = True
    value = self.factory.responses.pop(0)
    if isinstance(value, Exception):
      raise value
    if isinstance(value, bytes):
      return value
    return json.dumps({"id": self.request["id"], **value}).encode() + b"\n"

  def close(self):
    self.closed = True


class FakeSockets:
  def __init__(self, *responses):
    self.responses = list(responses)
    self.requests = []
    self.paths = []
    self.sockets = []
    self.connect_error = None

  def __call__(self, *args):
    value = FakeSocket(self)
    self.sockets.append(value)
    return value


class FakeHerdr:
  """项目生命周期与 source 级 seq 严格递增；未带 seq 的 patch 总可接受。"""
  def __init__(self, socket_path=None, deadline=None, expected_identity=None, *, version="v1"):
    from termcfg.herdr import Deadline
    self.deadline = deadline or Deadline()
    self.identity = (7, 11)
    self.socket_path = socket_path or "/tmp/example-herdr/api.sock"
    self.data = native_responses(version)
    self.workspaces = {}
    self.panes = {}
    self.tabs = {}
    self.requests = []
    self.sequences = {}
    self.auto_ready = True
    self.auto_accept = True
    self.counter = 0
    self.call_counts = Counter()
    self.mutation_calls = []
    self.barriers = {}
    self.failures = {}

  def fail(self, method, *, when="before", occurrence=1, error=None):
    """明确区分发送前失败与副作用完成后响应丢失。"""
    assert when in ("before", "after") and occurrence > 0
    self.failures[(method, when, occurrence)] = error or RuntimeError("synthetic native failure")

  def _boundary(self, method, when, params, occurrence):
    key = (method, when, occurrence)
    if key in self.barriers:
      self.barriers[key](self, deepcopy(params))
    if key in self.failures:
      raise self.failures[key]

  def __enter__(self):
    return self

  def __exit__(self, *args):
    self.close()

  def close(self):
    pass

  def request(self, method, params=None):
    params = params or {}
    self.requests.append((method, deepcopy(params)))
    self.call_counts[method] += 1
    occurrence = self.call_counts[method]
    self._boundary(method, "before", params, occurrence)
    if method in ("worktree.open", "workspace.create", "workspace.rename", "tab.create", "tab.rename",
        "workspace.report_metadata", "pane.report_metadata", "tab.report_metadata",
        "workspace.focus", "tab.focus", "pane.focus"):
      self.mutation_calls.append((method, deepcopy(params)))
    result = self._request(method, params)
    self._boundary(method, "after", params, occurrence)
    return result

  def _ready(self, pane, params, action):
    if not self.auto_ready or "ROTOM_WORK_LAUNCH_V2" not in params.get("env", {}):
      return
    payload = json.loads(params["env"]["ROTOM_WORK_LAUNCH_V2"])
    assert payload["version"] == 2 and type(payload["version"]) is int
    assert payload["action"] == action
    assert all(isinstance(payload[key], str) and payload[key]
      for key in ("owner", "epoch", "type", "instance", "kind", "op"))
    assert payload["kind"] in ("default", "extra")
    if action == "workspace-initial":
      assert payload["kind"] == "default"
    else:
      assert payload["workspace_id"] == pane["workspace_id"]
    pane["tokens"] = {"rw2_" + key: payload[key]
      for key in ("owner", "epoch", "type", "instance", "kind", "op")}
    pane["tokens"]["rw2_phase"] = "ready"

  def _accept_v2(self, pane):
    tokens = pane.get("tokens", {})
    workspace = self.workspaces.get(pane["workspace_id"], {})
    owner = workspace.get("tokens", {})
    if (tokens.get("rw2_phase") == "ready" and tokens.get("rw2_op")
        and tokens.get("rw2_commit") == tokens["rw2_op"]
        and owner.get("rw2_owner") == tokens.get("rw2_owner")
        and owner.get("rw2_epoch") == tokens.get("rw2_epoch")
        and owner.get("rw2_model") == "structured-v1"
        and owner.get("rw2_pending") == tokens["rw2_op"]):
      tokens["rw2_phase"] = "accepted"

  def _request(self, method, params):
    assert method in self.data or method == "tab.report_metadata", "unsupported fake Herdr method: " + method
    if method == "ping":
      return deepcopy(self.data["ping"])
    if method == "workspace.create" and method in self.data:
      assert params.get("focus", False) is False
      assert "worktree" not in params and "path" not in params
      result = deepcopy(self.data[method])
      n = 1
      while f"workspace-{n}" in self.workspaces or f"tab-{n}" in self.tabs or f"pane-{n}" in self.panes:
        n += 1
      ws, tab, pane = result["workspace"], result["tab"], result["root_pane"]
      ws.update(workspace_id=f"workspace-{n}", number=n, label=params.get("label"), tokens={})
      assert "worktree" not in ws
      ws["active_tab_id"] = tab["tab_id"] = pane["tab_id"] = f"tab-{n}"
      tab["workspace_id"] = pane["workspace_id"] = ws["workspace_id"]
      pane.update(pane_id=f"pane-{n}", terminal_id=f"terminal-{n}")
      self._ready(pane, params, "workspace-initial")
      self.workspaces[ws["workspace_id"]] = ws
      self.tabs[tab["tab_id"]] = tab
      self.panes[pane["pane_id"]] = pane
      return deepcopy(result)
    if method == "workspace.rename" and method in self.data:
      target = self.workspaces[params["workspace_id"]]
      target["label"] = params["label"]
      return {"type": "workspace_info", "workspace": deepcopy(target)}
    if method == "tab.rename" and method in self.data:
      assert set(params) == {"tab_id", "label"}
      target = self.tabs[params["tab_id"]]
      target["label"] = params["label"]
      return {"type": "tab_info", "tab": deepcopy(target)}
    if method == "worktree.open":
      found = next((w for w in self.workspaces.values() if w["worktree"]["checkout_path"] == params["path"]), None)
      if found:
        result = deepcopy(self.data["worktree.open"])
        result.update(workspace=deepcopy(found), already_open=True)
        result["tab"] = deepcopy(self.tabs[found["active_tab_id"]])
        result["root_pane"] = deepcopy(next(p for p in self.panes.values() if p["workspace_id"] == found["workspace_id"]))
        return result
      result = deepcopy(self.data["worktree.open"])
      n = len(self.workspaces) + 1
      ws, tab, pane = result["workspace"], result["tab"], result["root_pane"]
      ws["workspace_id"] = tab["workspace_id"] = pane["workspace_id"] = f"workspace-{n}"
      ws["active_tab_id"] = tab["tab_id"] = pane["tab_id"] = f"tab-{n}"
      pane["pane_id"] = f"pane-{n}"
      pane["terminal_id"] = f"terminal-{n}"
      ws["worktree"]["checkout_path"] = result["worktree"]["path"] = params["path"]
      ws["worktree"]["repo_root"] = params["cwd"]
      self.workspaces[ws["workspace_id"]] = ws
      self.tabs[tab["tab_id"]] = tab
      self.panes[pane["pane_id"]] = pane
      return deepcopy(result)
    if method == "workspace.list":
      return {"type": "workspace_list", "workspaces": deepcopy(list(self.workspaces.values()))}
    if method == "worktree.list":
      result = deepcopy(self.data[method])
      if params.get("cwd"):
        result["source"].update(repo_root=params["cwd"], source_checkout_path=params["cwd"])
      result["worktrees"] = [{**deepcopy(self.data["worktree.open"]["worktree"]), "path": w["worktree"]["checkout_path"], "open_workspace_id": w["workspace_id"]} for w in self.workspaces.values()]
      if params.get("cwd") and not any(w["path"] == params["cwd"] for w in result["worktrees"]):
        result["worktrees"].append({**deepcopy(self.data["worktree.open"]["worktree"]), "path": params["cwd"]})
      return result
    if method == "pane.list":
      return {"type": "pane_list", "panes": deepcopy([p for p in self.panes.values() if not params.get("workspace_id") or p["workspace_id"] == params["workspace_id"]])}
    resource = method.split(".")[0]
    if method == "tab.create":
      result = deepcopy(self.data["tab.create"])
      self.counter += 1
      n = self.counter
      tab, pane = result["tab"], result["root_pane"]
      tab.update(tab_id=f"tab-new-{n}", workspace_id=params["workspace_id"], label=params["label"])
      pane.update(pane_id=f"pane-new-{n}", terminal_id=f"terminal-new-{n}", tab_id=tab["tab_id"], workspace_id=params["workspace_id"])
      pane["tokens"] = {}
      if self.auto_ready and "ROTOM_WORK_LAUNCH_V1" in params.get("env", {}):
        payload = json.loads(params["env"]["ROTOM_WORK_LAUNCH_V1"])
        pane["tokens"] = {"rw_project": payload["project_digest"], "rw_epoch": payload["epoch"],
          "rw_role": payload["role"], "rw_op": payload["op"], "rw_kind": payload["kind"], "rw_phase": "ready"}
      self._ready(pane, params, "tab")
      self.tabs[tab["tab_id"]], self.panes[pane["pane_id"]] = tab, pane
      return deepcopy(result)
    if method == "pane.current":
      if params["caller_pane_id"] not in self.panes:
        from termcfg.errors import TermcfgError
        raise TermcfgError(4, "synthetic_pane_not_found")
      return {"type": "pane_current", "pane": deepcopy(self.panes[params["caller_pane_id"]])}
    if resource in ("workspace", "pane", "tab"):
      store = {"workspace": self.workspaces, "pane": self.panes, "tab": self.tabs}[resource]
      target = store[params[resource + "_id"]]
      if method.endswith("report_metadata"):
        key = (resource, params[resource + "_id"], params["source"])
        seq = params.get("seq")
        if seq is None or seq > self.sequences.get(key, -1):
          if seq is not None:
            self.sequences[key] = seq
          tokens = target.setdefault("tokens", {})
          for name, value in params["tokens"].items():
            if value is None:
              tokens.pop(name, None)
            else:
              tokens[name] = value
          if resource == "pane" and self.auto_accept and tokens.get("rw_commit") == tokens.get("rw_op") and tokens.get("rw_phase") == "ready":
            tokens["rw_phase"] = "accepted"
          if resource == "pane" and self.auto_accept:
            self._accept_v2(target)
        return {"type": "ok"}
      if method.endswith((".get", ".focus")):
        return {"type": resource + "_info", resource: deepcopy(target)}
    raise AssertionError("unsupported fake Herdr method: " + method)
