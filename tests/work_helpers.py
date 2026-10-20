"""Herdr 官方公开响应的离线替身；不启动宿主或绑定 socket。"""
from copy import deepcopy
import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "herdr-native" / "v1"


def native_responses():
  return json.loads((FIXTURES / "responses.json").read_text())


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
  def __init__(self, socket_path=None, deadline=None, expected_identity=None):
    from termcfg.herdr import Deadline
    self.deadline = deadline or Deadline()
    self.identity = (7, 11)
    self.socket_path = socket_path or "/tmp/example-herdr/api.sock"
    self.data = native_responses()
    self.workspaces = {}
    self.panes = {}
    self.tabs = {}
    self.requests = []
    self.sequences = {}
    self.auto_ready = True
    self.auto_accept = True
    self.counter = 0

  def __enter__(self):
    return self

  def __exit__(self, *args):
    self.close()

  def close(self):
    pass

  def request(self, method, params=None):
    params = params or {}
    self.requests.append((method, deepcopy(params)))
    if method == "ping":
      return deepcopy(self.data["ping"])
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
        return {"type": "ok"}
      if method.endswith((".get", ".focus")):
        return {"type": resource + "_info", resource: deepcopy(target)}
    raise AssertionError("unsupported fake Herdr method: " + method)
