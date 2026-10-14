#!/usr/bin/env python3
"""显式真实 Codex device OAuth 故障及重试验收；无账号，授权 URI 与终端输出不落盘。"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import socket
import socketserver
import ssl
import threading
import struct
import subprocess
import sys
import tempfile
import termios
import time
import uuid


class DeviceProxy:
  """仅测试的封闭 CONNECT/TLS fixture；不转发、不保存请求或凭据材料。"""

  REQUEST_BUDGET = 30
  CONNECT_BUDGET = 40

  def __init__(self, root):
    self.case = 0
    self.counts = {"connect": 0, "rejected_connect": 0, "requests": 0,
      "faults": 0, "unexpected": 0, "outbound_connections": 0,
      **{"usercode_case" + str(i): 0 for i in range(1, 5)},
      **{"poll_case" + str(i): 0 for i in range(1, 5)}}
    self.lock = threading.Lock()
    self.certificate = root / "fixture-ca.pem"
    key = root / "fixture-ca-key.pem"
    # 此自签 CA 仅由测试子进程通过 NODE_EXTRA_CA_CERTS 信任。
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
      "-subj", "/CN=auth.openai.com", "-addext", "subjectAltName=DNS:auth.openai.com",
      "-keyout", str(key), "-out", str(self.certificate)], check=True,
      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600); self.certificate.chmod(0o600)
    self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    self.tls.load_cert_chain(self.certificate, key)
    owner = self
    class Handler(socketserver.BaseRequestHandler):
      def handle(self):
        owner.handle(self.request)
    self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    self.server.daemon_threads = True
    self.url = "http://127.0.0.1:" + str(self.server.server_address[1])

  def start(self):
    self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    self.thread.start()

  def snapshot(self):
    with self.lock:
      return dict(self.counts)

  def close(self):
    self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)

  def handle(self, connection):
    connection.settimeout(10)
    try:
      stream = connection.makefile("rb")
      line = stream.readline(4096)
      # CONNECT 请求不会发送到真实上游；其他域名统一拒绝。
      with self.lock:
        self.counts["connect"] += 1
        accepted = line == b"CONNECT auth.openai.com:443 HTTP/1.1\r\n" and self.counts["connect"] <= self.CONNECT_BUDGET
        if not accepted:
          self.counts["rejected_connect"] += 1
      if not accepted:
        connection.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        return
      for _ in range(100):
        if stream.readline(8192) == b"\r\n":
          break
      else:
        raise ValueError()
      stream.close()
      connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
      with self.tls.wrap_socket(connection, server_side=True) as secured:
        request = secured.makefile("rb")
        method, target, version = request.readline(4096).decode("ascii").strip().split(" ")
        headers = {}
        for _ in range(100):
          line = request.readline(8192)
          if line == b"\r\n":
            break
          name, value = line.decode("ascii").split(":", 1)
          headers[name.lower()] = value.strip()
        else:
          raise ValueError()
        length = int(headers.get("content-length", "0"))
        if not 0 < length <= 4096 or headers.get("content-type") != "application/json" or method != "POST":
          raise ValueError()
        body = json.loads(request.read(length))
        with self.lock:
          self.counts["requests"] += 1
          if self.counts["requests"] > self.REQUEST_BUDGET or self.case not in range(1, 5):
            raise ValueError()
          case = self.case
          if target == "/api/accounts/deviceauth/usercode" and body == {"client_id": "app_EMoamEEZ73f0CkXaXp7hrann"}:
            self.counts["usercode_case" + str(case)] += 1
            fault = case == 1
            status = "200 OK"
            response = {"device_auth_id": "fixture-device-id", "user_code": "FIXTURE-DEVICE", "interval": 1}
          elif target == "/api/accounts/deviceauth/token" and body == {"device_auth_id": "fixture-device-id", "user_code": "FIXTURE-DEVICE"}:
            self.counts["poll_case" + str(case)] += 1
            fault = case == 3
            status = "403 Forbidden"
            response = {}
          else:
            raise ValueError()
          if fault:
            self.counts["faults"] += 1
        if fault:
          # 两个明确故障点：发码和轮询；不返回任何 token。
          secured.shutdown(socket.SHUT_RDWR)
          return
        encoded = json.dumps(response).encode()
        secured.sendall(("HTTP/1.1 " + status + "\r\nContent-Type: application/json\r\nContent-Length: "
          + str(len(encoded)) + "\r\nConnection: close\r\n\r\n").encode() + encoded)
    except (OSError, ValueError, UnicodeError):
      with self.lock:
        self.counts["unexpected"] += 1


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args(argv)
  if not args.allow_host:
    parser.error("需要 --allow-host；默认 pytest 不启动第三方宿主")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, runtime_packages
  from agentcfg.process import launch_environment
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock, runtime = dependencies.read_lock(repo), args.runtime.absolute()
  if (runtime_packages.status(runtime, lock.identity) != "installed" or any(((runtime / name).read_bytes() if (runtime / name).exists() else b"") != body
      for name, body in (("package.json", lock.package), ("pnpm-lock.yaml", lock.installer_resolution)))):
    parser.error("运行包收据与当前完整锁不匹配")
  evidence = args.evidence.absolute(); evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("请使用新的空证据目录")
  cache = Path("/dev/shm")
  outer_path = os.environ.get("PATH", "")
  result = {"kind": "native-pty-auth-real-codex-device-retry", "stage": "prepare", "lock_identity": lock.identity,
    "recipe": lock.metadata["recipe"], "platform": sys.platform, "model_calls": 0,
    "actual_account": "NOT RUN", "actual_clipboard": "NOT RUN", "actual_browser": "NOT RUN"}
  transcript, child, master, slave = bytearray(), None, None, None
  with tempfile.TemporaryDirectory(prefix="rotom-codex-device-", dir="/dev/shm") as private, tempfile.TemporaryDirectory(prefix="auth-panel-workspace-", dir=cache) as work:
    root, project = Path(private), Path(work)
    env = {"PATH": outer_path, "TERM": "xterm-256color", "LANG": "C.UTF-8"}
    for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[name] = str(root / suffix); ensure_private(root / suffix)
    fake_bin = root / "fake-bin"; ensure_private(fake_bin)
    for name in ("xdg-open", "open", "wl-copy", "xclip", "xsel", "pbcopy"):
      helper = fake_bin / name
      helper.write_text("#!/bin/sh\nexit 0\n"); helper.chmod(0o700)
    env["PATH"] = str(fake_bin) + ":" + outer_path
    os.environ.clear(); os.environ.update(env)
    native = root / "native-result.json"; ready = root / "ui-ready"; nonce = uuid.uuid4().hex
    def read():
      try:
        return json.loads(native.read_bytes())
      except (FileNotFoundError, ValueError):
        return {}
    try:
      proxy = DeviceProxy(root)
      proxy.start()
      node = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
      if node != lock.metadata["node"]:
        raise RuntimeError("NODE_VERSION")
      machine = root / "machine.toml"
      machine.write_text('schema_version=1\n[machine]\nid="native-auth-panel"\n'
        '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:9/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
        '[overrides.profiles.dsh-default]\nproviders=["fixture","codex"]\nmodels=["fixture"]\n'
        '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n[overrides.profiles.dsh-default.agent_options]\nshow_welcome=false\n')
      machine.chmod(0o600)
      workspace = load_workspace(machine, repository=repo); candidate = workspace.candidate(lock.identity)
      commands.apply_candidate(workspace, lock, candidate)
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        workspace.adapter.prepare_runtime(workspace, runtime)
      spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=project, runtime_root=runtime,
        instance_root=workspace.instance, lock_identity=lock.identity)
      child_env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
      child_env.update(AGENTCFG_AUTH_PANEL_ROOT=str(root), AGENTCFG_AUTH_PANEL_RESULT=str(native), AGENTCFG_AUTH_PANEL_NONCE=nonce,
        AGENTCFG_AUTH_PANEL_READY=str(ready),
        AGENTCFG_AUTH_PANEL_PATCH=str(workspace.instance / "dsh-home/agentcfg.patch.yml"),
        AGENTCFG_AUTH_PANEL_LAUNCHER=str(workspace.instance / "launch.mjs"))
      child_env.update(HTTPS_PROXY=proxy.url, HTTP_PROXY=proxy.url, ALL_PROXY=proxy.url, NO_PROXY="",
        NODE_EXTRA_CA_CERTS=str(proxy.certificate))
      argv = ["node", "--use-env-proxy", str(repo / "scripts/smoke-dsh-codex-device.mjs"), str(runtime)]
      master, slave = pty.openpty(); before = termios.tcgetattr(slave)
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
      child = subprocess.Popen(argv, cwd=project, env=child_env, stdin=slave, stdout=slave, stderr=slave)
      def pump():
        if select.select([master], [], [], 0.1)[0]:
          try:
            transcript.extend(os.read(master, 65536))
          except OSError:
            pass
      def text():
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)", "", transcript.decode(errors="replace"))
      def visible(label):
        # 原生终端用 CSI 前移代替部分空格；比较文字而非控制序列的空格编码。
        return "".join(label.split()) in "".join(text().split())
      case_deadline = None
      def wait(predicate, seconds=30):
        deadline = min(time.monotonic() + seconds, case_deadline or float("inf"))
        while not predicate() and child.poll() is None and time.monotonic() < deadline:
          pump()
          if read().get("error") or proxy.snapshot()["unexpected"]:
            raise RuntimeError("NATIVE_CASE_FAILED")
        if not predicate():
          raise RuntimeError("STAGE_TIMEOUT")
      result["stage"] = "pty.host-ready"
      wait(lambda: read().get("stage") == "host.agent_ready" and "fixture-not-real" in text()
        and not termios.tcgetattr(slave)[3] & termios.ICANON)
      ready.write_text("ready\n")
      result["cases"] = []
      for case in range(1, 5):
        proxy.case = case
        transcript.clear()
        result["stage"] = "pty.case" + str(case) + ".select"
        case_started = time.monotonic()
        case_deadline = case_started + 60
        os.write(master, b"/auth login openai-codex\r")
        wait(lambda: visible("Device code login (headless)") and visible("Select OpenAI Codex login method:"))
        selection_idle = 0
        if case in (1, 2):
          # 初次与失败后重开都先停在方法选择页；回答之前不应发起 OAuth 请求。
          before_selection = proxy.snapshot()["requests"]
          deadline = time.monotonic() + 5
          while time.monotonic() < deadline:
            pump()
            if child.poll() is not None or read().get("error") or proxy.snapshot()["requests"] != before_selection:
              raise RuntimeError("IDLE_PANEL_ABORTED")
          selection_idle = 5
        os.write(master, b"\x1b[B")
        time.sleep(0.15)
        transcript.clear()
        os.write(master, b"\r")
        row = {"case": case, "native_method_panel": True,
          "method_selection_idle_seconds": selection_idle, "oauth_before_selection": 0}
        if case in (1, 3):
          result["stage"] = "pty.case" + str(case) + ".fetch-failure"
          wait(lambda: visible("dsh-auth:") and visible("fetch failed")
            and proxy.snapshot()["faults"] == (1 if case == 1 else 2))
          row["fetch_failed_visible"] = True
        else:
          result["stage"] = "pty.case" + str(case) + ".device-wait"
          wait(lambda: visible("FIXTURE-DEVICE") and visible("Copy code")
            and visible("auth.openai.com/codex/device") and visible("Cancel")
            and proxy.counts["poll_case" + str(case)] >= 1)
          deadline = time.monotonic() + 5
          while time.monotonic() < deadline:
            pump()
            # 轨迹重绘会包含前一次失败文字；以本次轮询持续和宿主存活判断空闲。
            if child.poll() is not None or read().get("error") or proxy.snapshot()["unexpected"]:
              raise RuntimeError("IDLE_PANEL_ABORTED")
          if proxy.snapshot()["poll_case" + str(case)] < 2:
            raise RuntimeError("IDLE_PANEL_ABORTED")
          row.update(device_panel=True, idle_seconds=5)
          transcript.clear()
          os.write(master, b"\x1b[B"); time.sleep(0.15)
          os.write(master, b"\x1b[B"); time.sleep(0.15)
          os.write(master, b"\r")
          wait(lambda: visible("dsh-auth:") and (visible("cancel") or visible("ASK_CANCELLED")))
          # 取消后至少覆盖两个轮询间隔，确认没有遗留的后台登录轮询。
          polls_after_cancel = proxy.snapshot()["poll_case" + str(case)]
          deadline = time.monotonic() + 2.2
          while time.monotonic() < deadline:
            pump()
          if proxy.snapshot()["poll_case" + str(case)] != polls_after_cancel:
            raise RuntimeError("IDLE_PANEL_ABORTED")
          row["cancelled"] = True
          row["polling_stopped"] = True
        row["seconds"] = round(time.monotonic() - case_started, 3)
        if row["seconds"] > 60:
          raise RuntimeError("STAGE_TIMEOUT")
        result["cases"].append(row)
      case_deadline = None
      result["proxy"] = proxy.snapshot()
      if (result["proxy"]["faults"] != 2 or result["proxy"]["unexpected"]
          or any(result["proxy"]["usercode_case" + str(i)] != 1 for i in range(1, 5))
          or result["proxy"]["poll_case1"] or result["proxy"]["poll_case3"] != 1):
        raise RuntimeError("PROXY_FAILED")
      ready.write_text("done\n")
      result["stage"] = "pty.exit"
      wait(lambda: child.poll() is not None, 15)
      while select.select([master], [], [], 0)[0]:
        try:
          transcript.extend(os.read(master, 65536))
        except OSError:
          break
      after = termios.tcgetattr(slave); observed = read()
      result.update(native=observed, exit=child.returncode, termios_before=before[:4], termios_after=after[:4], complete_termios_match=before == after,
        nonce_verified=observed.get("nonce") == nonce, geometry=[100, 24], node=node, candidate_digest=candidate.generation,
        argv=["node", "--use-env-proxy", "scripts/smoke-dsh-codex-device.mjs", str(runtime)])
      if (child.returncode != 0 or before != after or observed.get("nonce") != nonce or observed.get("error")
          or not observed.get("native_complete") or observed.get("model_calls") != 0
          or observed.get("remote_http_requests") != 0 or observed.get("signed_in")
          or observed.get("credential_file_created")):
        raise RuntimeError("NATIVE_RESULT_MISMATCH")
      result.update(overall="PASS", stage="complete", login_success_count=0, credential_write_count=0,
        checks={"real_auth_command": "PASS", "real_device_flow": "PASS", "same_session_retry": "PASS", "idle_five_seconds": "PASS",
          "cancel": "PASS", "no_credential": "PASS", "termios_restore": "PASS"})
    except Exception as error:
      result.update(overall="FAIL", error=str(error) if isinstance(error, RuntimeError) and str(error) in {
        "NODE_VERSION", "NATIVE_CASE_FAILED", "STAGE_TIMEOUT", "NATIVE_RESULT_MISMATCH", "IDLE_PANEL_ABORTED", "PROXY_FAILED"} else "AUTH_PANEL_DRIVER_FAILED",
        error_location=result["stage"], native=read())
    finally:
      if child is not None and child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill(); child.wait()
      if child is not None:
        result["observed_exit"] = child.returncode
      if slave is not None:
        result["termios_restored_after_cleanup"] = before == termios.tcgetattr(slave)
      if "proxy" in locals():
        proxy.close()
        result["proxy"] = proxy.snapshot()
      for fd in (master, slave):
        if fd is not None:
          os.close(fd)
    names = ("scripts/smoke-dsh-codex-device.py", "scripts/smoke-dsh-codex-device.mjs", "src/agentcfg/dsh.py",
      "agents/dsh/templates/launch.mjs", "agents/dsh/packages/cursor-terminal/index.mjs", "agents/dsh/templates/theme-catppuccin.json")
    source = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in names}
    result.update(source_files=source, source_hash=hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest())
    result["fixture_limits"] = {"oauth_requests": DeviceProxy.REQUEST_BUDGET,
      "connect_requests": DeviceProxy.CONNECT_BUDGET, "faults": 2, "case_seconds": 60}
    # 设备码、链接与终端原文只用于内存检查，随后销毁。
    transcript.clear()
    result["terminal_transcript"] = "DISCARDED"
    with (evidence / "result.json").open("x", encoding="utf-8") as record:
      os.fchmod(record.fileno(), 0o600)
      record.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
