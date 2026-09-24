"""原生验收用确定性本地模型；只产生合成回复，不连接账号或外部模型。"""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import time
from urllib.parse import urlsplit


class ScriptedProvider:
  def __init__(self, models, *, scenario="normal", maximum_requests=100, delay_seconds=0, denied_path="/agentcfg-native-forbidden/sentinel", delegate_root=None, delegate_templates=None):
    if (not models or any(not isinstance(model, str) or not model.startswith("agentcfg-native-") for model in models)
        or scenario not in ("normal", "missing-final", "deny-path", "quota", "slow", "delegate-presets", "readseek")
        or type(maximum_requests) is not int or not 1 <= maximum_requests <= 1000 or not 0 <= delay_seconds <= 30
        or not isinstance(denied_path, str) or not denied_path.startswith("/") or "\0" in denied_path
        or scenario == "delegate-presets" and (not isinstance(delegate_root, str) or not delegate_root.startswith("/"))):
      raise ValueError("native-provider-binding")
    self.models = frozenset(models)
    self.scenario = scenario
    self.maximum = maximum_requests
    self.delay = delay_seconds
    self.denied_path = denied_path
    self.delegate_root = delegate_root
    self.delegate_templates = dict(delegate_templates or {})
    self.delivered_presets = set()
    self.inflight = 0
    self.max_inflight = 0
    self.counts = Counter()
    self.events = []
    self.mutex = threading.Lock()
    self.require_proxy = False
    self.proxy_requests = 0

  def response(self, payload):
    model = payload.get("model")
    if model not in self.models: return 404, {"error": {"message": "synthetic model not selected"}}, {}
    with self.mutex:
      self.counts[model] += 1
      number = sum(self.counts.values())
      count = self.counts[model]
      self.events.append({"request": number, "model": model})
    if number > self.maximum: return 429, {"error": {"message": "synthetic request cap"}}, {"Retry-After": "1"}
    if self.scenario == "quota" and count == 1: return 429, {"error": {"message": "synthetic rate limit"}}, {"Retry-After": "1"}
    tools = {row["function"]["name"]: row["function"] for row in payload.get("tools", []) if isinstance(row, dict) and isinstance(row.get("function"), dict)}
    messages = payload.get("messages", [])
    if self.delegate_templates and model != "agentcfg-native-main":
      contents = []
      for row in messages:
        content = row.get("content")
        if row.get("role") not in ("user", "system"): continue
        if isinstance(content, str): contents.append(content)
        elif isinstance(content, list): contents.extend(part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))
      delivered = {name for name, purpose in self.delegate_templates.items() if any(purpose in content for content in contents)}
      with self.mutex: self.delivered_presets.update(delivered)
    called = []
    for message in messages:
      if message.get("role") != "assistant": continue
      for call in message.get("tool_calls", []):
        function = call.get("function", {})
        try: arguments = json.loads(function.get("arguments", "{}"))
        except (ValueError, TypeError): arguments = {}
        called.append((function.get("name"), arguments))
    action = None
    delegate_parent = self.scenario == "delegate-presets" and model == "agentcfg-native-main" and "model_delegate" in tools
    if delegate_parent:
      text = json.dumps([row.get("content") for row in messages if row.get("role") == "user"])
      selected = re.findall(r"Native delegate preset (general|context|challenge|plan|research|review|scout)\b", text)
      if selected and not any(name == "model_delegate" and args.get("preset") == selected[-1] for name, args in called):
        action = ("model_delegate", {"backend": "pi", "mode": "review" if selected[-1] == "review" else "investigate", "preset": selected[-1],
          "task": "Read code.txt and report its content without modifying files.", "cwd": self.delegate_root, "model_role": "scout", "timeout_seconds": 120})
    read_tool = "tk_read" if "tk_read" in tools else "read" if "read" in tools else None
    if read_tool and not delegate_parent and self.scenario != "readseek":
      paths = ["code.txt"]
      if self.scenario == "deny-path": paths = [self.denied_path]
      prompts = json.dumps([row.get("content") for row in messages if row.get("role") in ("user", "system")])
      artifacts = set(re.findall(r"artifact:([A-Za-z0-9_-]+)", prompts))
      artifacts.update(re.findall(r"\bartifact-[a-f0-9]{64}\b", prompts))
      paths += ["artifact:" + identity for identity in sorted(artifacts)]
      already = {args.get("path") for name, args in called if name == read_tool and isinstance(args, dict)}
      remaining = [path for path in paths if path not in already]
      if remaining: action = (read_tool, {"path": remaining[0]})
    write_tool = "tk_write" if "tk_write" in tools else "write" if "write" in tools and model.endswith("-writer") else None
    if action is None and write_tool and not delegate_parent and not any(name == write_tool for name, _ in called):
      action = (write_tool, {"path": "code.txt", "content": "changed\n"})
    # ReadSeek九工具完整流程：按prompt点名驱动；检索→读取→写入→编辑→符号重命名→越界写入必须被拒。
    readseek_called = {name for name, _ in called}
    readseek_available = "readSeek_grep" in tools or "readSeek_view" in tools
    if action is None and self.scenario == "readseek" and readseek_available and not delegate_parent:
      user_text = json.dumps([row.get("content") for row in messages if row.get("role") == "user"])
      last_prompt = user_text[-600:]
      requested = re.findall(r"readSeek_(\w+)", last_prompt)
      if "denied" in last_prompt and "readSeek_write" in tools:
        action = ("readSeek_write", {"path": self.denied_path, "content": "must not land\n"})
      elif requested and "readSeek_" + requested[-1] in tools:
        name = "readSeek_" + requested[-1]
        if not any(called_name == name for called_name in readseek_called):
          arguments = {"readSeek_grep": {"pattern": "original", "path": "."},
            "readSeek_search": {"pattern": "def $NAME($$$ARGS):\n  $$$BODY", "path": "."},
            "readSeek_digest": {"path": "code.txt"},
            "readSeek_view": {"path": "sample.pdf"},
            "readSeek_write": {"path": "notes.py", "content": "draft one\nvalue = 1\nprint(value)\ndef helper():\n  return value\n"},
            "readSeek_edit": {"path": "notes.py", "edits": [{"replace": {"old_text": "draft one", "new_text": "draft two"}}]},
            "readSeek_def": {"name": "helper", "path": "notes.py"},
            "readSeek_refs": {"name": "value", "path": "notes.py"},
            "readSeek_rename": {"path": "notes.py", "line": 2, "to": "renamed"}}.get(name)
          if arguments is not None: action = (name, arguments)
    if action is None and not delegate_parent and self.scenario != "readseek" and "structured_output" in tools and not any(name == "structured_output" for name, _ in called):
      properties = tools["structured_output"].get("parameters", {}).get("properties", {})
      if "snapshot" in properties:
        action = ("structured_output", {"verdict": "pass", "snapshot": properties["snapshot"]["const"],
          "summary": "Synthetic native review after actual guarded reads", "scopeComplete": True, "findings": [],
          "evidence": [{"path": "code.txt", "startLine": 1, "endLine": 1}], "unverified": []})
      else: action = ("structured_output", {"summary": "Synthetic native inspection after actual guarded reads"})
    if self.scenario == "missing-final": action = None
    message = {"role": "assistant", "content": "" if self.scenario == "missing-final" else "Synthetic native execution completed."}
    if action:
      name, arguments = action
      message.update(content=None, tool_calls=[{"id": "native-call-" + str(number), "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments, separators=(",", ":"))}}])
    result = {"id": "native-response-" + str(number), "object": "chat.completion", "created": 1, "model": model,
      "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if action else "stop"}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    return 200, result, {}

  def snapshot(self):
    with self.mutex: return {"requests": sum(self.counts.values()), "models": dict(self.counts), "events": list(self.events), "delivered_presets": sorted(self.delivered_presets), "max_inflight": self.max_inflight,
      "proxy_requests": self.proxy_requests}


def streaming_body(response):
  message = response["choices"][0]["message"]
  delta = {key: value for key, value in message.items() if key in ("role", "content")}
  if "tool_calls" in message: delta["tool_calls"] = [{"index": index, **value} for index, value in enumerate(message["tool_calls"])]
  base = {key: response[key] for key in ("id", "created", "model")}; base["object"] = "chat.completion.chunk"
  frames = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
    {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": response["choices"][0]["finish_reason"]}], "usage": response["usage"]}]
  return ("".join("data: " + json.dumps(row, separators=(",", ":")) + "\n\n" for row in frames) + "data: [DONE]\n\n").encode()


class ProviderServer:
  """只能显式创建在新实例中使用；默认测试不调用此监听器。"""
  def __init__(self, provider, *, port=0):
    if type(port) is not int or port != 0 and not 1024 <= port <= 65535: raise ValueError("native-provider-port")
    self.provider = provider
    owner = self
    class Handler(BaseHTTPRequestHandler):
      def log_message(self, *_args): pass

      def do_GET(self):
        if not self.path.startswith("/searxng/") or not hasattr(owner.provider, "web_response") or self.headers.get("X-Agentcfg-Fixture-Key") != "synthetic-web-key":
          self.send_error(405 if self.path == "/mcp" else 403); return
        body = json.dumps(owner.provider.web_response()).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

      def do_POST(self):
        if owner.provider.require_proxy:
          requested = urlsplit(self.path)
          if (requested.scheme != "http" or requested.netloc != "agentcfg-native.invalid" or requested.path != "/v1/chat/completions" or requested.query
              or self.headers.get("Proxy-Authorization") != "Bearer synthetic-proxy-key"):
            self.send_error(407); return
          with owner.provider.mutex: owner.provider.proxy_requests += 1
          self.path = requested.path
        if self.path == "/mcp" and hasattr(owner.provider, "mcp_response"):
          if self.headers.get("Authorization") != "Bearer synthetic-mcp-key": self.send_error(403); return
          try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2 * 1024 * 1024: raise ValueError()
            value = owner.provider.mcp_response(json.loads(self.rfile.read(size)))
            body = json.dumps(value).encode() if value is not None else b""
            self.send_response(200 if value is not None else 202)
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
          except (ValueError, KeyError, TypeError): self.send_error(400)
          except (BrokenPipeError, ConnectionResetError): pass
          return
        if self.path not in ("/v1/chat/completions", "/v1/responses") or self.headers.get("Authorization") != "Bearer synthetic-native-key":
          self.send_error(403); return
        try:
          size = int(self.headers.get("Content-Length", "0"))
          if not 0 < size <= 2 * 1024 * 1024: raise ValueError()
          payload = json.loads(self.rfile.read(size))
          if not isinstance(payload, dict): raise ValueError()
          with owner.provider.mutex:
            owner.provider.inflight += 1
            owner.provider.max_inflight = max(owner.provider.max_inflight, owner.provider.inflight)
          try:
            if self.path == "/v1/responses":
              if not hasattr(owner.provider, "responses"): raise ValueError()
              status, headers, stream, body = 200, {}, True, owner.provider.responses(payload)
              if owner.provider.delay: time.sleep(owner.provider.delay)
            else:
              status, value, headers = owner.provider.response(payload)
              if owner.provider.scenario == "slow": time.sleep(owner.provider.delay)
              stream = status == 200 and payload.get("stream") is True
              body = streaming_body(value) if stream else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers.items(): self.send_header(name, value)
            self.end_headers(); self.wfile.write(body)
          finally:
            with owner.provider.mutex: owner.provider.inflight -= 1
        except (ValueError, KeyError, TypeError): self.send_error(400)
        except (BrokenPipeError, ConnectionResetError): pass
    self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    self.server.daemon_threads = False
    self.thread = threading.Thread(target=self.server.serve_forever, name="agentcfg-native-provider")

  @property
  def base_url(self): return "http://127.0.0.1:" + str(self.server.server_address[1]) + "/v1"

  def __enter__(self):
    self.thread.start()
    return self

  def __exit__(self, *_args):
    self.server.shutdown(); self.thread.join(); self.server.server_close()
