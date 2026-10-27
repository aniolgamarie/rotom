"""显式授权的 Herdr headless/PTY 底层探针；不启动 Agent、不发送终端输入。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.dont_write_bytecode = True


def save(root, name, value):
  path = root / name
  path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
  path.chmod(0o600)


def shell_probe(root):
  """仅作为临时 SHELL，记录公开引导字段后等待；不读取或注入输入。"""
  from agentcfg.run_owners import current_process_identity
  info = root.stat()
  if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
    return 4
  save(root, "shell-" + uuid.uuid4().hex + ".json", {
    "identity": current_process_identity(), "cwd": os.getcwd(),
    "tty": [os.isatty(fd) for fd in (0, 1, 2)],
    "bootstrap": {name: os.environ.get(name) for name in ("HERDR_SESSION", "HERDR_PANE_ID",
      "HERDR_TAB_ID", "HERDR_TERMINAL_ID", "HERDR_WORKSPACE_ID", "HERDR_SOCKET_PATH")},
    "payload_present": any(name in os.environ for name in
      ("ROTOM_WORK_LAUNCH_V1", "ROTOM_WORK_LAUNCH_V2", "ROTOM_RESTORE_LAUNCH_V1"))})
  os.execv("/bin/sh", ["/bin/sh", "-i"])


def children(pid):
  from agentcfg.run_owners import observed_process_identity
  result = []
  try:
    values = (Path("/proc") / str(pid) / "task" / str(pid) / "children").read_text().split()
  except OSError:
    return result
  for value in values:
    identity = observed_process_identity(int(value))
    if identity is not None:
      result.append(identity)
      result.extend(children(identity["pid"]))
  return result


def stop_owned(identity):
  """只向稳定出生身份匹配的本探针进程发送信号，不使用进程组或全局清理。"""
  from agentcfg.run_owners import observed_process_identity
  if observed_process_identity(identity["pid"]) != identity:
    return "already-exited-or-changed"
  try:
    descriptor = os.pidfd_open(identity["pid"])
  except ProcessLookupError:
    return "already-exited"
  try:
    if observed_process_identity(identity["pid"]) != identity:
      return "identity-changed"
    try:
      signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    except ProcessLookupError:
      return "already-exited"
    return "term-sent"
  finally:
    os.close(descriptor)


def native_request(client, root, method, params):
  """仅本探针公开 API；错误原文只保存在私人日志，避免丢失底层能力证据。"""
  from jsonschema import Draft202012Validator
  from termcfg.herdr import PARAM_SCHEMAS, RESULT_SCHEMAS, peer_pid
  if method == "pane.read":
    # 只读能力来自同版公开 schema；生产 wrapper 有意不提供终端正文读取。
    if (set(params) != {"pane_id", "source", "lines", "strip_ansi"} or not isinstance(params["pane_id"], str)
        or params["source"] != "recent" or params["lines"] != 200 or params["strip_ansi"] is not True):
      raise ValueError("invalid private pane observation")
  else:
    Draft202012Validator(PARAM_SCHEMAS[method]).validate(params)
  request_id = uuid.uuid4().hex
  request = {"id": request_id, "method": method, "params": params}
  with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.settimeout(5)
    connection.connect(client.pinned_address)
    if peer_pid(connection) != client.expected_peer_pid:
      raise RuntimeError("owned API peer changed")
    connection.sendall(json.dumps(request).encode() + b"\n")
    data = b""
    while b"\n" not in data and len(data) <= 2 * 1024 * 1024:
      part = connection.recv(65536)
      if not part:
        break
      data += part
  reply = json.loads(data)
  save(root, method.replace(".", "-") + "-wire.json", {"request": request, "reply": reply})
  if reply.get("id") != request_id or "error" in reply:
    raise RuntimeError("owned API request rejected: " + method)
  if method == "pane.read":
    result = reply["result"]
    if result.get("type") != "pane_read" or type(result.get("read", {}).get("text")) is not str:
      raise ValueError("invalid private pane read result")
  else:
    Draft202012Validator(RESULT_SCHEMAS[method]).validate(reply["result"])
  return reply["result"]


def probe(root, binary, duration):
  from agentcfg.run_owners import observed_process_identity
  from termcfg.herdr import Deadline, HerdrClient, discover, verify_schema
  from termcfg.work_config import validate_native_config
  os.umask(0o077)
  root.mkdir(mode=0o700)
  root = root.resolve(strict=True)
  if root.stat().st_uid != os.geteuid() or stat.S_IMODE(root.stat().st_mode) != 0o700:
    raise RuntimeError("private probe root required")
  binary = Path(binary).resolve(strict=True)
  paths = {name: root / directory for name, directory in {
    "HOME": "home", "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state",
    "XDG_CACHE_HOME": "cache", "XDG_RUNTIME_DIR": "runtime", "TMPDIR": "tmp"}.items()}
  paths["XDG_CONFIG_HOME"] = paths["HOME"] / ".config"
  for path in paths.values():
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
  (root / "project").mkdir(mode=0o700)
  wrapper = root / "probe-shell"
  import shlex
  wrapper.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, "-B", str(Path(__file__).resolve()),
    "--shell-probe", str(root)]) + "\n")
  wrapper.chmod(0o700)
  audit = root / "audit"
  audit.mkdir(mode=0o700)
  # Python 公开审计接口仅观察仓库自有 shell 的 exec，不修改上游或启动行为。
  (audit / "sitecustomize.py").write_text(
    "import json, os, sys\n"
    f"_probe_root = {str(root)!r}\n"
    "def _probe_audit(event, args):\n"
    "  if event != 'os.exec' or 'termcfg.work_shell' not in sys.modules:\n"
    "    return\n"
    "  try:\n"
    "    value = {'pid': os.getpid(), 'entry': sys.argv[0],\n"
    "      'module': sys.modules['termcfg.work_shell'].__file__, 'executable': os.fsdecode(args[0])}\n"
    "    with open(os.path.join(_probe_root, 'bootstrap-audit-' + str(os.getpid()) + '.json'), 'w') as stream:\n"
    "      json.dump(value, stream)\n"
    "  except Exception:\n"
    "    pass\n"
    "sys.addaudithook(_probe_audit)\n")
  (audit / "sitecustomize.py").chmod(0o600)
  os.environ.clear()
  os.environ.update({key: str(path) for key, path in paths.items()})
  os.environ.update(PATH=str(REPO) + ":/usr/bin:/bin", SHELL=str(wrapper), LANG="C.UTF-8",
    TERM="xterm-256color", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(audit) + os.pathsep + str(REPO / "src"))
  config = paths["XDG_CONFIG_HOME"] / "herdr/config.toml"
  config.parent.mkdir(mode=0o700)
  config.write_text('[terminal]\ndefault_shell="rotom-work-shell"\nshell_mode="non_login"\n'
    '[session]\nresume_agents_on_restore=false\n[update]\nversion_check=false\nmanifest_check=false\n')
  config.chmod(0o600)
  # 私人 HOME 已独占；短的唯一名避免上游内部 Unix socket 超出 sun_path。
  session = "rp-" + uuid.uuid4().hex[:12]
  result = {"session": session, "argv": [], "cleanup": [], "shell_probe_count": 0,
    "agent_started": False, "terminal_input_bytes": 0}
  server = client = server_identity = None
  known_children = []
  def cli(arguments, name):
    argv = [str(binary), *arguments]
    completed = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
    result["argv"].append({"argv": argv, "exit_code": completed.returncode})
    for kind, content in (("stdout", completed.stdout), ("stderr", completed.stderr)):
      path = root / (name + "." + kind)
      path.write_bytes(content)
      path.chmod(0o600)
    if completed.returncode:
      raise RuntimeError("public CLI failed: " + name)
    return completed.stdout
  try:
    result["version"] = cli(["--version"], "version").decode().strip()
    cli(["--help"], "help")
    cli(["server", "--help"], "server-help")
    raw_schema = cli(["api", "schema", "--json"], "schema")
    schema = json.loads(raw_schema)
    result["protocol"] = schema["protocol"]
    result["schema_digest"] = hashlib.sha256(raw_schema).hexdigest()
    verify_schema(binary, Deadline(10), structured=True)
    validate_native_config(binary, Deadline(10))
    result["config_check"] = "passed"
    result["argv"].append({"argv": [str(binary), "--session", session, "server"], "exit_code": None})
    # 与 start_headless 相同的公开 argv/隔离参数；私人捕获两流以保留早期启动错误。
    with (root / "server.stdout").open("wb") as output, (root / "server.stderr").open("wb") as errors:
      server = subprocess.Popen([str(binary), "--session", session, "server"], stdin=subprocess.DEVNULL,
        stdout=output, stderr=errors, start_new_session=True, close_fds=True, umask=0o077, env=dict(os.environ))
    server_identity = observed_process_identity(server.pid)
    if server_identity is None:
      raise RuntimeError("owned server birth identity unavailable")
    limit = time.monotonic() + 10
    discovered = None
    while time.monotonic() < limit:
      discovered = discover(binary, session, Deadline(5))
      if discovered is not None:
        break
      if server.poll() is not None:
        raise RuntimeError("owned server exited before endpoint became ready")
      time.sleep(0.05)
    if discovered is None:
      raise RuntimeError("owned server endpoint unavailable")
    socket_path = Path(discovered["socket_path"])
    if not socket_path.is_relative_to(root):
      raise RuntimeError("server endpoint escaped private probe root")
    client = HerdrClient(socket_path, Deadline(10))
    client.expected_peer_pid = server.pid
    result["ping"] = client.request("ping", {})
    result["peer_is_created_server"] = client.peer_pid == server.pid
    result["socket_owner_matches"] = socket_path.lstat().st_uid == os.geteuid()
    result["socket_identity"] = list(client.identity)
    created = native_request(client, root, "workspace.create", {"cwd": str(root / "project"), "label": "native-probe", "focus": False, "env": {}})
    save(root, "workspace-created.json", created)
    workspace_id = created["workspace"]["workspace_id"]
    tab = native_request(client, root, "tab.create", {"workspace_id": workspace_id, "cwd": str(root / "project"),
      "label": "native-probe-tab", "focus": False})
    save(root, "tab-created.json", tab)
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
      time.sleep(0.1)
    client.deadline = Deadline(5)
    for label, pane in (("workspace", created["root_pane"]), ("tab", tab["root_pane"])):
      observed = client.request("pane.get", {"pane_id": pane["pane_id"]})
      save(root, label + "-pane.json", observed)
      result[label + "_pane_fields"] = sorted(observed["pane"])
      result[label + "_cwd_fields"] = {name: observed["pane"].get(name) for name in ("cwd", "foreground_cwd")}
    known_children = children(server.pid)
    save(root, "owned-children.json", known_children)
    result["shell_probe_count"] = len(list(root.glob("shell-*.json")))
    result["owned_descendant_count"] = len(known_children)
    result["headless_pty_observed"] = any(all(json.loads(path.read_text())["tty"]) for path in root.glob("shell-*.json"))
    shell_pids = {json.loads(path.read_text())["identity"]["pid"] for path in root.glob("shell-*.json")}
    audited = [json.loads(path.read_text()) for path in root.glob("bootstrap-audit-*.json")]
    result["rotom_work_shell_confirmed"] = bool(shell_pids) and all(any(
      item["pid"] == pid and item["entry"] == str(REPO / "rotom-work-shell")
      and item["module"] == str(REPO / "src/termcfg/work_shell.py")
      and item["executable"] == str(wrapper) for item in audited) for pid in shell_pids)
    result["status"] = "observed"
    return 0
  except Exception as error:
    result["status"] = "failed"
    result["error_type"] = type(error).__name__
    result["error"] = str(error)
    return 5
  finally:
    if client is not None:
      client.close()
    if server is not None and server_identity is not None:
      known_children.extend(children(server.pid))
      result["cleanup"].append({"identity": server_identity, "result": stop_owned(server_identity)})
      try:
        server.wait(timeout=5)
      except subprocess.TimeoutExpired:
        result["cleanup_incomplete"] = True
      result["server_exit_code"] = server.poll()
      for identity in {value["pid"]: value for value in known_children}.values():
        result["cleanup"].append({"identity": identity, "result": stop_owned(identity)})
    save(root, "result.json", result)


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
  parser.add_argument("--allow-herdr", action="store_true")
  parser.add_argument("--root", type=Path)
  parser.add_argument("--herdr", default=shutil.which("herdr"))
  parser.add_argument("--observe-seconds", type=float, default=3)
  parser.add_argument("--shell-probe", type=Path, help=argparse.SUPPRESS)
  args = parser.parse_args(argv)
  if args.shell_probe is not None:
    return shell_probe(args.shell_probe)
  if (not args.allow_herdr or args.root is None or not args.root.is_absolute()
      or args.root.exists() or not args.herdr or not 0 < args.observe_seconds <= 30):
    parser.error("explicit --allow-herdr, unused absolute --root and installed --herdr required")
  return probe(args.root, args.herdr, args.observe_seconds)


if __name__ == "__main__":
  raise SystemExit(main())
