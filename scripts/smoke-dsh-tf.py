#!/usr/bin/env python3
"""显式真实 DSH + 本机虚构 TF 服务；不读取本机密钥或连接实际网关。"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pty
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlsplit


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-host", action="store_true")
  parser.add_argument("--runtime", type=Path, required=True)
  parser.add_argument("--evidence", type=Path, required=True)
  args = parser.parse_args()
  if not args.allow_host:
    parser.error("需要 --allow-host；不属于默认 pytest")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies
  from agentcfg.process import launch_environment
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  lock = dependencies.read_lock(repo)
  evidence = args.evidence.absolute()
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  if (evidence / "result.json").exists():
    parser.error("使用新的证据目录")
  requests = []
  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
      pass
    def do_POST(self):
      body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
      anthropic = urlsplit(self.path).path.endswith("/messages")
      authenticated = self.headers.get("x-api-key" if anthropic else "Authorization") == (
        "synthetic-tf" if anthropic else "Bearer synthetic-tf")
      requests.append({"path": self.path, "model": body.get("model"), "authenticated": authenticated})
      if not authenticated or len(requests) > 3:
        self.send_error(400)
        return
      self.send_response(200)
      self.send_header("Content-Type", "text/event-stream")
      self.send_header("Connection", "close")
      self.end_headers()
      if anthropic:
        events = [
          {"type": "message_start", "message": {"id": "fixture", "type": "message", "role": "assistant", "model": body["model"], "content": [], "usage": {"input_tokens": 1, "output_tokens": 0}}},
          {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
          {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "TF_FIXTURE_OK"}},
          {"type": "content_block_stop", "index": 0},
          {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
          {"type": "message_stop"}]
        payload = "".join("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n" for event in events)
      else:
        events = [{"id": "fixture", "object": "chat.completion.chunk", "model": body["model"], "choices": [{"index": 0, "delta": {"role": "assistant", "content": "TF_FIXTURE_OK"}, "finish_reason": None}]},
          {"id": "fixture", "object": "chat.completion.chunk", "model": body["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}]
        payload = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
      self.wfile.write(payload.encode())
      self.wfile.flush()
      self.close_connection = True
  server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  report = {"overall": "FAIL", "platform": sys.platform, "lock_identity": lock.identity, "real_account_calls": 0}
  outer_path = os.environ["PATH"]
  try:
    with tempfile.TemporaryDirectory(prefix="rotom-tf-native-", dir="/dev/shm") as private:
      root = Path(private)
      env = {"PATH": outer_path, "TERM": "xterm-256color", "LANG": "C.UTF-8"}
      for key, suffix in {"HOME": "manager", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state", "XDG_CACHE_HOME": "cache", "TMPDIR": "tmp"}.items():
        env[key] = str(root / suffix)
        ensure_private(root / suffix)
      os.environ.clear()
      os.environ.update(env)
      local = root / "machine.toml"
      config = (repo / "examples/dsh-tf.local.toml").read_text().replace('secrets_file = "~/.config/agentcfg/secrets.toml"\n', "")
      config = config.replace('tf_openai_url = ""', 'tf_openai_url = "http://127.0.0.1:' + str(server.server_port) + '/v1"')
      config = config.replace('tf_anthropic_url = ""', 'tf_anthropic_url = "http://127.0.0.1:' + str(server.server_port) + '/anthropic"')
      local.write_text(config + '\n[secrets]\nomp_kimi_tf_key="synthetic-tf"\nomp_zhipu_tf_key="synthetic-tf"\nomp_deepseek_tf_key="synthetic-tf"\n')
      local.chmod(0o600)
      workspace = load_workspace(local, repository=repo)
      candidate = workspace.candidate(lock.identity)
      commands.apply_candidate(workspace, lock, candidate)
      with Tree(workspace.state_root) as tree, instance_lock(tree):
        workspace.adapter.prepare_runtime(workspace, args.runtime.absolute())
      spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=root, runtime_root=args.runtime.absolute(), instance_root=workspace.instance, lock_identity=lock.identity)
      child_env = launch_environment(spec, workspace.resolved.data["machine"], workspace.secret_store)
      child_env.update(ROTOM_TF_ROOT=str(root), ROTOM_TF_RESULT=str(root / "result.json"), ROTOM_TF_PATCH=str(workspace.instance / "dsh-home/agentcfg.patch.yml"))
      # 输出仅在本次临时 HOME 内；最终证据只有白名单路由和布尔认证结果。
      master, slave = pty.openpty()
      with (root / "host-output.log").open("wb") as log:
        child = subprocess.Popen(["node", str(repo / "scripts/smoke-dsh-tf.mjs"), str(args.runtime.absolute())], cwd=root, env=child_env, stdin=slave, stdout=log, stderr=log)
        try:
          code = child.wait(timeout=40)
        finally:
          if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
          os.close(master)
          os.close(slave)
      report.update(native=json.loads((root / "result.json").read_text()), exit=code, requests=requests, candidate=candidate.generation)
      report["overall"] = "PASS" if code == 0 and report["native"]["overall"] == "PASS" and len(requests) == 3 else "FAIL"
  except Exception:
    report["error"] = "TF_DRIVER_FAILED"
  finally:
    server.shutdown()
    server.server_close()
  files = ["src/agentcfg/dsh.py", "agents/dsh/bindings.toml", "agents/dsh/content.toml", "schemas/registry.schema.json", "scripts/smoke-dsh-tf.py", "scripts/smoke-dsh-tf.mjs"]
  report["sources"] = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in files}
  (evidence / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
  print(json.dumps({"overall": report["overall"], "evidence": str(evidence)}))
  return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
