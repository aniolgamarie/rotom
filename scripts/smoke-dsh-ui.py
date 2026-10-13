#!/usr/bin/env python3
"""显式 PTY + 本地模拟模型验收；普通 pytest 不启动宿主。"""

import argparse
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import uuid


class FixtureServer(ThreadingHTTPServer):
  daemon_threads = True


def fixture_handler(state, gate, key, target, content):
  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
      pass

    def do_POST(self):
      try:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 2 * 1024 * 1024:
          raise ValueError("REQUEST_SIZE")
        body = json.loads(self.rfile.read(size))
        if self.headers.get("Authorization") != "Bearer " + key or not self.path.endswith("/chat/completions"):
          raise ValueError("REQUEST_ROUTE")
        with gate:
          state["requests"] += 1
          if state["requests"] > 6:
            raise ValueError("REQUEST_LIMIT")
          messages, tools = body.get("messages", []), body.get("tools", [])
          user = "\n".join(json.dumps(item.get("content", ""), ensure_ascii=False) for item in messages if item.get("role") == "user")
          results = [item for item in messages if item.get("role") == "tool" and item.get("tool_call_id") == "ui-write-call"]
          delta, finish = {"role": "assistant", "content": "临时验收"}, "stop"
          cancel_stream = bool(tools) and "CANCEL_TASK_MARKER" in user
          if not tools:
            state["auxiliary_requests"] += 1
          elif cancel_stream:
            state["cancel_started"] = True
            delta["content"] = "CANCEL_PENDING_MARKER"
          elif results:
            if state["tool_results"] or len(results) != 1 or not target.is_file() or target.read_text() != content:
              raise ValueError("TOOL_RESULT_MISMATCH")
            state["tool_results"] = 1
            delta["content"] = "已完成 UI_DONE_MARKER"
            state["completed"] = True
          else:
            state["task_requests"] += 1
            state["paste"] = {"chinese": "中文第一行" in user, "multiline": "第二行" in user and "\\n" in user, "marker": "TASK_MARKER" in user}
            if state["write_calls"] or not all(state["paste"].values()):
              raise ValueError("TASK_PASTE_MISMATCH")
            tool = next((item["function"] for item in tools if item.get("function", {}).get("name") == "write"), None)
            schema = tool.get("parameters", {}) if tool else {}
            if (not tool or not {"file_path", "content"} <= set(schema.get("required", []))
                or any(schema.get("properties", {}).get(name, {}).get("type") != "string" for name in ("file_path", "content"))):
              raise ValueError("WRITE_SCHEMA_NOT_FOUND")
            state["write_calls"] = 1
            state["tool_name"] = tool["name"]
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "ui-write-call", "type": "function", "function": {
              "name": tool["name"], "arguments": json.dumps({"file_path": str(target), "content": content}, ensure_ascii=False)}}]}
            finish = "tool_calls"
        packet = {"id": "chatcmpl-ui-fixture", "object": "chat.completion.chunk", "created": int(time.time()), "model": body.get("model", "fixture")}
        if body.get("stream"):
          self.send_response(200)
          self.send_header("Content-Type", "text/event-stream")
          self.send_header("Cache-Control", "no-cache")
          self.send_header("Connection", "close")
          self.end_headers()
          time.sleep(0.2)
          if cancel_stream:
            value = {**packet, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
            self.wfile.write(("data: " + json.dumps(value) + "\n\n").encode())
            self.wfile.flush()
            state["cancel_chunk_sent"] = True
            # 只观察本地假服务连接关闭，证明 UI 取消了正在进行的请求。
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
              if select.select([self.connection], [], [], 0.1)[0] and not self.connection.recv(1, socket.MSG_PEEK):
                state["cancel_disconnected"] = True
                self.close_connection = True
                return
            raise ValueError("CANCEL_NOT_OBSERVED")
          for value in ({**packet, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
              {**packet, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}):
            self.wfile.write(("data: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
          self.wfile.write(b"data: [DONE]\n\n")
          self.close_connection = True
        else:
          payload = json.dumps({**packet, "object": "chat.completion", "choices": [{"index": 0, "message": delta, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}, ensure_ascii=False).encode()
          self.send_response(200)
          self.send_header("Content-Type", "application/json")
          self.send_header("Content-Length", str(len(payload)))
          self.end_headers()
          self.wfile.write(payload)
      except Exception as error:
        with gate:
          state["error"] = str(error) if isinstance(error, ValueError) and str(error) in {
            "REQUEST_SIZE", "REQUEST_ROUTE", "REQUEST_LIMIT", "TOOL_RESULT_MISMATCH", "TASK_PASTE_MISMATCH", "WRITE_SCHEMA_NOT_FOUND", "CANCEL_NOT_OBSERVED"} else "FIXTURE_HTTP_FAILED"
        self.send_response(400)
        self.send_header("Content-Length", "0")
        self.end_headers()
  return Handler


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", required=True, type=Path)
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；默认测试不启动第三方宿主")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, runtime_packages
  from agentcfg.process import launch_environment
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock, runtime = dependencies.read_lock(repo), args.runtime.absolute()
  if (runtime_packages.status(runtime, lock.identity) != "installed" or any((runtime / name).read_bytes() != value
      for name, value in (("package.json", lock.package), ("package-lock.json", lock.resolution), ("pnpm-lock.yaml", lock.installer_resolution)))):
    parser.error("运行包收据与当前完整锁不匹配")
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("使用新的空证据目录")
  cache = repo / ".cache/dsh-upgrade"
  cache.mkdir(mode=0o700, parents=True, exist_ok=True)
  result = {"kind": "native-pty-simulated-local-model", "stage": "prepare", "checks": {}, "lock_identity": lock.identity,
    "recipe": lock.metadata["recipe"], "platform": sys.platform, "color_environment": "COLORTERM=truecolor",
    "ssh": "NOT RUN", "tmux": "NOT RUN", "real_accounts": "NOT RUN"}
  outer_path = os.environ.get("PATH", "")
  transcript, child, master, slave, server = bytearray(), None, None, None, None
  with tempfile.TemporaryDirectory(prefix="rotom-dsh-ui-", dir="/dev/shm") as private, tempfile.TemporaryDirectory(prefix="ui-workspace-", dir=cache) as work:
    root, project = Path(private), Path(work)
    env = {"PATH": outer_path, "TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": "C.UTF-8"}
    for name, suffix in {"HOME": "home", "DSH_HOME": "dsh", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
        "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
      env[name] = str(root / suffix)
      ensure_private(root / suffix)
    os.environ.clear()
    os.environ.update(env)
    target, content, key = project / "ui-tool-result.txt", "中文原生工具写入\nUI_TOOL_CONTENT_MARKER\n", "synthetic-" + uuid.uuid4().hex
    state = {"requests": 0, "auxiliary_requests": 0, "task_requests": 0, "write_calls": 0, "tool_results": 0, "completed": False}
    gate = threading.Lock()
    try:
      node = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True, check=True).stdout.strip()
      if node != lock.metadata["node"]:
        raise RuntimeError("NODE_VERSION")
      server = FixtureServer(("127.0.0.1", 0), fixture_handler(state, gate, key, target, content))
      threading.Thread(target=server.serve_forever, daemon=True).start()
      machine = root / "machine.toml"
      machine.write_text('schema_version=1\n[machine]\nid="native-ui"\n[overrides.providers.fixture]\nprotocol="openai-compatible"\n'
        f'base_url="http://127.0.0.1:{server.server_port}/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-not-real"\ninput=["text"]\n'
        '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n[overrides.profiles.dsh-default.roles]\nmain="fixture"\n'
        f'[secrets]\nfixture={json.dumps(key)}\n')
      machine.chmod(0o600)
      workspace = load_workspace(machine, repository=repo)
      candidate = workspace.candidate(lock.identity)
      commands.apply_candidate(workspace, lock, candidate)
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        workspace.adapter.prepare_runtime(workspace, runtime)
      spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=project, runtime_root=runtime, instance_root=workspace.instance, lock_identity=lock.identity)
      child_env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
      master, slave = pty.openpty()
      before = termios.tcgetattr(slave)
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
      child = subprocess.Popen(spec.argv, cwd=project, env=child_env, stdin=slave, stdout=slave, stderr=slave)
      def pump():
        if select.select([master], [], [], 0.1)[0]:
          try:
            transcript.extend(os.read(master, 65536))
          except OSError:
            pass
      def wait(predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate() and child.poll() is None and time.monotonic() < deadline:
          pump()
          if state.get("error"):
            raise RuntimeError("FIXTURE_REJECTED")
        if not predicate():
          raise RuntimeError("STAGE_TIMEOUT")
      def rendered_text():
        visible = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", transcript.decode(errors="replace"))
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", visible)
      result["stage"] = "ui.welcome"
      wait(lambda: "Say something, or type / for commands" in rendered_text() and not termios.tcgetattr(slave)[3] & termios.ICANON)
      # 原生 welcome 的输入框默认获焦点；空 Enter 只关闭启动页，不发送模型请求。
      ready_deadline = time.monotonic() + 1
      while time.monotonic() < ready_deadline:
        pump()
      result["checks"]["native_welcome_rendered"] = "PASS"
      os.write(master, b"\r")
      result["stage"] = "ui.ready"
      ready_deadline = time.monotonic() + 1
      while time.monotonic() < ready_deadline:
        pump()
      if child.poll() is not None or state["requests"]:
        raise RuntimeError("WELCOME_EMPTY_SUBMIT")
      result["checks"]["welcome_empty_enter_no_model_call"] = "PASS"
      result["checks"]["native_ui_ready"] = "PASS"
      result["stage"] = "ui.paste-tool"
      os.write(master, "\x1b[200~中文第一行\n第二行 TASK_MARKER\x1b[201~".encode())
      wait(lambda: b"TASK_MARKER" in transcript, 5)
      os.write(master, b"\r")
      wait(lambda: state["write_calls"] == 1)
      result["stage"] = "ui.resize"
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 18, 40, 0, 0))
      os.kill(child.pid, signal.SIGWINCH)
      resize_start = len(transcript)
      wait(lambda: state["completed"] and target.is_file() and target.read_text() == content)
      # Ink 在窄窗逐段重绘；ANSI 光标控制和换行会拆开可见标记。
      def rendered_marker(marker="UI_DONE_MARKER"):
        return marker in re.sub(r"\s+", "", rendered_text()) and len(transcript) > resize_start
      wait(rendered_marker)
      # 只检查公开 Theme 字段在真实渲染中的色值，不调用宿主私有 resolver。
      palette = json.loads((repo / "agents/dsh/templates/theme-catppuccin.json").read_bytes())["colors"]
      def ansi_color(value):
        return ("\x1b[38;2;" + ";".join(str(int(value[index:index + 2], 16)) for index in (1, 3, 5)) + "m").encode()
      if not all(ansi_color(palette[key]) in transcript for key in ("text", "promptBorder", "success")):
        raise RuntimeError("THEME_RENDER_MISMATCH")
      result["checks"]["native_catppuccin_truecolor"] = "PASS"
      result["checks"].update(chinese_multiline_paste="PASS", narrow_resize="PASS", native_write_tool_roundtrip="PASS")
      result["stage"] = "ui.cancel-stream"
      os.write(master, b"CANCEL_TASK_MARKER\r")
      wait(lambda: state.get("cancel_started") is True)
      wait(lambda: state.get("cancel_chunk_sent") is True, 5)
      os.write(master, b"\x03")
      wait(lambda: state.get("cancel_disconnected") is True, 10)
      assert child.poll() is None and state["write_calls"] == 1 and state["tool_results"] == 1
      result["checks"]["ctrl_c_active_request_cancel"] = "PASS"
      idle_deadline = time.monotonic() + 1
      while time.monotonic() < idle_deadline:
        pump()
      result["stage"] = "ui.ctrl-c"
      os.write(master, b"\x03")
      time.sleep(0.3)
      if child.poll() is None:
        os.write(master, b"\x03")
      wait(lambda: child.poll() is not None, 10)
      after = termios.tcgetattr(slave)
      result.update(exit=child.returncode, termios_before=before[:4], termios_after=after[:4],
        complete_termios_match=before == after, geometry=[[100, 24], [40, 18]],
        file_content_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), http=dict(state), candidate_digest=candidate.generation, node=node)
      if before != after or child.returncode != 0 or state["write_calls"] != 1 or state["tool_results"] != 1:
        raise RuntimeError("EXIT_OR_TTY_RESTORE")
      result["checks"].update(ctrl_c_exit="PASS", termios_restored="PASS")
      result["overall"], result["stage"] = "PASS", "complete"
    except Exception as error:
      result.update(overall="FAIL", error="FIXTURE_REJECTED" if state.get("error") else str(error) if isinstance(error, RuntimeError)
        and str(error) in {"NODE_VERSION", "STAGE_TIMEOUT", "EXIT_OR_TTY_RESTORE", "FIXTURE_REJECTED", "WELCOME_EMPTY_SUBMIT", "THEME_RENDER_MISMATCH"} else "UI_SMOKE_FAILED", error_location=result["stage"], http=dict(state))
    finally:
      if child is not None and child.poll() is None:
        child.terminate()
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait()
      if child is not None:
        result["observed_exit"] = child.returncode
      if server:
        server.shutdown()
        server.server_close()
      for fd in (master, slave):
        if fd is not None:
          os.close(fd)
    source = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in ("scripts/smoke-dsh-ui.py", "src/agentcfg/dsh.py",
      "agents/dsh/templates/launch.mjs", "agents/dsh/packages/cursor-terminal/index.mjs", "agents/dsh/templates/theme-catppuccin.json")}
    result.update(source_files=source, source_hash=hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest())
    (evidence / "transcript.log").write_bytes(transcript)
    (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}, ensure_ascii=False))
    return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
