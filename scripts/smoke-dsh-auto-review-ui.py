#!/usr/bin/env python3
"""显式真实 TUI/Perry + 本地假 HTTP 模型；不进入默认 pytest。"""
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", type=Path, required=True)
  parser.add_argument("--evidence", type=Path, required=True)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；不使用真实账号")
  repo = Path(__file__).resolve().parents[1]
  spec = importlib.util.spec_from_file_location("review_experience", repo / "scripts/experience-dsh-auto-review.py")
  entry = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(entry)
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("使用新的空证据目录")
  state = {"main_calls": 0, "review_calls": 0, "requests": 0, "probe_result": None, "errors": [], "catalogs": [], "delegation_attempted": False, "delegation_denied": False}
  transcript = bytearray()
  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
      pass
    def do_POST(self):
      try:
        size = int(self.headers.get("Content-Length", "0"))
        assert 0 < size < 2 * 1024 * 1024
        body = json.loads(self.rfile.read(size))
        assert self.headers.get("Authorization") == "Bearer synthetic-ui-review"
        state["requests"] += 1
        assert state["requests"] <= 8
        tools = [item["function"] for item in body.get("tools", [])]
        state["catalogs"].append({"model": body.get("model"), "names": [item["name"] for item in tools]})
        structured = next((item for item in tools if {"decision", "reason"} <= set(item.get("parameters", {}).get("properties", {}))), None)
        if structured:
          state["review_calls"] += 1
          assert {item["name"] for item in tools} <= {"rotom_review_fact", structured["name"], "subagent"}, "REVIEW_CATALOG"
          assert {"rotom_review_fact", structured["name"]} <= {item["name"] for item in tools}, "REVIEW_CATALOG"
          state["review_schemas"] = {item["name"]: item["parameters"] for item in tools}
          if state["review_calls"] == 1:
            state["delegation_attempted"] = True
            name, arguments, call_id = "subagent", {"description": "Forbidden delegation probe", "prompt": "Read an outside file", "run_in_background": False}, "ui-review-forbidden"
          else:
            denied = [item for item in body["messages"] if item.get("role") == "tool" and item.get("tool_call_id") == "ui-review-forbidden"]
            assert len(denied) == 1 and "Experimental reviewer probe does not permit model delegation" in json.dumps(denied), "DELEGATION_NOT_DENIED"
            state["delegation_denied"] = True
            name, arguments, call_id = structured["name"], {"decision": "allow", "reason": "Deterministic memory-only fixture", "riskLevel": "low"}, "ui-review-verdict"
          delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
          finish = "tool_calls"
        elif any(item["name"] == "rotom_review_probe" for item in tools):
          state["main_calls"] += 1
          results = [message for message in body["messages"] if message.get("role") == "tool" and message.get("tool_call_id") == "ui-review-probe"]
          if results:
            assert len(results) == 1
            content = results[0]["content"]
            text = content if isinstance(content, str) else "".join(block.get("text", "") for block in content)
            state["probe_result"] = json.loads(text)
            assert state["probe_result"]["count"] == 1
            assert "1/1" in state["probe_result"]["status"]
            delta, finish = {"role": "assistant", "content": "AUTO_REVIEW_PROBE_DONE"}, "stop"
          else:
            assert state["main_calls"] == 1
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "ui-review-probe", "type": "function", "function": {"name": "rotom_review_probe", "arguments": "{}"}}]}
            finish = "tool_calls"
        else:
          delta, finish = {"role": "assistant", "content": "Review probe"}, "stop"
        packet = {"id": "chatcmpl-review-fixture", "object": "chat.completion.chunk", "created": 1, "model": body.get("model", "fixture")}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for part in ({**packet, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**packet, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}):
          self.wfile.write(("data: " + json.dumps(part) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True
      except Exception as error:
        state["errors"].append(str(error) if isinstance(error, AssertionError) and str(error) in ("REVIEW_CATALOG", "DELEGATION_NOT_DENIED") else "FIXTURE_REQUEST_FAILED")
        self.send_error(400)
  server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  report = {"kind": "native-tui-perry-simulated-http-model", "status": "FAIL", "real_accounts": "NOT RUN", "release_gate": "FAIL", "platform": sys.platform}
  child = None
  started = time.monotonic()
  try:
    with tempfile.TemporaryDirectory(prefix="rotom-review-ui-", dir="/dev/shm") as home:
      root = Path(home)
      local = root / "machine.toml"
      local.write_text('schema_version=1\n[machine]\nid="review-ui-native"\n'
        '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="http://127.0.0.1:' + str(server.server_port) + '/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
        '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-model"\ninput=["text"]\n'
        '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n'
        '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n[secrets]\nfixture="synthetic-ui-review"\n')
      local.chmod(0o600)
      directory = root / "experience"
      runtime = args.runtime.absolute()
      workspace = entry.prepare(local, directory, runtime)
      # 假 HOME 验证同一正式模板、公开 bundle 顺序与真实人机入口。
      prefs = workspace.instance / "user-home/.dsh-tui"
      prefs.mkdir(mode=0o700, parents=True, exist_ok=True)
      (prefs / "onboarding-v0.14.done").touch(mode=0o600)
      master, slave = pty.openpty()
      before = termios.tcgetattr(slave)
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
      env = {"PATH": os.environ["PATH"], "HOME": str(root / "manager-home"), "LANG": "C.UTF-8", "TERM": "xterm-256color", "TMPDIR": str(root / "tmp")}
      Path(env["HOME"]).mkdir(mode=0o700)
      Path(env["TMPDIR"]).mkdir(mode=0o700)
      argv = [sys.executable, str(repo / "scripts/experience-dsh-auto-review.py"), "--run", "--allow-host", "--runtime", str(runtime), "--directory", str(directory), "--local", str(local)]
      child = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=directory / "workspace", start_new_session=True)
      def drain(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
          if select.select([master], [], [], 0.1)[0]:
            try:
              transcript.extend(os.read(master, 65536))
            except OSError:
              return
          if child.poll() is not None:
            return
      deadline = time.monotonic() + 25
      while child.poll() is None and time.monotonic() < deadline and b"dsh-tui" not in transcript.lower():
        drain(0.2)
      assert child.poll() is None and b"dsh-tui" in transcript.lower(), "UI_BOOT"
      drain(0.5)
      os.write(master, b"\r")
      drain(0.5)
      os.write(master, "请只调用一次 rotom_review_probe，不调用文件或 Shell 工具。".encode() + b"\r")
      deadline = time.monotonic() + 30
      while child.poll() is None and time.monotonic() < deadline and state["probe_result"] is None and not state["errors"]:
        drain(0.2)
      assert state["probe_result"] is not None and state["review_calls"] == 2 and state["delegation_denied"] and not state["errors"], "PROBE_NOT_AI_REVIEWED"
      drain(0.5)
      fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 22, 70, 0, 0))
      child.send_signal(signal.SIGWINCH)
      drain(0.3)
      os.write(master, b"\x03")
      drain(0.5)
      if child.poll() is None:
        os.write(master, b"\x03")
        drain(0.8)
      assert child.wait(timeout=5) == 0, "UI_EXIT"
      assert termios.tcgetattr(slave) == before, "TERMIOS_NOT_RESTORED"
      assert b"synthetic-ui-review" not in transcript, "CREDENTIAL_LEAK"
      os.close(master)
      os.close(slave)
      entry.prepare(local, directory, runtime)
      report.update(status="PASS", repeat_prepare="PASS", terminal_restore="PASS", exit=0,
        runtime_identity=entry.runtime_info(runtime)["identity"], source_files=entry.sources(),
        candidate_digest=json.loads((directory / entry.OWNER).read_bytes())["candidate"],
        pnpm_lock_sha256=entry.digest((runtime / "pnpm-lock.yaml").read_bytes()))
  except Exception as error:
    report["error"] = "NATIVE_UI_OR_ASSERTION_FAILED"
    report["stage_code"] = str(error) if isinstance(error, AssertionError) and str(error) in ("UI_BOOT", "PROBE_NOT_AI_REVIEWED", "UI_EXIT", "TERMIOS_NOT_RESTORED") else type(error).__name__
    if child is not None and child.poll() is None:
      child.send_signal(signal.SIGINT)
      try:
        child.wait(timeout=5)
      except subprocess.TimeoutExpired:
        child.terminate()
        try:
          child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill()
          child.wait(timeout=5)
  finally:
    server.shutdown()
    server.server_close()
    report.update(driver_sha256=entry.digest(Path(__file__).read_bytes()),
      invocation=["scripts/smoke-dsh-auto-review-ui.py", "--allow-host", "--runtime", str(args.runtime.absolute()), "--evidence", str(evidence)],
      http=state, duration=round(time.monotonic() - started, 3))
    (evidence / "transcript.log").write_bytes(transcript)
    (evidence / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
  print(json.dumps({"status": report["status"], "evidence": str(evidence)}))
  return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
