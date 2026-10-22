"""本轮逐项准入的固定Pi模块；不是用户可扩展的模块DSL。"""

MODULES = {
  "catppuccin": ("catppuccin-pi-theme", "0.1.6"),
  "pi-cursor": ("@rahularya01/pi-cursor", "1.4.39"),
  "playwright-cli": ("@playwright/cli", "0.1.22"),
  "pi-footer": ("pi-footer", "0.5.1"),
  "cache-hit-monitor": ("@narumitw/pi-cache-hit-monitor", "0.1.1"),
  "pi-context7": ("@upstash/context7-mcp", "4.4.2"),
  "pi-brave": ("@brave/brave-search-mcp-server", "2.1.4"),
}
PLUGIN = {"package": "@narumitw/pi-cache-hit-monitor", "version": "0.1.1", "entry": "src/index.ts"}
PLUGINS = {"pi-cursor": {"package": "@rahularya01/pi-cursor", "version": "1.4.39", "entry": "dist/index.js"}, "cache-hit-monitor": PLUGIN, "pi-footer": {"package": "pi-footer", "version": "0.5.1", "entry": "src/index.ts"}}
MCP = {
  "pi-context7": {"module": "context7", "args": ["node_modules/@upstash/context7-mcp/dist/index.js", "--transport", "stdio"],
    "tools": ["resolve-library-id", "query-docs"], "key": "CONTEXT7_API_KEY"},
  "pi-brave": {"module": "brave", "args": ["node_modules/@brave/brave-search-mcp-server/dist/index.js"],
    "tools": ["brave_web_search"], "key": "BRAVE_API_KEY"},
}
SUPPORT = {"kind": "module-support", "id": "pi-mcp-launch", "path": "agents/pi/support/mcp-launch.py", "target": "support/mcp-launch.py"}

SUPPORTS = {
  "pi-command-aliases": {"kind": "module-support", "id": "pi-command-aliases", "path": "agents/pi/support/command-aliases.mjs", "target": "support/command-aliases.mjs"},
  "pi-browser-launch": {"kind": "module-support", "id": "pi-browser-launch", "path": "agents/pi/support/browser-launch.py", "target": "support/browser-launch.py"},
  "pi-mcp-launch": SUPPORT,
  "pi-status-observer": {"kind": "module-support", "id": "pi-status-observer", "path": "agents/pi/support/status-observer.mjs", "target": "support/status-observer.mjs"},
  "pi-footer-config": {"kind": "module-support", "id": "pi-footer-config", "path": "agents/pi/templates/pi-footer.json", "target": "support/pi-footer.json"},
}


def selected_supports(selection):
  names = ["pi-command-aliases"] + (["pi-mcp-launch"] if selection["mcp"] else [])
  if "pi-footer" in selection["plugins"]:
    names += ["pi-status-observer", "pi-footer-config"]
  if "playwright-cli" in selection["skills"]:
    names += ["pi-browser-launch"]
  return [SUPPORTS[name] for name in names]


def selected_modules(selection):
  return sorted(set(selection["resources"]["themes"] + selection["plugins"] + selection["mcp"]
    + (["playwright-cli"] if "playwright-cli" in selection["skills"] else [])))
