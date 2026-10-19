"""固定MCP stdio入口的环境隔离；exec保留Pi拥有的PID和stdio。"""

import os
from pathlib import Path
import sys

MODULES = {
  "context7": ("node_modules/@upstash/context7-mcp/dist/index.js", ["--transport", "stdio"], "CONTEXT7_API_KEY"),
  "brave": ("node_modules/@brave/brave-search-mcp-server/dist/index.js", [], "BRAVE_API_KEY"),
}


def filtered_environment(module, source):
  if module not in MODULES:
    raise ValueError("unsupported MCP module")
  allowed = {"PATH", "LANG", "TZ", "HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", MODULES[module][2]}
  if module == "brave":
    allowed.add("BRAVE_MCP_ENABLED_TOOLS")
  return {key: value for key, value in source.items() if key in allowed or key.startswith("LC_")}


def main():
  if len(sys.argv) != 2 or sys.argv[1] not in MODULES:
    raise SystemExit(2)
  module = sys.argv[1]
  entry, arguments, _ = MODULES[module]
  root = Path(__file__).resolve().parent.parent
  os.execvpe("node", ["node", str(root / entry), *arguments], filtered_environment(module, os.environ))


if __name__ == "__main__":
  main()
