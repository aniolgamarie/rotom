#!/usr/bin/env python3
"""mihomo-mgr - Control mihomo via its external controller API."""

import argparse
import base64
from contextlib import contextmanager
import fcntl
import ipaddress
import json
import os
import re
import shutil
import signal
from datetime import datetime, timedelta
import socket
import stat
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
import hashlib
from collections import OrderedDict

try:
    import yaml
except ImportError:
    yaml = None
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

VERSION = "2.0.0"

DEFAULT_SOCK = ""
DEFAULT_HTTP = "http://127.0.0.1:9090"
DEFAULT_BIN_NAME = "mihomo"
DEFAULT_LOG_NAME = "mihomo.log"
DEFAULT_PID_NAME = "mihomo.pid"
DEFAULT_CONFIG_NAME = "config.yaml"
DEFAULT_RAW_SUB_NAME = "subscription.raw.yaml"
DEFAULT_MGR_CONFIG_PATH = "~/.config/mihomo-mgr/config.yaml"
DEFAULT_GFWLIST_URL = "https://gcore.jsdelivr.net/gh/gfwlist/gfwlist/gfwlist.txt"
GFWLIST_MAX_BYTES = 5 * 1024 * 1024
GFWLIST_TIMEOUT = 30
GFWLIST_BACKOFF_HOURS = 1
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_HTTP_PROXY_PORT = "10808"
DEFAULT_SOCKS_PROXY_PORT = "10808"
DEFAULT_DB_FILES = ("country.mmdb", "geosite.dat")
PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "ftp_proxy",
    "rsync_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "FTP_PROXY",
    "RSYNC_PROXY",
    "ALL_PROXY",
    "no_proxy",
    "NO_PROXY",
    "npm_config_proxy",
    "npm_config_https_proxy",
    "NPM_CONFIG_PROXY",
    "NPM_CONFIG_HTTPS_PROXY",
    "yarn_proxy",
    "yarn_https_proxy",
    "YARN_PROXY",
    "YARN_HTTPS_PROXY",
    "CARGO_HTTP_PROXY",
    "grpc_proxy",
    "GRPC_PROXY",
    "GIT_PROXY_COMMAND",
)
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1,*.local"
DB_FILES = {
    name: [
        f"https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/{name}",
        f"https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/{name}",
        f"https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/{name}",
    ]
    for name in (
        "country.mmdb",
        "geoip.dat",
        "geoip.db",
        "geoip.metadb",
        "geosite.dat",
        "geosite.db",
        "GeoLite2-ASN.mmdb",
    )
}


def _get_args():
    """Get connection args from environment or defaults."""
    cfg = _load_mgr_config()
    sock = os.environ.get("MIHOMO_SOCK", _cfg_value(cfg, "sock", DEFAULT_SOCK))
    http = os.environ.get("MIHOMO_API", _cfg_value(cfg, "api", DEFAULT_HTTP))
    secret = os.environ.get("MIHOMO_SECRET", _cfg_value(cfg, "secret", ""))
    return sock, http, secret


def _get_paths():
    cfg = _load_mgr_config()
    cwd = Path.cwd()
    config_dir = Path(
        os.environ.get("MIHOMO_CONFIG_DIR", _cfg_value(cfg, "config_dir", str(cwd)))
    ).expanduser()
    bin_dir = os.environ.get("MIHOMO_BIN_DIR", _cfg_value(cfg, "bin_dir", str(cwd)))
    bin_path = os.environ.get("MIHOMO_BIN", _cfg_value(cfg, "bin", ""))
    log_file = Path(
        os.environ.get("MIHOMO_LOG_FILE", str(config_dir / DEFAULT_LOG_NAME))
    ).expanduser()
    pid_file = Path(
        os.environ.get("MIHOMO_PID_FILE", str(config_dir / DEFAULT_PID_NAME))
    ).expanduser()
    config_file = Path(
        os.environ.get("MIHOMO_CONFIG", str(config_dir / DEFAULT_CONFIG_NAME))
    ).expanduser()
    raw_sub_file = Path(
        os.environ.get("MIHOMO_RAW_SUB", str(config_dir / DEFAULT_RAW_SUB_NAME))
    ).expanduser()
    if not bin_path:
        bin_path = str(Path(bin_dir).expanduser() / DEFAULT_BIN_NAME)
    return {
        "config_dir": config_dir,
        "bin_path": bin_path,
        "log_file": log_file,
        "pid_file": pid_file,
        "config_file": config_file,
        "raw_sub_file": raw_sub_file,
    }


class UnixHTTPHandler(urllib.request.AbstractHTTPHandler):
    """HTTP handler for Unix domain sockets."""

    def __init__(self, sock_path):
        super().__init__()
        self.sock_path = sock_path

    def http_open(self, req):
        return self.do_open(self._make_connection, req)

    def _make_connection(self, host, **kwargs):
        conn = UnixHTTPConnection(self.sock_path)
        return conn


class UnixHTTPConnection:
    """Minimal HTTP/1.1 over Unix socket."""

    def __init__(self, sock_path):
        self.sock_path = sock_path
        self._sock = None
        self._response = None
        self.timeout = 10

    def request(self, method, url, body=None, headers=None):
        headers = headers or {}
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect(self.sock_path)
        path = url
        lines = [f"{method} {path} HTTP/1.1", "Host: localhost", "Connection: close"]
        if body:
            lines.append(f"Content-Length: {len(body)}")
        for k, v in headers.items():
            lines.append(f"{k}: {v}")
        lines.append("")
        lines.append("")
        raw = "\r\n".join(lines).encode()
        if body:
            raw = raw + (body.encode() if isinstance(body, str) else body)
        self._sock.sendall(raw)

    def getresponse(self):
        data = b""
        while True:
            chunk = self._sock.recv(65536)
            if not chunk:
                break
            data += chunk
        self._sock.close()
        return _RawResponse(data)


class _RawResponse:
    """Parse raw HTTP response."""

    def __init__(self, data):
        parts = data.split(b"\r\n\r\n", 1)
        header_block = parts[0].decode(errors="replace")
        self.body = parts[1] if len(parts) > 1 else b""
        first_line = header_block.split("\r\n")[0]
        self.status = int(first_line.split(" ", 2)[1])
        self.reason = (
            first_line.split(" ", 2)[2] if len(first_line.split(" ", 2)) > 2 else ""
        )
        self._headers = {}
        for line in header_block.split("\r\n")[1:]:
            if ": " in line:
                k, v = line.split(": ", 1)
                self._headers[k.lower()] = v
        # Handle chunked transfer encoding
        if self._headers.get("transfer-encoding", "").lower() == "chunked":
            self.body = self._decode_chunked(self.body)

    def _decode_chunked(self, data):
        result = b""
        while data:
            line_end = data.find(b"\r\n")
            if line_end == -1:
                break
            size_str = data[:line_end].decode().strip()
            if not size_str:
                data = data[line_end + 2 :]
                continue
            chunk_size = int(size_str, 16)
            if chunk_size == 0:
                break
            result += data[line_end + 2 : line_end + 2 + chunk_size]
            data = data[line_end + 2 + chunk_size + 2 :]
        return result

    def read(self):
        return self.body

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)


# ── API Client ───────────────────────────────────────────────────────


def api(method, path, body=None, quiet=False):
    """Call mihomo API. Uses a configured Unix socket, otherwise HTTP."""
    sock, http_url, secret = _get_args()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    if sock and Path(sock).exists():
        conn = UnixHTTPConnection(sock)
        conn.request(
            method, path, body=json.dumps(body) if body else None, headers=headers
        )
        resp = conn.getresponse()
        raw = resp.read()
        if resp.status >= 400:
            if not quiet:
                print(
                    f"API error {resp.status}: {raw.decode(errors='replace')}",
                    file=sys.stderr,
                )
            sys.exit(1)
        return (json.loads(raw) if raw.strip() else None) or {}
    else:
        url = http_url.rstrip("/") + path
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return (json.loads(raw) if raw.strip() else None) or {}
        except urllib.error.HTTPError as e:
            if not quiet:
                print(
                    f"API error {e.code}: {e.read().decode(errors='replace')}",
                    file=sys.stderr,
                )
            sys.exit(1)
        except urllib.error.URLError as e:
            if not quiet:
                print(f"API connection error: {e}", file=sys.stderr)
            sys.exit(1)


# ── Interactive Picker ───────────────────────────────────────────────


def _interactive_filter(items, prompt="Filter", show_index=True):
    """交互式过滤器：显示列表，用户输入关键词实时过滤。

    Args:
        items: 要显示的条目列表 [(display_text, data), ...]
        prompt: 输入提示
        show_index: 是否显示编号

    Returns:
        选中的 data，或 None 表示取消
    """
    if not items:
        print("  (空)")
        return None

    filtered = items[:]

    while True:
        # 显示当前过滤结果（限制显示条数，避免占满终端）
        term_height = shutil.get_terminal_size().lines
        # 预留 5 行用于提示和输入
        max_display = max(10, term_height - 5)
        display_items = filtered
        truncated = False
        if len(filtered) > max_display:
            display_items = filtered[:max_display]
            truncated = True
            show_index = True  # 截断时强制显示编号，方便用户选择

        print()
        for i, (display, _) in enumerate(display_items):
            prefix = f"  [{i + 1}] " if show_index else "  "
            print(f"{prefix}{display}")
        if truncated:
            print(
                f"  ... 还有 {len(filtered) - max_display} 项未显示，请输入关键词过滤"
            )

        if len(filtered) == 0:
            print("  (无匹配项)")
            return None

        if len(filtered) == 1:
            # 只有一个匹配，询问是否选择
            print("\n  只有一个匹配项，是否选择?")
            try:
                confirm = input("  按 Enter 选择，或输入 q 取消: ").strip()
                if confirm.lower() == "q":
                    return None
                return filtered[0][1]
            except (EOFError, KeyboardInterrupt):
                print()
                return None

        # 获取用户输入
        print()
        try:
            user_input = input(
                f"  {prompt} (1-{len(filtered)}, 关键词, /正则/, q=取消): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if not user_input:
            continue

        if user_input.lower() == "q":
            return None

        # 尝试解析为编号
        try:
            idx = int(user_input)
            if 1 <= idx <= len(filtered):
                return filtered[idx - 1][1]
            print(f"  ⚠️  无效编号，请输入 1-{len(filtered)}")
            continue
        except ValueError:
            pass

        # 作为过滤词（支持正则）
        try:
            if (
                user_input.startswith("/")
                and user_input.endswith("/")
                and len(user_input) > 2
            ):
                # 正则模式: /pattern/
                pattern = re.compile(user_input[1:-1], re.IGNORECASE)
                filtered = [(d, data) for d, data in items if pattern.search(d)]
                if not filtered:
                    print(f"  ⚠️  正则 /{user_input[1:-1]}/ 无匹配")
                    filtered = items[:]
            else:
                # 子串匹配
                keyword = user_input.lower()
                filtered = [(d, data) for d, data in items if keyword in d.lower()]
                if not filtered:
                    print(f"  ⚠️  关键词 '{user_input}' 无匹配")
                    filtered = items[:]
        except re.error as e:
            print(f"  ⚠️  无效正则: {e}")
            filtered = items[:]


def _pick_group_menu(selected_group, proxies, group_types):
    """组级操作菜单。"""
    group_data = api("GET", f"/proxies/{_urlencode(selected_group)}")
    if "all" not in group_data:
        print(f"  ❌ '{selected_group}' 不是有效组。")
        return

    group_info = proxies.get(selected_group, {})
    gtype = group_info.get("type", "?")
    current = group_data.get("now", "")
    all_nodes = group_data.get("all") or []

    # 过滤非真实节点
    group_names = {k for k, v in proxies.items() if v.get("type") in group_types}
    skip = ("DIRECT", "REJECT", "GLOBAL")
    real_nodes = [n for n in all_nodes if n not in skip and n not in group_names]

    while True:
        print(f"\n📂 组操作: {selected_group}")
        print(f"   类型: {gtype}  |  当前: {current}  |  节点数: {len(real_nodes)}")
        print("-" * 50)
        print("  [1] 🔌 选择节点 (切换/测速/详情)")
        print("  [2] 🏓 测试所有节点延迟")
        print("  [3] ⚡ 自动选最快节点 (best)")
        print("  [4] 📋 查看组详情")
        print("  [5] 🔙 返回选择组")
        print("  [q] ❌ 退出")
        print()

        try:
            choice = input("  请选择 (1-5): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice == "1":
            _pick_node_menu(selected_group, real_nodes, current)

        elif choice == "2":
            print(f"\n  🏓 测试 {len(real_nodes)} 个节点延迟...")
            _delay_group_impl(
                selected_group, "http://www.gstatic.com/generate_204", 5000, 10
            )

        elif choice == "3":
            print("\n  ⚡ 自动选最快节点...")
            # 复用 best 逻辑
            keywords_input = input("  输入过滤关键词 (直接回车=全部): ").strip()
            if keywords_input:
                keywords = keywords_input.split()
            else:
                keywords = [n for n in real_nodes]

            if not keywords:
                print("  ❌ 没有可用节点")
                continue

            # 如果输入的是关键词，过滤节点
            if keywords_input:
                kw_lower = [k.lower() for k in keywords]
                filtered = [
                    n for n in real_nodes if any(kw in n.lower() for kw in kw_lower)
                ]
            else:
                filtered = real_nodes

            if not filtered:
                print(f"  ❌ 没有匹配 '{keywords_input}' 的节点")
                continue

            print(f"  测试 {len(filtered)} 个节点...")
            alive, dead, total = _best_test_all(
                filtered,
                "http://www.gstatic.com/generate_204",
                5000,
                10,
                keywords_input,
            )
            if alive:
                best_name, best_delay = alive[0]
                print(f"\n  🏆 最快: {best_name} ({best_delay}ms)")
                if best_name != current:
                    confirm = input(f"  切换到 {best_name}? (Y/n): ").strip()
                    if confirm.lower() != "n":
                        api(
                            "PUT",
                            f"/proxies/{_urlencode(selected_group)}",
                            {"name": best_name},
                        )
                        print(f"  ✅ 已切换 → {best_name}")
                else:
                    print("  ℹ️  已经是当前节点")
            else:
                print("  ❌ 所有节点不可达")

        elif choice == "4":
            print(f"\n  📋 组详情: {selected_group}")
            print(f"     类型: {gtype}")
            print(f"     当前节点: {current}")
            print(f"     总节点数: {len(all_nodes)}")
            print(f"     真实节点: {len(real_nodes)}")
            # 显示子组（如果有的话）
            sub_groups = [n for n in all_nodes if n in group_names]
            if sub_groups:
                print(f"     子组: {', '.join(sub_groups)}")

        elif choice == "5":
            return  # 返回上一层

        elif choice.lower() == "q":
            return  # 退出


def _pick_node_menu(selected_group, real_nodes, current):
    """节点级操作菜单。"""
    nodes = []
    for name in real_nodes:
        marker = " ★" if name == current else ""
        display = f"{name}{marker}"
        nodes.append((display, name))

    if not nodes:
        print("  ❌ 组内没有节点")
        return

    print(f"\n🔌 选择节点 (当前: {current})")
    print("-" * 50)
    selected_node = _interactive_filter(nodes, "选择节点")

    if not selected_node:
        return

    print(f"\n  ✅ 已选择: {selected_node}")

    # 节点操作
    while True:
        print(f"\n🎯 节点操作: {selected_node}")
        if selected_node == current:
            print("   (当前节点)")
        print("-" * 50)
        print("  [1] 🔄 切换到这个节点")
        print("  [2] 🏓 测试延迟")
        print("  [3] 📋 查看详情")
        print("  [4] 🔙 返回选择节点")
        print("  [q] ❌ 退出")
        print()

        try:
            choice = input("  请选择 (1-4): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice == "1":
            if selected_node == current:
                print("\n  ℹ️  已经是当前节点")
            else:
                api(
                    "PUT",
                    f"/proxies/{_urlencode(selected_group)}",
                    {"name": selected_node},
                )
                print(f"\n  ✅ 已切换 '{selected_group}' → {selected_node}")

        elif choice == "2":
            print("\n  🏓 测试延迟中...")
            result = api(
                "GET",
                f"/proxies/{_urlencode(selected_node)}/delay?timeout=5000&url=http://www.gstatic.com/generate_204",
            )
            d = result.get("delay") or 0
            if d > 0:
                print(f"  ✅ {selected_node}: {d}ms")
            else:
                print(f"  ❌ {selected_node}: 超时")

        elif choice == "3":
            node_data = api("GET", f"/proxies/{_urlencode(selected_node)}", quiet=True)
            print("\n  📋 节点详情:")
            print(f"     名称: {selected_node}")
            print(f"     类型: {node_data.get('type', '?')}")
            if node_data.get("history"):
                last = node_data["history"][-1]
                delay = last.get("delay", 0)
                if delay:
                    print(f"     上次延迟: {delay}ms")
                else:
                    print("     上次延迟: 超时")

        elif choice == "4":
            return  # 返回选节点

        elif choice.lower() == "q":
            return


def cmd_pick(args):
    """Interactive picker: select group → group/node actions."""
    print("\n🔍 Interactive Picker")
    print("=" * 50)
    print("\n💡 操作提示:")
    print("   • 输入关键词过滤列表 (如: 节点、香港、IEPL)")
    print("   • 输入 /正则/ 使用正则表达式 (如: /IEPL.*港/)")
    print("   • 输入编号直接选择 (如: 1、2、3)")
    print("   • 输入 q 取消或返回上一步")
    print()

    # Step 1: 选择代理组
    try:
        proxies_data = api("GET", "/proxies", quiet=True)
    except SystemExit:
        print("  ❌ 无法连接 mihomo API")
        return

    proxies = proxies_data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")

    groups = []
    for name, g in sorted(proxies.items()):
        if g.get("type") in group_types:
            now = g.get("now", "-")
            count = len(g.get("all") or [])
            display = f"{name}  → {now}  [{count} nodes]"
            groups.append((display, name))

    if not groups:
        print("  ❌ 未找到代理组")
        return

    print("📡 选择代理组")
    print("-" * 50)
    selected_group = _interactive_filter(groups, "选择组")

    if not selected_group:
        print("\n  ❌ 已取消")
        return

    print(f"\n  ✅ 已选择: {selected_group}")

    # Step 2: 组级操作菜单
    _pick_group_menu(selected_group, proxies, group_types)


# ── Commands ─────────────────────────────────────────────────────────


def cmd_status(args):
    """Show overall status."""
    try:
        ver = api("GET", "/version", quiet=True)
        cfg = api("GET", "/configs", quiet=True)
        conns = api("GET", "/connections", quiet=True)
        proxies_data = api("GET", "/proxies", quiet=True)
    except SystemExit:
        if args.json:
            json.dump({"error": "API unavailable"}, sys.stdout)
            print()
        else:
            _print_process_status()
            print("\nAPI: unavailable")
        return

    if args.json:
        # JSON output for scripting
        proxies = proxies_data.get("proxies") or {}
        group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
        groups = {}
        for name, g in proxies.items():
            if g.get("type") in group_types:
                groups[name] = {
                    "type": g.get("type"),
                    "now": g.get("now"),
                    "all_count": len(g.get("all") or []),
                }
        result = {
            "version": ver.get("version"),
            "mode": cfg.get("mode"),
            "mixed_port": cfg.get("mixed-port"),
            "tun_enabled": (cfg.get("tun") or {}).get("enable", False),
            "log_level": cfg.get("log-level"),
            "connections_active": len(conns.get("connections") or []),
            "upload_bytes": conns.get("uploadTotal", 0),
            "download_bytes": conns.get("downloadTotal", 0),
            "proxy_groups": groups,
        }
        json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return

    # Human-readable output
    _print_process_status()

    nc = len(conns.get("connections") or [])
    up = conns.get("uploadTotal", 0)
    down = conns.get("downloadTotal", 0)

    print(f"\nMihomo {ver.get('version', '?')}")
    print(f"Mode: {cfg.get('mode', '?')}")
    print(f"Mixed port: {cfg.get('mixed-port', '?')}")
    tun = cfg.get("tun") or {}
    print(
        f"TUN: {'enabled' if tun.get('enable') else 'disabled'} ({tun.get('stack', '?')})"
    )
    print(f"Log level: {cfg.get('log-level', '?')}")
    print(f"Connections: {nc} active")
    print(f"Traffic: ↑ {_fmt_bytes(up)}  ↓ {_fmt_bytes(down)}")

    # Show current proxy selections
    proxies = proxies_data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    groups = {k: v for k, v in proxies.items() if v.get("type") in group_types}
    if groups:
        print("\nProxy groups:")
        for name, g in sorted(groups.items()):
            now = g.get("now", "-")
            # Resolve chain: if 'now' is also a group, follow it
            chain = [now]
            seen = {name}
            cur = now
            while (
                cur in proxies
                and proxies[cur].get("type") in group_types
                and cur not in seen
            ):
                seen.add(cur)
                cur = proxies[cur].get("now", "")
                if cur:
                    chain.append(cur)
            chain_str = " → ".join(chain)
            print(f"  {name}: {chain_str}")

    # 7.1 Top 5 domain traffic
    try:
        db_path = _get_stats_db_path()
        if db_path.exists():
            start_hour = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H")
            db_conn = sqlite3.connect(str(db_path))
            cur = db_conn.cursor()
            cur.execute(
                """
                SELECT domain, SUM(upload_bytes + download_bytes)
                FROM hourly_domain
                WHERE hour >= ?
                GROUP BY domain
                ORDER BY SUM(upload_bytes + download_bytes) DESC
                LIMIT 5
            """,
                (start_hour,),
            )
            top_domains = cur.fetchall()
            db_conn.close()
            if top_domains:
                print("\nTop 5 domains (24h):")
                max_bytes = top_domains[0][1] if top_domains else 1
                for domain, total in top_domains:
                    bar = _render_bar(total, max_bytes, 10)
                    print(f"  {domain:<25} {bar} {_fmt_bytes(total)}")
    except Exception:
        pass


def cmd_mode(args):
    """Get or set proxy mode."""
    if args.value:
        if _routing_has_active() and args.value == "global":
            raise RoutingError("global mode bypasses the active local routing policy")
        if args.value == "rule" and _guard_is_tripped():
            raise RoutingError("traffic guard is tripped; release it before restoring rule mode")
        api("PATCH", "/configs", {"mode": args.value})
        print(f"Mode set to: {args.value}")
    else:
        cfg = api("GET", "/configs")
        print(f"Mode: {cfg.get('mode', '?')}")


def cmd_groups(args):
    """List proxy groups."""
    data = api("GET", "/proxies")
    proxies = data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    groups = {k: v for k, v in proxies.items() if v.get("type") in group_types}
    for name, g in sorted(groups.items()):
        now = g.get("now", "-")
        n = len(g.get("all") or [])
        t = g.get("type", "?")
        print(f"  {name} ({t}): {now}  [{n} nodes]")


def _fetch_node_delay(node_name):
    """获取单个节点的延迟信息。返回 (name, delay_ms)。"""
    try:
        node_data = api("GET", f"/proxies/{_urlencode(node_name)}", quiet=True)
        history = node_data.get("history") or []
        delay = (history[-1].get("delay") or 0) if history else 0
        return node_name, delay
    except (SystemExit, Exception):
        return node_name, 0


def _node_matches(node_name, patterns, use_regex):
    """检查节点名是否匹配任一 pattern。
    use_regex=True 时使用 re.search，否则使用子串匹配（均忽略大小写）。
    """
    if use_regex:
        return any(re.search(p, node_name, re.IGNORECASE) for p in patterns)
    name_lower = node_name.lower()
    return any(p.lower() in name_lower for p in patterns)


def _resolve_group(group_pattern, use_regex=False):
    """解析组名。

    匹配优先级：
    1. 精确匹配：直接返回
    2. use_regex=True：正则匹配
    3. 自动 fallback：子串匹配（忽略大小写）

    返回实际组名。匹配多个时提示并选第一个，无匹配时退出。
    """
    # 获取所有代理组名
    data = api("GET", "/proxies", quiet=True)
    proxies = data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    group_names = [k for k, v in proxies.items() if v.get("type") in group_types]

    # 1. 精确匹配
    if group_pattern in group_names:
        return group_pattern

    # 2. 正则匹配
    if use_regex:
        try:
            pattern = re.compile(group_pattern, re.IGNORECASE)
        except re.error as e:
            print(f"Invalid group regex '{group_pattern}': {e}", file=sys.stderr)
            sys.exit(1)
        matched = [g for g in group_names if pattern.search(g)]
        if matched:
            if len(matched) > 1:
                print(f"Multiple groups match /{group_pattern}/ (using first):")
                for g in matched[:5]:
                    print(f"    - {g}")
                if len(matched) > 5:
                    print(f"    ... +{len(matched) - 5} more")
            return matched[0]
        # 正则也没匹配到，继续 fallback

    # 3. 自动 fallback：子串匹配（忽略大小写）
    pattern_lower = group_pattern.lower()
    matched = [g for g in group_names if pattern_lower in g.lower()]

    if not matched:
        print(f"No group matching '{group_pattern}'.", file=sys.stderr)
        print(
            f"  Available groups: {', '.join(sorted(group_names)[:10])}",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(matched) > 1:
        print(f"Multiple groups contain '{group_pattern}' (using first):")
        for g in matched[:5]:
            print(f"    - {g}")
        if len(matched) > 5:
            print(f"    ... +{len(matched) - 5} more")
    return matched[0]


def cmd_nodes(args):
    """List nodes in a proxy group."""
    use_regex = getattr(args, "regex", False)
    group = _resolve_group(args.group, use_regex)
    data = api("GET", f"/proxies/{_urlencode(group)}")
    if "all" not in data:
        print(f"'{group}' is not a group or not found.", file=sys.stderr)
        sys.exit(1)
    now = data.get("now", "")
    all_nodes = data.get("all") or []
    # --filter: 按关键词/正则过滤显示的节点
    filter_patterns = getattr(args, "filter", None) or []
    if filter_patterns:
        all_nodes = [
            n for n in all_nodes if _node_matches(n, filter_patterns, use_regex)
        ]
        match_label = "regex" if use_regex else "keyword"
        print(
            f"Group: {group} ({data.get('type', '?')}) [filter({match_label}): {'|'.join(filter_patterns)}]"
        )
    else:
        print(f"Group: {group} ({data.get('type', '?')})")
    print(f"Current: {now}\n")
    # 并行获取节点延迟
    delays = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_node_delay, n): n for n in all_nodes}
        for future in as_completed(futures):
            name, delay = future.result()
            delays[name] = delay
    for node_name in all_nodes:
        marker = " ★" if node_name == now else ""
        delay = delays.get(node_name, 0)
        delay_str = f"{delay}ms" if delay > 0 else "N/A"
        print(f"  {node_name}{marker}  ({delay_str})")


def cmd_select(args):
    """Select a node in a proxy group."""
    use_regex = getattr(args, "regex", False)
    group = _resolve_group(args.group, use_regex)
    node = args.node
    if use_regex:
        # 正则模式：从组内节点中查找第一个匹配项
        data = api("GET", f"/proxies/{_urlencode(group)}")
        if "all" not in data:
            print(f"'{group}' is not a group or not found.", file=sys.stderr)
            sys.exit(1)
        all_nodes = data.get("all") or []
        matched = [n for n in all_nodes if re.search(node, n, re.IGNORECASE)]
        if not matched:
            print(f"No node matching /{node}/ in '{group}'.", file=sys.stderr)
            sys.exit(1)
        if len(matched) > 1:
            print(
                f"Multiple matches (selecting first): {', '.join(matched[:5])}{'...' if len(matched) > 5 else ''}"
            )
        node = matched[0]
    api("PUT", f"/proxies/{_urlencode(group)}", {"name": node})
    print(f"Switched '{group}' → {node}")


def cmd_delay(args):
    """Test delay for a node or group (auto-detect).

    If target is a group name, tests all nodes in the group.
    If target is a node name, tests just that node.
    With --regex, target is treated as a regex pattern for group matching.
    """
    url = args.url or "http://www.gstatic.com/generate_204"
    timeout = args.timeout or 1000
    target = args.target
    use_regex = getattr(args, "regex", False)

    # 检查是否是组名（--regex 时直接用正则匹配）
    data = api("GET", "/proxies", quiet=True)
    proxies = data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    group_names = [k for k, v in proxies.items() if v.get("type") in group_types]

    matched_group = None
    if use_regex:
        import re

        matches = [g for g in group_names if re.search(target, g, re.IGNORECASE)]
        if len(matches) == 1:
            matched_group = matches[0]
        elif len(matches) > 1:
            print(f"Multiple groups match regex '{target}':")
            for g in matches[:5]:
                print(f"  - {g}")
            print("Please be more specific.")
            sys.exit(1)
    elif target in group_names:
        matched_group = target
    else:
        target_lower = target.lower()
        matches = [g for g in group_names if target_lower in g.lower()]
        if len(matches) == 1:
            matched_group = matches[0]
        elif len(matches) > 1:
            print(f"Multiple groups match '{target}':")
            for g in matches[:5]:
                print(f"  - {g}")
            print("Please be more specific.")
            sys.exit(1)

    if matched_group:
        # 是组名，测试所有节点
        print(f"Detected as group '{matched_group}', testing all nodes...")
        _delay_group_impl(matched_group, url, timeout, getattr(args, "concurrency", 10))
    else:
        # 是节点名，测试单个节点
        result = api(
            "GET",
            f"/proxies/{_urlencode(target)}/delay?timeout={timeout}&url={_urlencode(url)}",
        )
        d = result.get("delay") or 0
        if d > 0:
            print(f"{target}: {d}ms")
        else:
            print(f"{target}: timeout / unreachable")


def _delay_group_impl(group, url, timeout, concurrency):
    """Implementation of delay-group testing."""
    data = api("GET", f"/proxies/{_urlencode(group)}")
    if "all" not in data:
        print(f"'{group}' is not a group.", file=sys.stderr)
        sys.exit(1)
    # 从 API 获取所有策略组名，过滤掉非真实节点
    proxies_data = api("GET", "/proxies", quiet=True)
    proxies = proxies_data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    group_names = {k for k, v in proxies.items() if v.get("type") in group_types}
    _skip_exact = ("DIRECT", "REJECT", "GLOBAL")

    def _is_real_node(name):
        return name not in _skip_exact and name not in group_names

    all_nodes = [n for n in data.get("all") or [] if _is_real_node(n)]
    total = len(all_nodes)
    print(
        f"Testing {total} nodes in '{group}' (timeout={timeout}ms, concurrency={concurrency})...\n"
    )
    results = []
    lock = threading.Lock()
    completed = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_test_node_delay, n, url, timeout): n for n in all_nodes
        }
        for future in as_completed(futures):
            name, d = future.result()
            with lock:
                completed += 1
                results.append((name, d))
                elapsed = time.time() - start
                ds = f"{d}ms" if d > 0 else "timeout"
                print(
                    f"\r  [{completed}/{total}] {name:<30} {ds:>8}  ({elapsed:.0f}s)    ",
                    end="",
                    flush=True,
                )
    # Clear progress line
    print("\r" + " " * 80 + "\r", end="")
    elapsed = time.time() - start
    # Sort by delay (0 = timeout, put at end)
    results.sort(key=lambda x: (x[1] == 0, x[1]))
    now_name = data.get("now", "")
    alive = [(n, d) for n, d in results if d > 0]
    dead = [(n, d) for n, d in results if d == 0]
    # 3-column compact display for reachable nodes
    cols, col_w = 3, 30
    for i in range(0, len(alive), cols):
        line = ""
        for name, d in alive[i : i + cols]:
            marker = " ★" if name == now_name else ""
            s = f"{name}{marker}: {d}ms"
            # 超长名称截断以保持列对齐
            if _display_width(s) > col_w:
                suffix = f"{marker}: {d}ms"
                max_w = col_w - _display_width(suffix) - 2
                t = name
                while _display_width(t) > max_w and t:
                    t = t[:-1]
                s = f"{t}..{suffix}" if t else s[: col_w - 1] + "…"
            line += _pad_display(s, col_w)
        print("  " + line)
    # Timeout nodes: summary line
    if dead:
        dead_now = [f"{n} ★" if n == now_name else n for n, _ in dead]
        preview = ", ".join(dead_now[:4])
        tail = f" +{len(dead) - 4} more" if len(dead) > 4 else ""
        print(f"  timeout ({len(dead)}): {preview}{tail}")
    # Summary line
    avg = sum(d for _, d in alive) // len(alive) if alive else 0
    fastest = alive[0][1] if alive else "-"
    print(
        f"\n  {total} nodes │ {elapsed:.1f}s │ reachable: {len(alive)} │ fastest: {fastest}ms │ avg: {avg}ms │ timeout: {len(dead)}"
    )


def _test_node_delay(node_name, url, timeout):
    """Thread-safe node delay test. Returns (name, delay_ms)."""
    try:
        r = api(
            "GET",
            f"/proxies/{_urlencode(node_name)}/delay?timeout={timeout}&url={_urlencode(url)}",
            quiet=True,
        )
        return node_name, r.get("delay", 0) or 0
    except (SystemExit, Exception):
        return node_name, 0


def _display_width(s):
    """Calculate display width accounting for CJK wide characters."""
    import unicodedata

    w = 0
    for c in s:
        ea = unicodedata.east_asian_width(c)
        w += 2 if ea in ("W", "F") else 1
    return w


def _pad_display(s, width):
    """Pad string to given display width, handling CJK correctly."""
    dw = _display_width(s)
    if dw >= width:
        return s
    return s + " " * (width - dw)


def cmd_delay_group(args):
    """Test delay for all nodes in a group concurrently.

    This is kept for backward compatibility. The unified `delay` command
    now auto-detects whether the target is a group or node.
    """
    url = args.url or "http://www.gstatic.com/generate_204"
    timeout = args.timeout or 1000
    concurrency = getattr(args, "concurrency", 10) or 10
    use_regex = getattr(args, "regex", False)
    group = _resolve_group(args.group, use_regex)
    _delay_group_impl(group, url, timeout, concurrency)


# ── best: YAML 配置操作 ──────────────────────────────────────────────

_BEST_GROUP_PREFIX = "🎯 best-"
_BEST_STATE_PATH = "~/.config/mihomo-mgr/best-watch.json"


def _best_group_name(keywords):
    """根据关键词生成 url-test 组名。"""
    return _BEST_GROUP_PREFIX + "".join(keywords)


def _best_state_path():
    return Path(_BEST_STATE_PATH).expanduser()


def _best_save_state(group, original_node, ut_group, keywords):
    """保存 watch 状态，用于 --watch-off 恢复。"""
    path = _best_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "group": group,
        "original_node": original_node,
        "ut_group": ut_group,
        "keywords": keywords,
    }
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def _best_load_state():
    """加载 watch 状态。"""
    try:
        return json.loads(_best_state_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _best_clear_state():
    """清除 watch 状态。"""
    try:
        _best_state_path().unlink()
    except FileNotFoundError:
        pass


def _yaml_quote(name):
    """YAML flow format 引用名称（含特殊字符时用单引号）。"""
    if name and all(c.isalnum() or c in "-_." for c in name):
        return name
    return "'" + name.replace("'", "''") + "'"


def _line_is_group(line, group_name):
    """判断一行是否是目标 proxy-group 的定义（flow-style 单行格式）。"""
    stripped = line.strip()
    if not stripped.startswith("- {"):
        return False
    for fmt in [
        f"name: '{group_name}'",
        f'name: "{group_name}"',
        f"name: {group_name},",
        f"name: {group_name} ",
    ]:
        if fmt in stripped:
            return True
    return False


def _add_to_proxies_list(line, new_proxy_quoted):
    """在 proxies: [...] 的开头添加一个代理名。"""
    idx = line.find("proxies: [")
    if idx < 0:
        return line
    insert_at = idx + len("proxies: [")
    rest = line[insert_at:].lstrip()
    if rest.startswith("]"):
        return line[:insert_at] + new_proxy_quoted + line[insert_at:]
    return line[:insert_at] + new_proxy_quoted + ", " + line[insert_at:]


def _remove_from_proxies_list(line, group_name):
    """从 proxies: [...] 中删除一个代理名（处理各种引用格式和逗号）。"""
    for fmt in [
        f"'{group_name}', ",
        f'"{group_name}", ',
        f"{group_name}, ",
        f", '{group_name}'",
        f', "{group_name}"',
        f", {group_name}",
        f"'{group_name}'",
        f'"{group_name}"',
    ]:
        idx = line.find(fmt)
        if idx >= 0:
            return line[:idx] + line[idx + len(fmt) :]
    return line


def _config_add_watch_group(
    raw, ut_group, filtered_nodes, url, interval, tolerance, timeout, target_group
):
    """在 config.yaml 中添加 url-test 组，并加入目标 Selector 的 proxies 列表。
    返回修改后的 YAML 文本，如果找不到 proxy-groups 则返回 None。
    """
    proxies_str = ", ".join(_yaml_quote(n) for n in filtered_nodes)
    ut_line = (
        f"    - {{ name: '{ut_group}', type: url-test,"
        f" url: '{url}', interval: {interval}, tolerance: {tolerance}, timeout: {timeout},"
        f" proxies: [{proxies_str}] }}"
    )
    ut_quoted = _yaml_quote(ut_group)

    # Store watch group config in overlay
    overlay_content = f"# Watch group: {ut_group}\n"
    overlay_content += f"# Target group: {target_group}\n"
    overlay_content += f"# Nodes: {', '.join(filtered_nodes)}\n"
    overlay_content += f"# URL: {url}\n"
    overlay_content += f"# Interval: {interval}s\n"
    overlay_content += f"# Tolerance: {tolerance}ms\n"
    overlay_content += f"# Timeout: {timeout}ms\n\n"
    overlay_content += f"group_definition: |\n  {ut_line}\n"
    overlay_content += f"target_group: {target_group}\n"
    overlay_content += f"group_name: {ut_quoted}\n"
    _write_overlay("watch-groups.yaml", overlay_content)

    if yaml is not None:
        try:
            config = yaml.safe_load(raw)
            groups = config.get("proxy-groups") if isinstance(config, dict) else None
            if not isinstance(groups, list):
                return None
            groups.insert(
                0,
                {
                    "name": ut_group,
                    "type": "url-test",
                    "url": url,
                    "interval": interval,
                    "tolerance": tolerance,
                    "timeout": timeout,
                    "proxies": list(filtered_nodes),
                },
            )
            for group in groups:
                if isinstance(group, dict) and group.get("name") == target_group:
                    proxies = group.setdefault("proxies", [])
                    if isinstance(proxies, list) and ut_group not in proxies:
                        proxies.insert(0, ut_group)
                    break
            return yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception:
            return None

    lines = raw.splitlines()
    out = []
    group_inserted = False
    proxy_added = False

    for line in lines:
        if not group_inserted and line.rstrip() == "proxy-groups:":
            out.append(line)
            out.append(ut_line)
            group_inserted = True
            continue
        if not proxy_added and _line_is_group(line, target_group):
            line = _add_to_proxies_list(line, ut_quoted)
            proxy_added = True
        out.append(line)

    if not group_inserted:
        return None
    return "\n".join(out) + "\n"


def _config_remove_watch_group(raw, ut_group, target_group):
    """从 config.yaml 中移除 url-test 组，并从目标 Selector 的 proxies 列表中删除。
    返回 (修改后的 YAML 文本, 是否找到了组)。
    """
    if yaml is not None:
        try:
            config = yaml.safe_load(raw)
            groups = config.get("proxy-groups") if isinstance(config, dict) else None
            if not isinstance(groups, list):
                return raw, False
            kept = []
            removed = False
            for group in groups:
                if isinstance(group, dict) and group.get("name") == ut_group:
                    removed = True
                    continue
                if isinstance(group, dict) and group.get("name") == target_group:
                    proxies = group.get("proxies")
                    if isinstance(proxies, list):
                        group["proxies"] = [name for name in proxies if name != ut_group]
                kept.append(group)
            config["proxy-groups"] = kept
            return (
                yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False),
                removed,
            )
        except Exception:
            return raw, False
    lines = raw.splitlines()
    out = []
    removed = False
    for line in lines:
        if _line_is_group(line, ut_group):
            removed = True
            continue
        if _line_is_group(line, target_group):
            line = _remove_from_proxies_list(line, ut_group)
        out.append(line)
    return "\n".join(out) + "\n", removed


def _config_has_group(raw, group_name):
    """检查 YAML 文本中是否包含指定名称的 proxy-group。"""
    if yaml is not None:
        try:
            config = yaml.safe_load(raw) or {}
            return any(
                isinstance(group, dict) and group.get("name") == group_name
                for group in config.get("proxy-groups", [])
            )
        except Exception:
            pass
    return any(_line_is_group(line, group_name) for line in raw.splitlines())


def _api_raw(method, path, body=None):
    """调用 mihomo API，不退出程序。返回 (success: bool, data: dict|None)。"""
    sock, http_url, secret = _get_args()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    try:
        if sock and Path(sock).exists():
            conn = UnixHTTPConnection(sock)
            body_bytes = (
                body if isinstance(body, bytes) else (body.encode() if body else None)
            )
            conn.request(method, path, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.status >= 400:
                return False, None
            return True, (json.loads(raw) if raw.strip() else None) or {}
        else:
            url = http_url.rstrip("/") + path
            data = (
                body if isinstance(body, bytes) else (body.encode() if body else None)
            )
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                return True, (json.loads(raw) if raw.strip() else None) or {}
    except Exception:
        return False, None


def _group_exists_in_api(group_name):
    """检查组是否在 mihomo 运行时中存在（不退出程序）。"""
    ok, data = _api_raw("GET", f"/proxies/{_urlencode(group_name)}")
    return ok and data is not None


def _reload_mihomo(wait_for_group=None, restart_process=False):
    """重载 mihomo 配置。
    如果 restart_process=True 或修改了 proxy-groups，需要重启进程。
    否则使用 PUT /configs 热重载。
    如果指定了 wait_for_group，还会等待该组出现在 proxies API 中。
    返回是否成功。
    """
    paths = _get_paths()
    config_file = paths["config_file"]

    if restart_process or not config_file.exists():
        # 重启进程：先停止，再启动
        pid_file = paths["pid_file"]
        pid = _read_pid(pid_file)
        if pid and _is_pid_running(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(10):
                    time.sleep(0.5)
                    if not _is_pid_running(pid):
                        break
                else:
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.5)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
        _unlink_if_exists(pid_file)

        # 启动新进程
        bin_path = paths["bin_path"]
        config_dir = paths["config_dir"]
        log_file = paths["log_file"]
        if not _binary_exists(bin_path):
            return False

        config_dir.mkdir(parents=True, exist_ok=True)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.parent.mkdir(parents=True, exist_ok=True)

        cmd = [bin_path, "-d", str(config_dir)]
        if config_file.exists():
            cmd.extend(["-f", str(config_file)])

        with log_file.open("ab") as log:
            proc = subprocess.Popen(
                cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
        pid_file.write_text(str(proc.pid) + "\n")
    else:
        # 热重载：发送配置文件路径
        try:
            payload = json.dumps({"path": str(config_file)}).encode()
            ok, _ = _api_raw("PUT", "/configs", body=payload)
            if not ok:
                return False
        except Exception:
            return False

    # 等待 API 恢复
    api_ready = False
    for _ in range(30):
        time.sleep(0.5)
        ok, _ = _api_raw("GET", "/version")
        if ok:
            api_ready = True
            break
    if not api_ready:
        return False
    # 等待指定组出现
    if wait_for_group:
        for _ in range(30):
            time.sleep(0.5)
            if _group_exists_in_api(wait_for_group):
                return True
        return False
    return True


# ── best: 核心逻辑 ──────────────────────────────────────────────────


def _best_filter_nodes(group_name, keywords, use_regex=False):
    """按关键词/正则过滤策略组中的真实节点。返回 (filtered, group_data)。"""
    data = api("GET", f"/proxies/{_urlencode(group_name)}")
    if "all" not in data:
        print(f"'{group_name}' is not a group or not found.", file=sys.stderr)
        sys.exit(1)

    proxies_data = api("GET", "/proxies", quiet=True)
    proxies = proxies_data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    group_names = {k for k, v in proxies.items() if v.get("type") in group_types}
    _skip_exact = ("DIRECT", "REJECT", "GLOBAL")

    # 验证正则表达式
    if use_regex:
        compiled = []
        for kw in keywords:
            try:
                compiled.append(re.compile(kw, re.IGNORECASE))
            except re.error as e:
                print(f"Invalid regex '{kw}': {e}", file=sys.stderr)
                sys.exit(1)

    all_nodes = data.get("all") or []
    filtered = [
        n
        for n in all_nodes
        if n not in _skip_exact
        and n not in group_names
        and _node_matches(n, keywords, use_regex)
    ]

    if not filtered:
        match_desc = "/" + "/|".join(keywords) + "/" if use_regex else str(keywords)
        print(f"No nodes matching {match_desc} in '{group_name}'.")
        regions = set()
        for n in all_nodes:
            if n not in _skip_exact and n not in group_names:
                parts = n.split("-")
                if len(parts) >= 2:
                    region_name = "".join(c for c in parts[1] if not c.isdigit())
                    if region_name:
                        regions.add(region_name)
        if regions:
            print(f"  Available regions: {', '.join(sorted(regions))}")
        sys.exit(1)

    return filtered, data


def _best_test_all(filtered, url, timeout, concurrency, kw_display):
    """并发测试所有节点延迟，返回 (alive, dead, total)。"""
    total = len(filtered)
    results = []
    lock = threading.Lock()
    completed = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_test_node_delay, n, url, timeout): n for n in filtered
        }
        for future in as_completed(futures):
            name, d = future.result()
            with lock:
                completed += 1
                results.append((name, d))
                elapsed = time.time() - start
                ds = f"{d}ms" if d > 0 else "timeout"
                print(
                    f"\r  [{completed}/{total}] {name:<30} {ds:>8}  ({elapsed:.0f}s)    ",
                    end="",
                    flush=True,
                )
    print("\r" + " " * 80 + "\r", end="")

    results.sort(key=lambda x: (x[1] == 0, x[1]))
    alive = [(n, d) for n, d in results if d > 0]
    dead = [(n, d) for n, d in results if d == 0]
    return alive, dead, total


def _best_print_results(alive, dead, total, kw_display):
    """打印测试结果。"""
    print(f"  Reachable nodes ({len(alive)}/{total}):")
    for i, (name, d) in enumerate(alive):
        marker = " ← best" if i == 0 else ""
        print(f"    {i + 1:>2}. {name}: {d}ms{marker}")
    if dead:
        print(
            f"  Timeout ({len(dead)}): {', '.join(n for n, _ in dead[:5])}{'...' if len(dead) > 5 else ''}"
        )


def _best_switch(group, node_name, dry_run=False):
    """切换策略组到指定节点。"""
    if dry_run:
        print(f"  (dry-run, would switch to {node_name})")
        return
    api("PUT", f"/proxies/{_urlencode(group)}", {"name": node_name})
    print(f"  ✓ Switched '{group}' → {node_name}")


def _best_list_watches():
    """列出所有活跃的 watch 组及其运行状态。"""
    # 从 API 获取所有 proxy groups
    try:
        proxies_data = api("GET", "/proxies", quiet=True)
    except SystemExit:
        print("Cannot connect to mihomo API.", file=sys.stderr)
        sys.exit(1)

    proxies = proxies_data.get("proxies") or {}

    # 过滤出 best- 前缀的 URLTest 组
    watch_groups = {}
    for name, g in proxies.items():
        if name.startswith(_BEST_GROUP_PREFIX) and g.get("type") == "URLTest":
            watch_groups[name] = g

    if not watch_groups:
        print("No active watch groups.")
        return

    # 加载状态文件
    state = _best_load_state()

    print(f"Active watch groups ({len(watch_groups)}):\n")

    for name, g in watch_groups.items():
        now = g.get("now", "-")
        all_nodes = g.get("all") or []
        node_count = len(all_nodes)

        # 获取当前节点的延迟
        delay = 0
        if now and now in proxies:
            node_data = proxies.get(now) or {}
            history = node_data.get("history") or []
            if history:
                delay = history[-1].get("delay") or 0

        # 从状态文件获取关联信息
        target_group = ""
        keywords = []
        original_node = ""
        if state and state.get("ut_group") == name:
            target_group = state.get("group", "")
            keywords = state.get("keywords", [])
            original_node = state.get("original_node", "")

        # 显示组信息
        print(f"  {name}")
        print("    Type: URLTest")
        print(f"    Nodes: {node_count}")
        print(f"    Current: {now}")
        if delay > 0:
            print(f"    Delay: {delay}ms")
        elif delay == 0 and now != "-":
            print("    Delay: timeout")

        if target_group:
            print(f"    Target: {target_group}")
        if keywords:
            print(f"    Keywords: {', '.join(keywords)}")
        if original_node:
            print(f"    Original: {original_node}")
        print()


def _best_watch_off(args, dry_run):
    """清理 watch 模式：移除 url-test 组，恢复原始选择。"""
    state = _best_load_state()

    if args.keywords:
        ut_group = _best_group_name(args.keywords)
        group = args.group
    elif state:
        ut_group = state["ut_group"]
        group = state["group"]
    else:
        print("No watch state found. Specify group and keywords, e.g.:")
        print('  mihomo-mgr.py best "\U0001f680 节点选择" 日本 美国 --watch-off')
        sys.exit(1)

    original_node = state.get("original_node", "") if state else ""
    print(f"Removing watch: {ut_group}")

    if dry_run:
        print(f"  (dry-run) Would remove '{ut_group}' from config")
        print("  (dry-run) Would reload mihomo")
        if original_node:
            print(f"  (dry-run) Would switch '{group}' → {original_node}")
        return

    paths = _get_paths()
    config_file = paths["config_file"]
    if not config_file.exists():
        print(f"  Config file not found: {config_file}", file=sys.stderr)
        _best_clear_state()
        return

    raw = config_file.read_text()
    new_raw, removed = _config_remove_watch_group(raw, ut_group, group)

    if not removed:
        print(f"  Group '{ut_group}' not found in config (already removed?).")
        _best_clear_state()
        return

    new_raw = _routing_compose(new_raw)
    if _routing_has_active():
        _routing_validate_with_core(new_raw, config_file)
    config_file.write_text(new_raw)
    print(f"  Removed '{ut_group}' from config.")

    print("  Restarting mihomo...")
    if not _reload_mihomo(restart_process=True):
        print("  ✗ Mihomo failed to restart.", file=sys.stderr)
        config_file.write_text(raw)
        print("  Config rolled back.", file=sys.stderr)
        sys.exit(1)
    print("  ✓ Mihomo restarted.")
    _delete_overlay("watch-groups.yaml")

    if original_node:
        try:
            api("PUT", f"/proxies/{_urlencode(group)}", {"name": original_node})
            print(f"  ✓ Switched '{group}' → {original_node}")
        except SystemExit:
            print(
                f"  Warning: could not switch back to '{original_node}'.",
                file=sys.stderr,
            )

    _best_clear_state()
    print("\n  Watch removed.")


def _cmd_best_unlocked(args):
    """Filter nodes by keywords, test delays, and auto-select the fastest.

    With --watch, creates a url-test proxy group in config.yaml with the
    filtered nodes, reloads mihomo, and lets the native url-test mechanism
    handle health checks and failover — no external polling needed.
    """
    cfg = _load_mgr_config()
    url = (
        args.url
        or _cfg_value(cfg, "health_check_url")
        or "http://www.gstatic.com/generate_204"
    )
    timeout = args.timeout or 5000
    concurrency = args.concurrency or 10
    keywords = args.keywords
    kw_display = ", ".join(keywords)
    dry_run = args.dry_run
    use_regex = getattr(args, "regex", False)

    # ── list: 列出所有 watch 组 ──
    if getattr(args, "list", False):
        _best_list_watches()
        return

    # 解析组名（支持正则）
    group = _resolve_group(args.group, use_regex)

    # ── switch: 切换到指定的 watch 组 ──
    if getattr(args, "switch", False):
        if not keywords:
            print(
                'Error: keywords are required. Example: best "\U0001f680 节点选择" 日本 美国 --switch',
                file=sys.stderr,
            )
            sys.exit(1)
        ut_group = _best_group_name(keywords)
        if dry_run:
            print(f"  (dry-run) Would switch '{group}' → {ut_group}")
            return
        try:
            api("PUT", f"/proxies/{_urlencode(group)}", {"name": ut_group})
            print(f"  ✓ Switched '{group}' → {ut_group}")
        except SystemExit:
            print(
                f"  ✗ Failed to switch. Group '{ut_group}' may not exist.",
                file=sys.stderr,
            )
            print(
                f'  Create it first: mihomo-mgr.py best "{group}" {" ".join(keywords)} --watch',
                file=sys.stderr,
            )
        return

    # ── watch-off: 清理模式 ──
    if getattr(args, "watch_off", False):
        _best_watch_off(args, dry_run)
        return

    if not keywords:
        print(
            'Error: keywords are required. Example: best "\U0001f680 节点选择" 日本 美国',
            file=sys.stderr,
        )
        sys.exit(1)

    match_label = f"regex: {kw_display}" if use_regex else kw_display

    # ── 过滤节点 ──
    filtered, data = _best_filter_nodes(group, keywords, use_regex=use_regex)
    total = len(filtered)
    now_name = data.get("now", "")

    # ── 初始测试 ──
    print(f"Filtering {total} nodes matching [{match_label}] in '{group}'...")
    print(f"Testing delays (timeout={timeout}ms, concurrency={concurrency})...\n")

    alive, dead, total = _best_test_all(filtered, url, timeout, concurrency, kw_display)

    if not alive:
        print(f"All {total} nodes matching [{kw_display}] are unreachable.")
        sys.exit(1)

    _best_print_results(alive, dead, total, kw_display)
    best_name, best_delay = alive[0]
    print(f"\n  Best: {best_name} ({best_delay}ms)")

    # ── 非 watch 模式：直接选择最快节点 ──
    if not args.watch:
        if best_name == now_name:
            print("  Already selected — no change needed.")
        else:
            if now_name:
                print(f"  Previous: {now_name}")
            _best_switch(group, best_name, dry_run)
        return

    # ── watch 模式：创建 url-test 组，让 mihomo 原生接管 ──
    ut_group = _best_group_name(keywords)
    interval = args.interval or 15
    tolerance = args.tolerance or 50
    health_timeout = args.health_timeout or 2000

    if dry_run:
        print(f"\n  (dry-run) Would create url-test group: {ut_group}")
        print(
            f"  (dry-run) Nodes: {len(alive)}, interval={interval}s, tolerance={tolerance}ms, timeout={health_timeout}ms"
        )
        print(f"  (dry-run) Would switch '{group}' → {ut_group}")
        return

    # 读取 config.yaml
    paths = _get_paths()
    config_file = paths["config_file"]
    if not config_file.exists():
        print(f"\n  Config file not found: {config_file}", file=sys.stderr)
        print(
            "  Watch mode requires a config file. Run 'sub-pull' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    raw = config_file.read_text()

    if _config_has_group(raw, ut_group):
        print(f"\n  url-test group '{ut_group}' already exists in config.")
        # 检查 mihomo 运行时是否已加载该组
        if _group_exists_in_api(ut_group):
            print("  Group already loaded in mihomo.")
        else:
            # 组在 config 里但 mihomo 没加载，需要重启进程
            print("  Group not loaded in mihomo, restarting...")
            if not _reload_mihomo(wait_for_group=ut_group, restart_process=True):
                print("  ✗ Mihomo failed to restart.", file=sys.stderr)
                sys.exit(1)
            print("  ✓ Mihomo restarted.")
    else:
        alive_names = [n for n, _ in alive]
        old_watch_overlay = _read_overlay("watch-groups.yaml")
        new_raw = _config_add_watch_group(
            raw,
            ut_group,
            alive_names,
            url,
            interval,
            tolerance,
            health_timeout,
            group,
        )
        if new_raw is None:
            if old_watch_overlay:
                _write_overlay("watch-groups.yaml", old_watch_overlay)
            else:
                _delete_overlay("watch-groups.yaml")
            print(
                "\n  Failed to parse config: proxy-groups section not found.",
                file=sys.stderr,
            )
            sys.exit(1)

        new_raw = _routing_compose(new_raw)
        if _routing_has_active():
            try:
                _routing_validate_with_core(new_raw, config_file)
            except Exception:
                if old_watch_overlay:
                    _write_overlay("watch-groups.yaml", old_watch_overlay)
                else:
                    _delete_overlay("watch-groups.yaml")
                raise
        config_file.write_text(new_raw)
        print(
            f"\n  Added url-test group '{ut_group}' ({len(alive)} nodes, interval={interval}s, timeout={health_timeout}ms)"
        )

        # 重启 mihomo，等待新组出现
        print("  Restarting mihomo...")
        if not _reload_mihomo(wait_for_group=ut_group, restart_process=True):
            print("  ✗ Mihomo failed to restart.", file=sys.stderr)
            config_file.write_text(raw)
            if old_watch_overlay:
                _write_overlay("watch-groups.yaml", old_watch_overlay)
            else:
                _delete_overlay("watch-groups.yaml")
            print("  Config rolled back.", file=sys.stderr)
            sys.exit(1)
        print("  ✓ Mihomo restarted.")

    # 切换策略组到 url-test 组
    api("PUT", f"/proxies/{_urlencode(group)}", {"name": ut_group})
    print(f"  ✓ Switched '{group}' → {ut_group}")

    # 保存状态（用于 --watch-off 恢复）
    _best_save_state(group, now_name, ut_group, keywords)

    print("\n  Watch active. Mihomo natively handles health checks and failover.")
    print(f'  To stop: mihomo-mgr.py best "{group}" --watch-off')


def cmd_best(args):
    if getattr(args, "watch", False) or getattr(args, "watch_off", False):
        with _publish_lock():
            return _cmd_best_unlocked(args)
    return _cmd_best_unlocked(args)


def cmd_conns(args):
    """List active connections."""
    data = api("GET", "/connections")
    conns = data.get("connections") or []
    if not conns:
        print("No active connections.")
        return
    up = data.get("uploadTotal", 0)
    down = data.get("downloadTotal", 0)
    print(
        f"Total: {len(conns)} connections  ↑ {_fmt_bytes(up)}  ↓ {_fmt_bytes(down)}\n"
    )
    # Sort by download speed desc
    conns.sort(key=lambda c: c.get("download", 0), reverse=True)
    limit = args.limit or 20
    for c in conns[:limit]:
        meta = c.get("metadata") or {}
        host = meta.get("host") or meta.get("destinationIP", "?")
        port = meta.get("destinationPort", "")
        chain = " → ".join(c.get("chains") or [])
        rule = c.get("rule", "")
        dl = _fmt_bytes(c.get("download", 0))
        ul = _fmt_bytes(c.get("upload", 0))
        print(f"  {host}:{port}  ↑{ul} ↓{dl}  [{chain}]  ({rule})")


def cmd_conns_close(args):
    """Close connections."""
    if args.id:
        api("DELETE", f"/connections/{args.id}")
        print(f"Closed connection {args.id}")
    else:
        api("DELETE", "/connections")
        print("Closed all connections.")


def cmd_rules(args):
    """List rules."""
    data = api("GET", "/rules")
    rules = data.get("rules") or []
    limit = args.limit or 30
    print(f"Total: {len(rules)} rules (showing first {limit})\n")
    for r in rules[:limit]:
        print(f"  {r.get('type', '?')}: {r.get('payload', '')} → {r.get('proxy', '')}")


def cmd_dns(args):
    """Query DNS resolution."""
    result = api("GET", f"/dns/query?name={_urlencode(args.domain)}&type={args.type}")
    answers = result.get("Answer") or []
    if not answers:
        print(f"No DNS records for {args.domain}")
        return
    for a in answers:
        print(f"  {a.get('Name', '')}  {a.get('Type', '')}  {a.get('data', '')}")


def cmd_flush_dns(args):
    """Flush DNS cache."""
    api("POST", "/cache/flushdns")
    print("DNS cache flushed.")


def cmd_restart(args):
    """Restart mihomo core."""
    if _routing_has_active():
        with _publish_lock():
            config_file = _get_paths()["config_file"]
            if not config_file.exists():
                raise RoutingError(f"Mihomo config not found: {config_file}")
            old = config_file.read_text()
            candidate = _compose_overlays(old)
            _routing_validate_with_core(candidate, config_file)
            if candidate != old:
                _atomic_write_text(config_file, candidate)
    api("PUT", "/restart")
    print("Core restarting...")


def cmd_upgrade_geo(args):
    """Update GeoIP/GeoSite databases."""
    api("POST", "/configs/geo")
    print("GeoIP/GeoSite update triggered.")


def cmd_db_check(args):
    """Check required mihomo database files."""
    names = _selected_db_files(args)
    missing = _missing_db_files(names)
    if not missing:
        print("DB files: ok")
        return

    print("Missing DB files:")
    for name in missing:
        print(f"  {name}")
    if args.download:
        _download_db_files(missing)


def cmd_db_download(args):
    """Download missing or requested mihomo database files."""
    names = _selected_db_files(args)
    missing = names if args.force else _missing_db_files(names)
    if not missing:
        print("DB files: ok")
        return
    _download_db_files(missing)


def cmd_start(args):
    """Start mihomo as a background process."""
    # 旧入口会隐式下载数据库、改写有效配置并启动统计进程。
    # termcfg 的显式服务路径接管这一职责；保留其余查询/配置命令供迁移。
    raise RuntimeError("legacy_start_disabled: use ./termcfg service start")
    paths = _get_paths()
    if _read_running_pid(paths["pid_file"]):
        print(f"mihomo is already running (pid {_read_pid(paths['pid_file'])})")
        return

    paths["config_dir"].mkdir(parents=True, exist_ok=True)
    paths["log_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["pid_file"].parent.mkdir(parents=True, exist_ok=True)

    if not _binary_exists(paths["bin_path"]):
        print(f"mihomo binary not found: {paths['bin_path']}", file=sys.stderr)
        sys.exit(1)

    if not args.skip_db_check:
        missing = _missing_db_files(DEFAULT_DB_FILES)
        if missing:
            _download_db_files(missing)

    selected_config = Path(args.config).expanduser() if args.config else paths["config_file"]
    selected_paths = dict(paths)
    selected_paths["config_file"] = selected_config

    # 启动前把 config.json 的参数同步到实际启动配置
    if not args.no_patch:
        if _patch_config_yaml(_load_mgr_config(), selected_paths):
            print("Patched config.yaml with config-set values")

    policy = _routing_load()
    if args.no_patch and policy and policy.get("enabled") and policy.get("active"):
        with _publish_lock():
            policy = _routing_load(required=True)
            if not selected_config.exists():
                raise RoutingError(f"Mihomo config not found: {selected_config}")
            current = selected_config.read_text()
            composed = _routing_compose(current, policy=policy)
            if composed != current:
                _routing_validate_with_core(composed, selected_config)
                _atomic_write_text(selected_config, composed)

    cmd = [paths["bin_path"], "-d", str(paths["config_dir"])]
    if args.config:
        cmd.extend(["-f", str(selected_config)])
    elif paths["config_file"].exists():
        cmd.extend(["-f", str(paths["config_file"])])

    with paths["log_file"].open("ab") as log:
        proc = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
    paths["pid_file"].write_text(str(proc.pid) + "\n")
    print(f"Started mihomo pid {proc.pid}")
    print(f"Log: {paths['log_file']}")

    # Record manual override for schedule
    _record_manual_override("start")

    # 自动启动流量统计守护进程
    _start_traffic_daemon()
    print("Traffic stats daemon started")


def cmd_stop(args):
    """Stop mihomo process started by mihomo-mgr."""
    paths = _get_paths()
    pid = _read_pid(paths["pid_file"])
    if not pid or not _is_pid_running(pid):
        print("mihomo is not running")
        _unlink_if_exists(paths["pid_file"])
        return

    # Record manual override for schedule
    _record_manual_override("stop")

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _unlink_if_exists(paths["pid_file"])
        print(f"Stopped mihomo pid {pid} (already exited)")
        return
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if not _is_pid_running(pid):
            _unlink_if_exists(paths["pid_file"])
            print(f"Stopped mihomo pid {pid}")
            return
        time.sleep(0.2)

    if args.force:
        os.kill(pid, signal.SIGKILL)
        _unlink_if_exists(paths["pid_file"])
        print(f"Killed mihomo pid {pid}")
    else:
        print(f"mihomo pid {pid} did not stop within {args.timeout}s")


def cmd_restart_proc(args):
    """Restart mihomo process."""
    cmd_stop(args)
    cmd_start(args)


def cmd_logs(args):
    """Show recent mihomo log lines."""
    paths = _get_paths()
    log_path = paths["log_file"]
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return

    if args.follow:
        print(f"Following {log_path} (Ctrl-C to stop)...")
        try:
            subprocess.run(
                ["tail", "-n", str(args.lines), "-f", str(log_path)], check=False
            )
        except KeyboardInterrupt:
            print()
        return

    size = _fmt_bytes(log_path.stat().st_size)
    with log_path.open("rb") as f:
        line_count = sum(1 for _ in f)
    print(f"Log: {log_path} ({size}, {line_count} lines)")
    if line_count == 0:
        return
    print()
    for line in _tail(log_path, args.lines):
        print(line, end="")


def cmd_logs_clear(args):
    """Truncate or trim the mihomo log file."""
    paths = _get_paths()
    log_path = paths["log_file"]
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return

    if args.keep:
        lines = _tail(log_path, args.keep)
        log_path.write_text("".join(lines))
        print(
            f"Trimmed {log_path} to last {args.keep} lines ({_fmt_bytes(log_path.stat().st_size)})"
        )
    else:
        log_path.write_text("")
        print(f"Cleared {log_path}")


def cmd_config(args):
    """Show persisted mihomo-mgr configuration."""
    cfg = _load_mgr_config()
    paths = _get_paths()
    print(f"Config store: {_mgr_config_path()}")
    if cfg:
        print("Persisted:")
        for key in sorted(cfg):
            value = cfg[key]
            if isinstance(value, dict):
                print(f"  {key}:")
                for subkey, subvalue in sorted(value.items()):
                    if isinstance(subvalue, dict):
                        print(f"    {subkey}:")
                        for k, v in sorted(subvalue.items()):
                            print(f"      {k}: {v}")
                    elif isinstance(subvalue, list):
                        print(f"    {subkey}: {', '.join(str(x) for x in subvalue)}")
                    else:
                        print(f"    {subkey}: {subvalue}")
            elif isinstance(value, list):
                print(f"  {key}: {', '.join(str(x) for x in value)}")
            else:
                print(f"  {key}: {value}")
    else:
        print("Persisted: none")
    print("Effective:")
    print(f"  config_dir: {paths['config_dir']}")
    print(f"  bin: {paths['bin_path']}")
    print(f"  log_file: {paths['log_file']}")
    print(f"  pid_file: {paths['pid_file']}")
    print(f"  raw_sub_file: {paths['raw_sub_file']}")
    print(f"  config_file: {paths['config_file']}")
    sock, api_url, secret = _get_args()
    print(f"  api: {api_url}")
    print(f"  sock: {sock or '-'}")
    print(f"  secret: {'set' if secret else '-'}")
    http_url, socks_url, no_proxy = _proxy_values(
        argparse.Namespace(
            host=None,
            http_port=None,
            socks_port=None,
            http=None,
            socks=None,
            no_proxy=None,
        )
    )
    mixed_port = _cfg_value(cfg, "mixed_port", "-")
    print(f"  mixed_port: {mixed_port}")
    print(f"  proxy_http: {http_url}")
    print(f"  proxy_socks: {socks_url}")
    print(f"  no_proxy: {no_proxy}")
    health_check_url = _cfg_value(cfg, "health_check_url", "-")
    print(f"  health_check_url: {health_check_url}")
    direct_domains = cfg.get("direct_domains") or []
    if direct_domains:
        print(f"  direct_domains: {', '.join(direct_domains)}")
    else:
        print("  direct_domains: (none)")


def cmd_config_init(args):
    """Create an editable default configuration file."""
    path = _mgr_config_path()
    if path.exists() and not args.force:
        print(f"Config already exists: {path}")
        print("Use --force to overwrite it.")
        return
    _atomic_mgr_config(path, _default_mgr_config_text())
    print(f"Created {path}")
    print(
        "Edit this file to set subscription URL, paths, proxy ports, and API settings."
    )


def cmd_config_set(args):
    """Persist mihomo-mgr configuration."""
    cfg = _load_mgr_config()
    updates = {
        "config_dir": args.persist_config_dir,
        "bin_dir": args.persist_bin_dir,
        "bin": args.persist_bin,
        "log_file": args.persist_log_file,
        "pid_file": args.persist_pid_file,
        "api": args.persist_api,
        "sock": args.persist_sock,
        "sub_url": args.persist_sub_url,
        "proxy_host": args.persist_proxy_host,
        "mixed_port": args.persist_mixed_port,
        "proxy_http_port": args.persist_proxy_http_port,
        "proxy_socks_port": args.persist_proxy_socks_port,
        "proxy_http": args.persist_proxy_http,
        "proxy_socks": args.persist_proxy_socks,
        "no_proxy": args.persist_no_proxy,
        "health_check_url": args.persist_health_check_url,
    }
    # 校验端口值
    for key in ("mixed_port", "proxy_http_port", "proxy_socks_port"):
        val = updates.get(key)
        if val:
            try:
                port = int(val)
                if not (1 <= port <= 65535):
                    raise ValueError
            except ValueError:
                print(f"Invalid port value for {key} (must be 1-65535)", file=sys.stderr)
                sys.exit(1)
    for key, value in updates.items():
        if value:
            cfg[key] = (
                str(Path(value).expanduser())
                if key.endswith("_dir") or key.endswith("_file") or key == "bin"
                else value
            )
    if args.persist_secret is not None:
        cfg["secret"] = args.persist_secret
    # 白名单域名管理
    if getattr(args, "clear_direct_domains", False):
        cfg.pop("direct_domains", None)
        print("  Cleared direct_domains whitelist.")
    remove_domains = getattr(args, "remove_direct_domain", None)
    if remove_domains:
        existing = cfg.get("direct_domains") or []
        cfg["direct_domains"] = [d for d in existing if d not in remove_domains]
        print("  Removed entries from direct_domains.")
    add_domains = getattr(args, "add_direct_domain", None)
    if add_domains:
        existing = cfg.get("direct_domains") or []
        for d in add_domains:
            d = d.strip()
            if d and d not in existing:
                existing.append(d)
        cfg["direct_domains"] = existing
        print(f"  Added to direct_domains: {', '.join(add_domains)}")

    # ── Stats configuration ──
    stats = cfg.setdefault("stats", {})
    if not isinstance(stats, dict):
        stats = {}
        cfg["stats"] = stats
    if getattr(args, "persist_stats_enabled", None) is not None:
        stats["enabled"] = args.persist_stats_enabled.lower() in ("true", "1", "yes")
    if getattr(args, "persist_stats_db", None):
        stats["db"] = str(Path(args.persist_stats_db).expanduser())
    if getattr(args, "persist_stats_retention_days", None) is not None:
        stats["retention_days"] = args.persist_stats_retention_days
    if getattr(args, "persist_stats_poll_interval", None) is not None:
        stats["poll_interval"] = args.persist_stats_poll_interval

    # ── Idle detection configuration ──
    idle = cfg.setdefault("idle", {})
    if not isinstance(idle, dict):
        idle = {}
        cfg["idle"] = idle
    if getattr(args, "persist_idle_enabled", None) is not None:
        idle["enabled"] = args.persist_idle_enabled.lower() in ("true", "1", "yes")
    if getattr(args, "persist_idle_auto_block_level", None):
        idle["auto_block_level"] = args.persist_idle_auto_block_level
    if getattr(args, "persist_idle_block_after_notify_count", None) is not None:
        idle["block_after_notify_count"] = args.persist_idle_block_after_notify_count
    if getattr(args, "persist_idle_cooldown_minutes", None) is not None:
        idle["cooldown_minutes"] = args.persist_idle_cooldown_minutes
    # Idle whitelist management
    wl = idle.setdefault("whitelist", [])
    if not isinstance(wl, list):
        wl = []
        idle["whitelist"] = wl
    for proc in getattr(args, "remove_idle_whitelist", None) or []:
        if proc in wl:
            wl.remove(proc)
            print(f"  Removed from idle whitelist: {proc}")
    for proc in getattr(args, "add_idle_whitelist", None) or []:
        if proc not in wl:
            wl.append(proc)
            print(f"  Added to idle whitelist: {proc}")
    # Idle blacklist management
    bl = idle.setdefault("blacklist", [])
    if not isinstance(bl, list):
        bl = []
        idle["blacklist"] = bl
    for proc in getattr(args, "remove_idle_blacklist", None) or []:
        if proc in bl:
            bl.remove(proc)
            print(f"  Removed from idle blacklist: {proc}")
    for proc in getattr(args, "add_idle_blacklist", None) or []:
        if proc not in bl:
            bl.append(proc)
            print(f"  Added to idle blacklist: {proc}")

    # ── Schedule configuration ──
    schedule = cfg.setdefault("schedule", {})
    if not isinstance(schedule, dict):
        schedule = {}
        cfg["schedule"] = schedule
    if getattr(args, "persist_schedule_enabled", None) is not None:
        schedule["enabled"] = args.persist_schedule_enabled.lower() in (
            "true",
            "1",
            "yes",
        )
    if getattr(args, "persist_schedule_work_hours", None):
        schedule["work_hours"] = args.persist_schedule_work_hours
    if getattr(args, "persist_schedule_work_days", None):
        schedule["work_days"] = args.persist_schedule_work_days

    # ── Guard（流量熔断）configuration ──
    guard = cfg.setdefault("guard", {})
    if not isinstance(guard, dict):
        guard = {}
        cfg["guard"] = guard
    if getattr(args, "persist_guard_enabled", None) is not None:
        guard["enabled"] = args.persist_guard_enabled.lower() in ("true", "1", "yes")
    if getattr(args, "persist_guard_wall", None) is not None:
        guard["wall"] = args.persist_guard_wall.lower() in ("true", "1", "yes")
    if getattr(args, "persist_guard_quota_gb", None) is not None:
        guard["monthly_quota_gb"] = float(args.persist_guard_quota_gb)
    if getattr(args, "persist_guard_trip_pct", None) is not None:
        guard["trip_threshold_pct"] = float(args.persist_guard_trip_pct)
    if getattr(args, "persist_guard_warn_pct", None) is not None:
        guard["warn_threshold_pct"] = float(args.persist_guard_warn_pct)
    if getattr(args, "persist_guard_monthly_warn_pct", None) is not None:
        guard["monthly_warn_pct"] = float(args.persist_guard_monthly_warn_pct)
    if getattr(args, "persist_guard_disable_hours", None) is not None:
        guard["disable_hours"] = float(args.persist_guard_disable_hours)

    # ── Notification configuration ──
    notify = cfg.setdefault("notify", {})
    if not isinstance(notify, dict):
        notify = {}
        cfg["notify"] = notify
    dingtalk = notify.setdefault("dingtalk", {})
    if not isinstance(dingtalk, dict):
        dingtalk = {}
        notify["dingtalk"] = dingtalk
    if getattr(args, "persist_notify_dingtalk_webhook", None) is not None:
        dingtalk["webhook"] = args.persist_notify_dingtalk_webhook
    if getattr(args, "persist_notify_dingtalk_secret", None) is not None:
        dingtalk["secret"] = args.persist_notify_dingtalk_secret

    _save_mgr_config(cfg)
    _invalidate_config_cache()
    print(f"Saved {_mgr_config_path()}")


def cmd_config_clear(args):
    """Remove persisted mihomo-mgr configuration."""
    _unlink_if_exists(_mgr_config_path())
    _invalidate_config_cache()
    print(f"Removed {_mgr_config_path()}")


def cmd_proxy_status(args):
    """Show proxy variables configured in the current terminal environment."""
    active = []
    missing = []
    for key in PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            active.append((key, value))
        else:
            missing.append(key)

    print("Proxy environment:")
    if active:
        for key, value in active:
            print(f"  {key}={value}")
    else:
        print("  none")

    coverage_keys = (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    )
    coverage = sum(1 for key in coverage_keys if os.environ.get(key))
    print(f"Coverage: {coverage}/{len(coverage_keys)} core variables configured")
    http_url, socks_url, no_proxy = _proxy_values(
        argparse.Namespace(
            host=None,
            http_port=None,
            socks_port=None,
            http=None,
            socks=None,
            no_proxy=None,
        )
    )
    print("Proxy-on target:")
    print(f"  http: {http_url}")
    print(f"  socks: {socks_url}")
    print(f"  no_proxy: {no_proxy}")
    if missing and args.verbose:
        print("Missing:")
        for key in missing:
            print(f"  {key}")


def cmd_proxy_on(args):
    """Print shell exports for a temporary proxy environment."""
    http_url, socks_url, no_proxy = _proxy_values(args)
    exports = {
        "http_proxy": http_url,
        "https_proxy": http_url,
        "ftp_proxy": http_url,
        "rsync_proxy": http_url,
        "all_proxy": socks_url,
        "HTTP_PROXY": http_url,
        "HTTPS_PROXY": http_url,
        "FTP_PROXY": http_url,
        "RSYNC_PROXY": http_url,
        "ALL_PROXY": socks_url,
        "no_proxy": no_proxy,
        "NO_PROXY": no_proxy,
        "npm_config_proxy": http_url,
        "npm_config_https_proxy": http_url,
        "NPM_CONFIG_PROXY": http_url,
        "NPM_CONFIG_HTTPS_PROXY": http_url,
        "yarn_proxy": http_url,
        "yarn_https_proxy": http_url,
        "YARN_PROXY": http_url,
        "YARN_HTTPS_PROXY": http_url,
        "CARGO_HTTP_PROXY": http_url,
        "grpc_proxy": http_url,
        "GRPC_PROXY": http_url,
    }
    for key, value in exports.items():
        print(f"export {key}={_shell_quote(value)}")
    if not args.quiet:
        print('# Apply with: eval "$(mihomo-mgr.py proxy-on)"')


def cmd_proxy_off(args):
    """Print shell commands that unset proxy variables."""
    for key in PROXY_ENV_KEYS:
        print(f"unset {key}")
    if not args.quiet:
        print('# Apply with: eval "$(mihomo-mgr.py proxy-off)"')


def _install_subscription_unlocked(raw, cfg, paths):
    """Validate and transactionally install raw/generated subscription files."""
    candidate = _compose_overlays(_normalize_subscription_config(raw, cfg))
    config_file = paths["config_file"]
    raw_file = paths["raw_sub_file"]
    old_config = config_file.read_text() if config_file.exists() else None
    old_raw = raw_file.read_text() if raw_file.exists() else None
    if _routing_has_active():
        _routing_validate_with_core(candidate, config_file)
    reachable = False
    payload = json.dumps({"path": str(config_file)}).encode()
    try:
        _atomic_write_text(config_file, candidate)
        _atomic_write_text(raw_file, raw)
        reachable, _ = _api_raw("GET", "/version")
        if reachable:
            ok, _ = _api_raw("PUT", "/configs", body=payload)
            if not ok:
                raise RoutingError("Mihomo reload failed")
    except Exception as exc:
        if old_config is None:
            config_file.unlink(missing_ok=True)
        else:
            _atomic_write_text(config_file, old_config)
        if old_raw is None:
            raw_file.unlink(missing_ok=True)
        else:
            _atomic_write_text(raw_file, old_raw)
        if reachable:
            _api_raw("PUT", "/configs", body=payload)
        raise RoutingError(f"Subscription update failed; files were rolled back: {exc}") from exc


def _install_subscription(raw, cfg, paths):
    with _publish_lock():
        return _install_subscription_unlocked(raw, cfg, paths)


def cmd_sub_pull(args):
    """Pull subscription and generate normalized config.yaml."""
    cfg = _load_mgr_config()
    paths = _get_paths()
    url = args.url or _cfg_value(cfg, "sub_url")
    if not url:
        print("Subscription URL is not configured.", file=sys.stderr)
        print(
            "Set it with: mihomo-mgr.py config-set --sub-url '<url>'", file=sys.stderr
        )
        sys.exit(1)

    paths["config_dir"].mkdir(parents=True, exist_ok=True)
    proxy_port = None
    if not getattr(args, "no_proxy", False):
        proxy_port = (
            _cfg_value(cfg, "proxy_http_port")
            or _cfg_value(cfg, "mixed_port")
            or DEFAULT_HTTP_PROXY_PORT
        )
    raw = _fetch_subscription(url, proxy_port=proxy_port)
    _install_subscription(raw, cfg, paths)

    print("Subscription pulled.")
    print(f"Raw cache: {paths['raw_sub_file']}")
    print(f"Generated config: {paths['config_file']}")
    print(f"Source: {_redact_url(url)}")



def cmd_sub_show(args):
    """Show subscription cache paths and status."""
    cfg = _load_mgr_config()
    paths = _get_paths()
    url = _cfg_value(cfg, "sub_url")
    print(f"Subscription URL: {_redact_url(url) if url else '-'}")
    print(f"Raw cache: {paths['raw_sub_file']} ({_file_status(paths['raw_sub_file'])})")
    print(
        f"Generated config: {paths['config_file']} ({_file_status(paths['config_file'])})"
    )


def cmd_sub_import(args):
    """Import a local YAML file as subscription and generate config.yaml."""
    cfg = _load_mgr_config()
    paths = _get_paths()
    src = Path(args.file).expanduser()
    if not src.exists():
        print(f"File not found: {src}", file=sys.stderr)
        sys.exit(1)

    raw = src.read_text(encoding="utf-8-sig", errors="replace")
    paths["config_dir"].mkdir(parents=True, exist_ok=True)
    _install_subscription(raw, cfg, paths)

    print("Subscription imported.")
    print(f"Raw cache: {paths['raw_sub_file']}")
    print(f"Generated config: {paths['config_file']}")
    print(f"Source: {src}")



def cmd_guard(args):
    """流量熔断器 CLI：status / release / report / test / trip / check。"""
    action = args.action or "status"
    cfg = _guard_cfg()
    state = _guard_load_state()
    db_path = _get_stats_db_path()

    if action == "status":
        if not cfg.get("enabled"):
            print("guard: 已禁用（mm config-set --guard-enabled true 开启）")
            return
        rolling = sum(b[1] for b in state.get("minute_buckets", []))
        used = _guard_month_used(db_path) or 0
        limit = cfg["monthly_quota_gb"] * GUARD_GB
        pct_str = f"（{used / limit * 100:.0f}%）" if limit > 0 else ""
        if state.get("disabled_until"):
            until = _guard_parse_until(state["disabled_until"])
            if until:
                remain = str(until - datetime.now()).split(".")[0]
                print(f"状态:     熔断中，剩余 {remain}"
                      f"（到期恢复 {state.get('saved_mode')}；解除: mm guard release）")
            else:
                state["disabled_until"] = None  # 损坏状态自愈
                print("状态:     正常监视（状态已自愈）")
        else:
            print("状态:     正常监视")
        print(f"滚动1h:   {_guard_fmt(rolling)} / 熔断阈值 {_guard_fmt(_guard_trip_bytes(cfg))}"
              f"（配额 {cfg['monthly_quota_gb']:g}GB × {cfg['trip_threshold_pct']:g}%）")
        if cfg["warn_threshold_pct"]:
            print(f"预警线:   {_guard_fmt(_guard_warn_bytes(cfg))}")
        print(f"月累计:   {_guard_fmt(used)} / {cfg['monthly_quota_gb']:g}GB{pct_str}")
        if state.get("trip_event"):
            print(f"最近事件: {state['trip_event']}")
        mode = (_guard_api("GET", "/configs") or {}).get("mode")
        print(f"mihomo:   mode={mode}")

    elif action == "release":
        if not state.get("disabled_until"):
            print("当前未处于熔断状态")
            return
        restore = _routing_safe_restore_mode(state.get("saved_mode") or "rule")
        _guard_api("PATCH", "/configs", {"mode": restore})
        event = state.get("trip_event")
        state["disabled_until"] = None
        state["trip_event"] = None
        state["warn_active"] = False
        _guard_save_state(state)
        _guard_notify("mm guard: 熔断已手动解除", f"已恢复 {restore} 模式（用户手动解除）")
        print(f"已解除熔断并恢复 {restore} 模式；事件报告: {event or '（无）'}")

    elif action == "report":
        event = state.get("trip_event")
        if not event or not Path(event).exists():
            events = sorted((_mgr_config_path().parent / "guard-events").glob("*.md"))
            event = str(events[-1]) if events else None
        if not event:
            print("暂无事件报告")
            return
        print(Path(event).read_text())

    elif action == "test":
        _guard_notify("mm guard: 通知通道测试", "如果你看到这条消息，说明通知通道工作正常。")
        print("已发送测试通知（文件日志 + 钉钉(若配置) + wall(若开启)）")

    elif action == "trip":
        rolling = sum(b[1] for b in state.get("minute_buckets", []))
        report = _guard_trip(cfg, state, db_path, "手动强制触发（测试）", rolling)
        _guard_save_state(state)
        print(f"已强制熔断；报告: {report}")

    elif action == "check":
        _guard_check(cfg, state, db_path)
        _guard_save_state(state)
        rolling = sum(b[1] for b in state.get("minute_buckets", []))
        print(f"检查完成 rolling={_guard_fmt(rolling)}")


def cmd_stats_daemon(args):
    """Manage traffic stats daemon."""
    action = args.action

    if action == "start":
        status = _traffic_daemon_status()
        if status["running"]:
            print(f"Traffic stats daemon is already running (pid {status['pid']})")
            return
        _start_traffic_daemon()
        print("Traffic stats daemon started")

    elif action == "stop":
        if _stop_traffic_daemon():
            print("Traffic stats daemon stopped")
        else:
            print("Traffic stats daemon is not running")

    elif action == "status":
        status = _traffic_daemon_status()
        if status["running"]:
            print(f"Traffic stats daemon is running (pid {status['pid']})")
        elif status.get("stale"):
            print("Traffic stats daemon is not running (stale PID file)")
        else:
            print("Traffic stats daemon is not running")


def cmd_stats(args):
    """Traffic statistics commands."""
    action = getattr(args, "stats_action", None)

    if action == "vacuum":
        db_path = _get_stats_db_path()
        cfg = _load_mgr_config()
        retention_days = cfg.get("stats", {}).get("retention_days", 180)
        _cleanup_old_data(db_path, retention_days)
        print(f"Cleaned up data older than {retention_days} days")
        return

    if action == "reset":
        db_path = _get_stats_db_path()
        if db_path.exists():
            db_path.unlink()
            _init_stats_db(db_path)
            print("Traffic stats database reset")
        else:
            print("No traffic stats database found")
        return

    if action == "idle":
        # 处理 idle 子命令
        if getattr(args, "idle_detail", False):
            status = _get_idle_status()
            if not status["enabled"]:
                print("Idle detection is disabled")
                return
            print("Idle Process Status")
            print("-" * 60)
            for proc in status["processes"]:
                idle_str = (
                    f"idle {proc['idle_hours']:.1f}h" if proc["idle"] else "active"
                )
                blocked_str = " [BLOCKED]" if proc["blocked"] else ""
                print(f"{proc['name']:<20}  {idle_str:<15}{blocked_str}")
        elif getattr(args, "idle_block", None):
            _block_process(args.idle_block)
            print(f"Blocked process: {args.idle_block}")
        elif getattr(args, "idle_unblock", None):
            _unblock_process(args.idle_unblock)
            print(f"Unblocked process: {args.idle_unblock}")
        elif getattr(args, "idle_whitelist_add", None):
            cfg = _load_mgr_config()
            whitelist = cfg.get("idle", {}).get("whitelist", [])
            if args.idle_whitelist_add not in whitelist:
                whitelist.append(args.idle_whitelist_add)
                cfg.setdefault("idle", {})["whitelist"] = whitelist
                _save_mgr_config(cfg)
                print(f"Added to whitelist: {args.idle_whitelist_add}")
        elif getattr(args, "idle_whitelist_remove", None):
            cfg = _load_mgr_config()
            whitelist = cfg.get("idle", {}).get("whitelist", [])
            if args.idle_whitelist_remove in whitelist:
                whitelist.remove(args.idle_whitelist_remove)
                cfg.setdefault("idle", {})["whitelist"] = whitelist
                _save_mgr_config(cfg)
                print(f"Removed from whitelist: {args.idle_whitelist_remove}")
        elif getattr(args, "idle_whitelist_list", False):
            cfg = _load_mgr_config()
            whitelist = cfg.get("idle", {}).get("whitelist", [])
            print("Idle Whitelist:")
            for proc in whitelist:
                print(f"  - {proc}")
        elif getattr(args, "idle_blacklist_add", None):
            _block_process(args.idle_blacklist_add)
            print(f"Added to blacklist and blocked: {args.idle_blacklist_add}")
        elif getattr(args, "idle_blacklist_remove", None):
            _unblock_process(args.idle_blacklist_remove)
            print(f"Removed from blacklist and unblocked: {args.idle_blacklist_remove}")
        elif getattr(args, "idle_blacklist_list", False):
            cfg = _load_mgr_config()
            blacklist = cfg.get("idle", {}).get("blacklist", [])
            print("Idle Blacklist:")
            for proc in blacklist:
                print(f"  - {proc}")
        else:
            # 默认显示摘要
            status = _get_idle_status()
            if not status["enabled"]:
                print("Idle detection is disabled")
                return
            idle_count = sum(1 for p in status["processes"] if p["idle"])
            blocked_count = sum(1 for p in status["processes"] if p["blocked"])
            print(f"Idle Detection: {idle_count} idle, {blocked_count} blocked")
            print("Use 'mm stats idle --idle-detail' for more information")
        return

    # 获取参数
    top_n = getattr(args, "top", 20)
    since = getattr(args, "since", "7d")
    node_mode = getattr(args, "node", False)
    rule_mode = getattr(args, "rule", False)
    json_mode = getattr(args, "json", False)
    trend = getattr(args, "trend", None)
    compare = getattr(args, "compare", None)

    db_path = _get_stats_db_path()
    if not db_path.exists():
        print("No traffic stats data yet")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 趋势分析
    if trend:
        if trend == "hourly":
            date = getattr(args, "date", datetime.now().strftime("%Y-%m-%d"))
            cursor.execute(
                """
                SELECT hour, SUM(upload_bytes), SUM(download_bytes), SUM(connection_count)
                FROM hourly_domain
                WHERE hour LIKE ?
                GROUP BY hour
                ORDER BY hour
            """,
                (f"{date}%",),
            )
            rows = cursor.fetchall()

            if json_mode:
                print(
                    json.dumps(
                        [
                            {
                                "hour": r[0],
                                "upload": r[1],
                                "download": r[2],
                                "connections": r[3],
                            }
                            for r in rows
                        ],
                        indent=2,
                    )
                )
            else:
                print(f"Hourly Traffic Trend ({date})")
                print("-" * 60)
                for hour, upload, download, conns in rows:
                    h = hour.split("T")[1] if "T" in hour else hour
                    print(
                        f"{h}:00  ↑{_fmt_bytes(upload):>8}  ↓{_fmt_bytes(download):>8}  {conns:>5} conns"
                    )

        elif trend == "daily":
            days = int(since.replace("d", "")) if since.endswith("d") else 7
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            cursor.execute(
                """
                SELECT date, total_upload_bytes, total_download_bytes, total_connections
                FROM daily_summary
                WHERE date >= ?
                ORDER BY date
            """,
                (start_date,),
            )
            rows = cursor.fetchall()

            if json_mode:
                print(
                    json.dumps(
                        [
                            {
                                "date": r[0],
                                "upload": r[1],
                                "download": r[2],
                                "connections": r[3],
                            }
                            for r in rows
                        ],
                        indent=2,
                    )
                )
            else:
                print(f"Daily Traffic Trend (last {days} days)")
                print("-" * 60)
                for date, upload, download, conns in rows:
                    print(
                        f"{date}  ↑{_fmt_bytes(upload):>8}  ↓{_fmt_bytes(download):>8}  {conns:>5} conns"
                    )

        elif trend == "monthly":
            cursor.execute(
                """
                SELECT month, total_upload_bytes, total_download_bytes, total_connections
                FROM monthly_summary
                ORDER BY month DESC
                LIMIT 12
            """
            )
            rows = cursor.fetchall()

            if json_mode:
                print(
                    json.dumps(
                        [
                            {
                                "month": r[0],
                                "upload": r[1],
                                "download": r[2],
                                "connections": r[3],
                            }
                            for r in rows
                        ],
                        indent=2,
                    )
                )
            else:
                print("Monthly Traffic Trend")
                print("-" * 60)
                for month, upload, download, conns in reversed(rows):
                    print(
                        f"{month}  ↑{_fmt_bytes(upload):>8}  ↓{_fmt_bytes(download):>8}  {conns:>5} conns"
                    )

        conn.close()
        return

    # 对比分析
    if compare:
        if compare == "daily":
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            cursor.execute(
                "SELECT total_upload_bytes, total_download_bytes, total_connections FROM daily_summary WHERE date = ?",
                (today,),
            )
            today_data = cursor.fetchone() or (0, 0, 0)

            cursor.execute(
                "SELECT total_upload_bytes, total_download_bytes, total_connections FROM daily_summary WHERE date = ?",
                (yesterday,),
            )
            yesterday_data = cursor.fetchone() or (0, 0, 0)

            if json_mode:
                print(
                    json.dumps(
                        {
                            "today": {
                                "upload": today_data[0],
                                "download": today_data[1],
                                "connections": today_data[2],
                            },
                            "yesterday": {
                                "upload": yesterday_data[0],
                                "download": yesterday_data[1],
                                "connections": yesterday_data[2],
                            },
                        },
                        indent=2,
                    )
                )
            else:
                print("Daily Comparison")
                print("-" * 60)
                print(f"Today ({today})")
                print(f"  Upload: {_fmt_bytes(today_data[0])}")
                print(f"  Download: {_fmt_bytes(today_data[1])}")
                print(f"  Connections: {today_data[2]}")
                print(f"\nYesterday ({yesterday})")
                print(f"  Upload: {_fmt_bytes(yesterday_data[0])}")
                print(f"  Download: {_fmt_bytes(yesterday_data[1])}")
                print(f"  Connections: {yesterday_data[2]}")

        elif compare == "monthly":
            this_month = datetime.now().strftime("%Y-%m")
            last_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime(
                "%Y-%m"
            )

            cursor.execute(
                "SELECT total_upload_bytes, total_download_bytes, total_connections FROM monthly_summary WHERE month = ?",
                (this_month,),
            )
            this_data = cursor.fetchone() or (0, 0, 0)

            cursor.execute(
                "SELECT total_upload_bytes, total_download_bytes, total_connections FROM monthly_summary WHERE month = ?",
                (last_month,),
            )
            last_data = cursor.fetchone() or (0, 0, 0)

            if json_mode:
                print(
                    json.dumps(
                        {
                            "this_month": {
                                "upload": this_data[0],
                                "download": this_data[1],
                                "connections": this_data[2],
                            },
                            "last_month": {
                                "upload": last_data[0],
                                "download": last_data[1],
                                "connections": last_data[2],
                            },
                        },
                        indent=2,
                    )
                )
            else:
                print("Monthly Comparison")
                print("-" * 60)
                print(f"This Month ({this_month})")
                print(f"  Upload: {_fmt_bytes(this_data[0])}")
                print(f"  Download: {_fmt_bytes(this_data[1])}")
                print(f"  Connections: {this_data[2]}")
                print(f"\nLast Month ({last_month})")
                print(f"  Upload: {_fmt_bytes(last_data[0])}")
                print(f"  Download: {_fmt_bytes(last_data[1])}")
                print(f"  Connections: {last_data[2]}")

        conn.close()
        return

    # 排行查询
    days = int(since.replace("d", "")) if since.endswith("d") else 7
    start_hour = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H")

    if node_mode:
        cursor.execute(
            """
            SELECT node, SUM(upload_bytes), SUM(download_bytes), SUM(connection_count)
            FROM hourly_node
            WHERE hour >= ?
            GROUP BY node
            ORDER BY SUM(upload_bytes + download_bytes) DESC
            LIMIT ?
        """,
            (start_hour, top_n),
        )
        rows = cursor.fetchall()
        title = f"Node Traffic Ranking (last {days} days, top {top_n})"
        key_name = "node"
    elif rule_mode:
        cursor.execute(
            """
            SELECT rule, SUM(upload_bytes), SUM(download_bytes), SUM(connection_count)
            FROM hourly_rule
            WHERE hour >= ?
            GROUP BY rule
            ORDER BY SUM(upload_bytes + download_bytes) DESC
            LIMIT ?
        """,
            (start_hour, top_n),
        )
        rows = cursor.fetchall()
        title = f"Rule Traffic Ranking (last {days} days, top {top_n})"
        key_name = "rule"
    else:
        cursor.execute(
            """
            SELECT domain, SUM(upload_bytes), SUM(download_bytes), SUM(connection_count)
            FROM hourly_domain
            WHERE hour >= ?
            GROUP BY domain
            ORDER BY SUM(upload_bytes + download_bytes) DESC
            LIMIT ?
        """,
            (start_hour, top_n),
        )
        rows = cursor.fetchall()
        title = f"Domain Traffic Ranking (last {days} days, top {top_n})"
        key_name = "domain"

    if json_mode:
        print(
            json.dumps(
                [
                    {
                        key_name: r[0],
                        "upload": r[1],
                        "download": r[2],
                        "connections": r[3],
                    }
                    for r in rows
                ],
                indent=2,
            )
        )
    elif getattr(args, "export_csv", False):
        # 4.12 CSV export
        import csv

        writer = csv.writer(sys.stdout)
        writer.writerow([key_name, "upload_bytes", "download_bytes", "connections"])
        for r in rows:
            writer.writerow(r)
    else:
        # 4.9 ASCII bar chart ranking
        print(title)
        print("-" * 60)
        max_total = max((r[1] + r[2] for r in rows), default=1)
        for name, upload, download, conns in rows:
            total = upload + download
            bar = _render_bar(total, max_total, 15)
            print(
                f"{name:<25} {bar} ↑{_fmt_bytes(upload):>8} ↓{_fmt_bytes(download):>8}"
            )

    conn.close()


def cmd_stats_idle(args):
    """Idle detection commands."""
    action = getattr(args, "idle_action", None)

    if action == "detail":
        status = _get_idle_status()
        if not status["enabled"]:
            print("Idle detection is disabled")
            return

        print("Idle Process Status")
        print("-" * 60)
        for proc in status["processes"]:
            idle_str = f"idle {proc['idle_hours']:.1f}h" if proc["idle"] else "active"
            blocked_str = " [BLOCKED]" if proc["blocked"] else ""
            print(f"{proc['name']:<20}  {idle_str:<15}{blocked_str}")

    elif action == "block":
        process_name = getattr(args, "process", None)
        if not process_name:
            print("Error: process name required", file=sys.stderr)
            sys.exit(1)
        _block_process(process_name)
        print(f"Blocked process: {process_name}")

    elif action == "unblock":
        process_name = getattr(args, "process", None)
        if not process_name:
            print("Error: process name required", file=sys.stderr)
            sys.exit(1)
        _unblock_process(process_name)
        print(f"Unblocked process: {process_name}")

    elif action == "whitelist":
        wl_action = getattr(args, "whitelist_action", None)
        process_name = getattr(args, "process", None)

        cfg = _load_mgr_config()
        whitelist = cfg.get("idle", {}).get("whitelist", [])

        if wl_action == "add" and process_name:
            if process_name not in whitelist:
                whitelist.append(process_name)
                cfg.setdefault("idle", {})["whitelist"] = whitelist
                _save_mgr_config(cfg)
                print(f"Added to whitelist: {process_name}")
            else:
                print(f"Already in whitelist: {process_name}")

        elif wl_action == "remove" and process_name:
            if process_name in whitelist:
                whitelist.remove(process_name)
                cfg.setdefault("idle", {})["whitelist"] = whitelist
                _save_mgr_config(cfg)
                print(f"Removed from whitelist: {process_name}")
            else:
                print(f"Not in whitelist: {process_name}")

        elif wl_action == "list":
            print("Idle Whitelist:")
            for proc in whitelist:
                print(f"  - {proc}")

    elif action == "blacklist":
        bl_action = getattr(args, "blacklist_action", None)
        process_name = getattr(args, "process", None)

        cfg = _load_mgr_config()
        blacklist = cfg.get("idle", {}).get("blacklist", [])

        if bl_action == "add" and process_name:
            if process_name not in blacklist:
                blacklist.append(process_name)
                cfg.setdefault("idle", {})["blacklist"] = blacklist
                _save_mgr_config(cfg)
                _block_process(process_name)
                print(f"Added to blacklist and blocked: {process_name}")
            else:
                print(f"Already in blacklist: {process_name}")

        elif bl_action == "remove" and process_name:
            if process_name in blacklist:
                blacklist.remove(process_name)
                cfg.setdefault("idle", {})["blacklist"] = blacklist
                _save_mgr_config(cfg)
                _unblock_process(process_name)
                print(f"Removed from blacklist and unblocked: {process_name}")
            else:
                print(f"Not in blacklist: {process_name}")

        elif bl_action == "list":
            print("Idle Blacklist:")
            for proc in blacklist:
                print(f"  - {proc}")

    else:
        # Default: show summary
        status = _get_idle_status()
        if not status["enabled"]:
            print("Idle detection is disabled")
            return

        idle_count = sum(1 for p in status["processes"] if p["idle"])
        blocked_count = sum(1 for p in status["processes"] if p["blocked"])

        print(f"Idle Detection: {idle_count} idle, {blocked_count} blocked")
        print("Use 'mm stats idle --detail' for more information")


# ── Idle Detection ──────────────────────────────────────────────────────────


def _check_process_idle(process_name: str, cfg: dict) -> "tuple[bool, float]":
    """Check if a process is idle. Returns (is_idle, idle_hours)."""
    idle_cfg = cfg.get("idle", {}).get("monitored", {}).get(process_name, {})
    if not idle_cfg:
        return False, 0.0

    idle_check = idle_cfg.get("idle_check")
    threshold = idle_cfg.get("threshold_hours", 2)

    if idle_check == "history_jsonl":
        # Check codex history.jsonl
        history_file = Path(
            idle_cfg.get("idle_file", "~/.codex/history.jsonl")
        ).expanduser()
        if not history_file.exists():
            return True, 999.0  # No history = idle

        try:
            # Read last line
            with open(history_file, "rb") as f:
                f.seek(0, 2)  # Seek to end
                file_size = f.tell()
                if file_size == 0:
                    return True, 999.0

                # Read last 1KB
                read_size = min(1024, file_size)
                f.seek(-read_size, 2)
                lines = f.read().decode("utf-8", errors="ignore").split("\n")

                # Find last non-empty line
                for line in reversed(lines):
                    if line.strip():
                        try:
                            data = json.loads(line)
                            ts = data.get("ts", 0)
                            if ts > 0:
                                idle_hours = (time.time() - ts) / 3600
                                return idle_hours >= threshold, idle_hours
                        except json.JSONDecodeError:
                            pass
                        break
        except Exception:
            pass

    elif idle_check == "session_mtime":
        # Check opencode session files
        session_dir = Path(
            idle_cfg.get("idle_dir", "~/.local/state/opencode/")
        ).expanduser()
        if not session_dir.exists():
            return True, 999.0

        try:
            # Find most recent session file
            latest_mtime = 0
            for session_file in session_dir.glob("*.jsonl"):
                mtime = session_file.stat().st_mtime
                latest_mtime = max(latest_mtime, mtime)

            if latest_mtime == 0:
                return True, 999.0

            idle_hours = (time.time() - latest_mtime) / 3600
            return idle_hours >= threshold, idle_hours
        except Exception:
            pass

    elif idle_check == "heartbeat":
        # 5.4 心跳模式检测（兜底）：检查连接间隔变异系数
        # 如果连接间隔非常规律（变异系数 < 0.1）且每次下载 < 1KB，认为是心跳
        try:
            from datetime import datetime, timedelta

            db_path = _get_stats_db_path()
            if not db_path.exists():
                return False, 0.0

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # 获取最近1小时的连接记录
            one_hour_ago = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
            cursor.execute(
                """
                SELECT hour, download_bytes, connection_count
                FROM hourly_domain
                WHERE hour >= ? AND domain LIKE ?
                ORDER BY hour
            """,
                (one_hour_ago, f"%{process_name}%"),
            )

            rows = cursor.fetchall()
            conn.close()

            if len(rows) < 3:  # 需要至少3个数据点
                return False, 0.0

            # 计算连接间隔
            intervals = []
            for i in range(1, len(rows)):
                hour1 = datetime.fromisoformat(rows[i - 1][0].replace("T", " "))
                hour2 = datetime.fromisoformat(rows[i][0].replace("T", " "))
                interval = (hour2 - hour1).total_seconds() / 60  # 分钟
                intervals.append(interval)

            if not intervals:
                return False, 0.0

            # 计算变异系数（标准差/平均值）
            import statistics

            mean_interval = statistics.mean(intervals)
            if mean_interval == 0:
                return False, 0.0

            std_interval = statistics.stdev(intervals) if len(intervals) > 1 else 0
            cv = std_interval / mean_interval  # 变异系数

            # 检查是否是小流量心跳（每次 < 1KB）
            total_downloads = sum(row[1] for row in rows)
            total_connections = sum(row[2] for row in rows)

            if total_connections == 0:
                return False, 0.0

            avg_download_per_conn = total_downloads / total_connections

            # 如果变异系数 < 0.1 且平均每次下载 < 1KB，认为是心跳
            if cv < 0.1 and avg_download_per_conn < 1024:
                # 使用最早记录的时间作为空闲开始时间
                first_hour = datetime.fromisoformat(rows[0][0].replace("T", " "))
                idle_hours = (datetime.now() - first_hour).total_seconds() / 3600
                return idle_hours >= threshold, idle_hours

        except Exception:
            pass

    return False, 0.0


def _get_idle_status() -> dict:
    """Get idle status for all monitored processes."""
    cfg = _load_mgr_config()

    if not cfg.get("idle", {}).get("enabled", True):
        return {"enabled": False, "processes": []}

    monitored = cfg.get("idle", {}).get("monitored", {})
    whitelist = cfg.get("idle", {}).get("whitelist", [])
    blacklist = cfg.get("idle", {}).get("blacklist", [])

    processes = []
    for proc_name in monitored:
        if proc_name in whitelist:
            continue

        is_idle, idle_hours = _check_process_idle(proc_name, cfg)
        processes.append(
            {
                "name": proc_name,
                "idle": is_idle,
                "idle_hours": idle_hours,
                "blocked": proc_name in blacklist,
            }
        )

    return {"enabled": True, "processes": processes}


def _block_process(process_name: str):
    """Block a process by adding PROCESS-NAME rule."""
    cfg = _load_mgr_config()
    blacklist = cfg.get("idle", {}).get("blacklist", [])

    if process_name not in blacklist:
        blacklist.append(process_name)
        cfg.setdefault("idle", {})["blacklist"] = blacklist
        _save_mgr_config(cfg)

    # Update overlay
    overlay_content = "payload:\n"
    for proc in blacklist:
        overlay_content += f"  - PROCESS-NAME,{proc}\n"

    _write_overlay("blocked-processes.yaml", overlay_content)
    _reapply_overlays()

    # Record event
    _record_alert("block", f"Blocked process: {process_name}")


def _unblock_process(process_name: str):
    """Unblock a process by removing PROCESS-NAME rule."""
    cfg = _load_mgr_config()
    blacklist = cfg.get("idle", {}).get("blacklist", [])

    if process_name in blacklist:
        blacklist.remove(process_name)
        cfg.setdefault("idle", {})["blacklist"] = blacklist
        _save_mgr_config(cfg)

    # Update overlay
    if blacklist:
        overlay_content = "payload:\n"
        for proc in blacklist:
            overlay_content += f"  - PROCESS-NAME,{proc}\n"
        _write_overlay("blocked-processes.yaml", overlay_content)
    else:
        _delete_overlay("blocked-processes.yaml")

    _reapply_overlays()

    # Record event
    _record_alert("unblock", f"Unblocked process: {process_name}")


_IDLE_COOLDOWN_FILE = Path("~/.config/mihomo-mgr/idle-cooldown.json").expanduser()


def _read_idle_cooldown() -> dict:
    """Read idle cooldown map: {process_name: last_alert_timestamp}."""
    try:
        if _IDLE_COOLDOWN_FILE.exists():
            return json.loads(_IDLE_COOLDOWN_FILE.read_text())
    except Exception:
        pass
    return {}


def _write_idle_cooldown(data: dict):
    """Write idle cooldown map."""
    try:
        _IDLE_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _IDLE_COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _run_idle_check():
    """Daemon idle check: auto-block idle processes, auto-unblock active ones.

    Called from _check_idle_tick() every 5 minutes.
    Implements 5.16: idle detection integrated into daemon main loop.
    """
    status = _get_idle_status()
    if not status.get("enabled"):
        return

    cfg = _load_mgr_config()
    cooldown_minutes = cfg.get("idle", {}).get("cooldown_minutes", 30)
    cooldown_seconds = cooldown_minutes * 60
    cooldown_map = _read_idle_cooldown()
    now = time.time()

    for proc in status.get("processes", []):
        name = proc["name"]
        is_idle = proc["idle"]
        is_blocked = proc["blocked"]

        if is_idle and not is_blocked:
            # Process is idle and not yet blocked → block it
            last_alert = cooldown_map.get(name, 0)
            if now - last_alert < cooldown_seconds:
                continue  # cooldown active, skip

            _block_process(name)
            _send_notification(
                "空闲进程阻断",
                f"进程 {name} 已空闲 {proc['idle_hours']:.1f} 小时，已自动阻断",
            )
            cooldown_map[name] = now
            _write_idle_cooldown(cooldown_map)

        elif not is_idle and is_blocked:
            # Process was blocked but is now active → unblock it
            _unblock_process(name)
            _send_notification(
                "空闲进程恢复",
                f"进程 {name} 已恢复活动，已自动解除阻断",
            )
            cooldown_map.pop(name, None)
            _write_idle_cooldown(cooldown_map)


def _record_alert(alert_type: str, message: str):
    """Record an alert event."""
    alerts_file = Path("~/.config/mihomo-mgr/alerts.jsonl").expanduser()
    alerts_file.parent.mkdir(parents=True, exist_ok=True)

    alert = {
        "timestamp": datetime.now().isoformat(),
        "type": alert_type,
        "message": message,
    }

    with open(alerts_file, "a") as f:
        f.write(json.dumps(alert) + "\n")


def _send_notification(title: str, message: str):
    """Send notification via configured channels."""
    cfg = _load_mgr_config()
    channels = cfg.get("notify", {}).get("channels", ["file"])

    # Always write to file
    _record_alert("notification", f"{title}: {message}")

    # DingTalk notification
    if "dingtalk" in channels:
        webhook = cfg.get("notify", {}).get("dingtalk", {}).get("webhook")
        if webhook:
            try:
                payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": f"## {title}\n\n{message}",
                    },
                }
                req = urllib.request.Request(
                    webhook,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                print(f"DingTalk notification failed: {e}", file=sys.stderr)

    # Terminal notification (if SSH session detected)
    if "terminal" in channels:
        try:
            # Check if tmux is available
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if result.returncode == 0:
                # Send message to tmux
                subprocess.run(
                    ["tmux", "display-message", f"[mihomo-mgr] {title}: {message}"],
                    timeout=1,
                )
        except Exception:
            pass


def cmd_stats_large(args):
    """Large download detection commands."""
    action = getattr(args, "large_action", None)

    db_path = _get_stats_db_path()
    if not db_path.exists():
        print("No traffic stats data yet")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    if action == "list":
        since = getattr(args, "since", "7d")
        days = int(since.replace("d", "")) if since.endswith("d") else 7
        start_date = (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )

        cursor.execute(
            """
            SELECT timestamp, domain, process, download_bytes,
                   source_ip, destination_ip, duration_seconds, rule
            FROM large_downloads
            WHERE timestamp >= ?
            ORDER BY download_bytes DESC
            LIMIT 50
        """,
            (start_date,),
        )

        rows = cursor.fetchall()

        if not rows:
            print(f"No large downloads (>30MB) in the last {days} days")
        else:
            print(f"Large Downloads (>30MB) - Last {days} days")
            print("-" * 100)
            print(
                f"{'Time':<20} {'Domain':<25} {'Process':<15} {'Size':<10} {'Duration':<10}"
            )
            print("-" * 100)

            for row in rows:
                ts, domain, process, size, src_ip, dst_ip, duration, rule = row
                time_str = ts[:16].replace("T", " ")
                duration_str = f"{duration:.1f}s" if duration else "-"
                print(
                    f"{time_str:<20} {domain[:24]:<25} {process[:14]:<15} {_fmt_bytes(size):<10} {duration_str:<10}"
                )

            print(f"\nTotal: {len(rows)} large downloads")

    elif action == "detail":
        download_id = getattr(args, "id", None)
        if not download_id:
            print("Error: download ID required", file=sys.stderr)
            sys.exit(1)

        cursor.execute("SELECT * FROM large_downloads WHERE id = ?", (download_id,))
        row = cursor.fetchone()

        if not row:
            print(f"Download ID {download_id} not found")
        else:
            print(f"Large Download Details - ID: {download_id}")
            print("-" * 60)
            print(f"Timestamp:      {row[1]}")
            print(f"Domain:         {row[2]}")
            print(f"Node:           {row[3]}")
            print(f"Process:        {row[4]}")
            print(f"Process Path:   {row[5]}")
            print(f"Source IP:      {row[6]}")
            print(f"Source Port:    {row[7]}")
            print(f"Destination IP: {row[8]}")
            print(f"Dest Port:      {row[9]}")
            print(f"Download Size:  {_fmt_bytes(row[10])}")
            print(f"Duration:       {row[11]:.1f}s" if row[11] else "Duration:       -")
            print(f"Rule:           {row[12]}")

    elif action == "summary":
        since = getattr(args, "since", "30d")
        days = int(since.replace("d", "")) if since.endswith("d") else 30
        start_date = (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )

        cursor.execute(
            """
            SELECT COUNT(*), SUM(download_bytes), AVG(download_bytes),
                   MAX(download_bytes), COUNT(DISTINCT domain), COUNT(DISTINCT process)
            FROM large_downloads
            WHERE timestamp >= ?
        """,
            (start_date,),
        )

        row = cursor.fetchone()
        if row and row[0] > 0:
            count, total, avg, max_size, domains, processes = row
            print(f"Large Download Summary - Last {days} days")
            print("-" * 60)
            print(f"Total Downloads:    {count}")
            print(f"Total Data:         {_fmt_bytes(total)}")
            print(f"Average Size:       {_fmt_bytes(avg)}")
            print(f"Largest Download:   {_fmt_bytes(max_size)}")
            print(f"Unique Domains:     {domains}")
            print(f"Unique Processes:   {processes}")

            cursor.execute(
                """
                SELECT domain, COUNT(*), SUM(download_bytes)
                FROM large_downloads
                WHERE timestamp >= ?
                GROUP BY domain
                ORDER BY SUM(download_bytes) DESC
                LIMIT 5
            """,
                (start_date,),
            )

            print("\nTop Domains by Data:")
            for domain, cnt, size in cursor.fetchall():
                print(f"  {domain:<30} {cnt:>3} downloads  {_fmt_bytes(size)}")
        else:
            print(f"No large downloads in the last {days} days")

    conn.close()


# ── Helpers ──────────────────────────────────────────────────────────


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _render_bar(value, max_value, width=20):
    """Render an ASCII bar chart bar."""
    if max_value <= 0:
        return " " * width
    filled = int(value / max_value * width)
    filled = max(0, min(width, filled))
    return "\u2588" * filled + "\u2591" * (width - filled)


def _urlencode(s):
    return urllib.parse.quote(s, safe="")


def _print_process_status():
    paths = _get_paths()
    pid = _read_pid(paths["pid_file"])
    discovered = _find_mihomo_processes()
    running = bool((pid and _is_pid_running(pid)) or discovered)
    display_pid = pid or (discovered[0]["pid"] if discovered else None)
    print("Process:")
    print(f"  Running: {'yes' if running else 'no'}")
    print(f"  PID: {display_pid if display_pid else '-'}")
    if discovered:
        print("  Discovered:")
        for item in discovered:
            print(f"    {item['pid']}: {item['cmd']}")
    missing = _missing_db_files(DEFAULT_DB_FILES)
    if missing:
        print(f"  DB files: missing {', '.join(missing)}")
    else:
        print("  DB files: ok")


def _mgr_config_path():
    return Path(
        os.environ.get("MIHOMO_MGR_CONFIG", DEFAULT_MGR_CONFIG_PATH)
    ).expanduser()


_mgr_config_cache = None


def _secure_mgr_directory(path):
    parent = path.parent
    if parent.is_symlink():
        raise RuntimeError("unsafe private config directory")
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("unsafe private config directory")
    parent.chmod(0o700)


def _secure_mgr_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise RuntimeError("unsafe private config file")
    path.chmod(0o600)


def _atomic_mgr_config(path, data):
    _secure_mgr_directory(path)
    fd, name = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            _secure_mgr_file(path)
        os.replace(name, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _load_mgr_config():
    global _mgr_config_cache
    if _mgr_config_cache is not None:
        return _mgr_config_cache
    path = _mgr_config_path()
    if path.exists() or path.is_symlink():
        _secure_mgr_directory(path)
        _secure_mgr_file(path)

    # Migration: config.json -> config.yaml
    if not path.exists():
        json_path = path.with_suffix(".json")
        if json_path.exists():
            try:
                _secure_mgr_directory(json_path)
                _secure_mgr_file(json_path)
                json_data = json.loads(_strip_json_comments(json_path.read_text()))
                if yaml:
                    _atomic_mgr_config(
                        path, yaml.safe_dump(
                            json_data, default_flow_style=False, allow_unicode=True
                        )
                    )
                else:
                    _atomic_mgr_config(path, json.dumps(json_data, indent=2, sort_keys=True) + "\n")
                json_path.rename(path.with_suffix(".json.bak"))
            except Exception:
                pass

    try:
        if yaml:
            _mgr_config_cache = yaml.safe_load(path.read_text()) or {}
        else:
            _mgr_config_cache = json.loads(_strip_json_comments(path.read_text()))
        _mgr_config_cache = _validate_config(_mgr_config_cache)
    except (FileNotFoundError, json.JSONDecodeError):
        _mgr_config_cache = {}
    return _mgr_config_cache


def _invalidate_config_cache():
    global _mgr_config_cache
    _mgr_config_cache = None


def _cfg_value(cfg, key, default=None):
    value = cfg.get(key)
    return value if value not in (None, "") else default


def _save_mgr_config(cfg):
    path = _mgr_config_path()
    if yaml:
        _atomic_mgr_config(path, yaml.safe_dump(cfg, default_flow_style=False, allow_unicode=True))
    else:
        _atomic_mgr_config(path, json.dumps(cfg, indent=2, sort_keys=True) + "\n")


# ── Local routing policy ───────────────────────────────────────────

_ROUTING_TYPES = {
    "domain": "DOMAIN",
    "domain-suffix": "DOMAIN-SUFFIX",
    "ip-cidr": "IP-CIDR",
    "ip-cidr6": "IP-CIDR6",
    "process-name": "PROCESS-NAME",
}
_ROUTING_LIST_ALIASES = {
    "direct": "direct",
    "whitelist": "direct",
    "proxy": "proxy",
    "blacklist": "proxy",
}


class RoutingError(ValueError):
    """A user-facing local routing policy error."""


def _routing_path():
    """Keep policy independent from the replaceable mihomo config directory."""
    return _mgr_config_path().parent / "routing.json"


def _gfwlist_path():
    return _mgr_config_path().parent / "gfwlist.json"


def _publish_lock_path():
    return _mgr_config_path().parent / "publish.lock"


@contextmanager
def _publish_lock():
    """Serialize routing/cache/config publication across mm processes."""
    path = _publish_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _time_iso(timestamp=None):
    value = datetime.fromtimestamp(timestamp if timestamp is not None else time.time())
    return value.isoformat(timespec="seconds")


def _parse_time(value):
    try:
        return datetime.fromisoformat(value).timestamp() if value else None
    except (TypeError, ValueError):
        return None


def _gfwlist_default_state():
    return {
        "version": 1,
        "source_url": DEFAULT_GFWLIST_URL,
        "enabled": False,
        "interval_hours": 24,
        "last_success": None,
        "last_attempt": None,
        "next_retry": None,
        "error": None,
        "content_sha256": None,
        "direct": [],
        "proxy": [],
        "accepted_count": 0,
        "skipped_count": 0,
        "skipped_reasons": {},
        "skipped_samples": {},
        "conservative_exception_count": 0,
        "conservative_reasons": {},
        "conservative_samples": {},
    }


def _gfwlist_load():
    path = _gfwlist_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return _gfwlist_default_state()
    except json.JSONDecodeError as exc:
        raise RoutingError(f"Invalid GFWList cache JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RoutingError("Unsupported GFWList cache format")
    if data.get("source_url") != DEFAULT_GFWLIST_URL:
        raise RoutingError("GFWList cache source URL does not match the fixed source")
    try:
        interval = int(data.get("interval_hours", 24))
    except (TypeError, ValueError) as exc:
        raise RoutingError("GFWList interval_hours must be an integer") from exc
    if interval < 0:
        raise RoutingError("GFWList interval_hours cannot be negative")
    data["interval_hours"] = interval
    for key in ("direct", "proxy"):
        if not isinstance(data.get(key, []), list):
            raise RoutingError(f"gfwlist.{key} must be a list")
        data[key] = [_routing_validate_entry(item) for item in data.get(key, [])]
        if any(item["type"] not in ("domain", "domain-suffix") for item in data[key]):
            raise RoutingError(f"gfwlist.{key} only supports domain entries")
    return {**_gfwlist_default_state(), **data}


def _gfwlist_save(state):
    path = _gfwlist_path()
    _atomic_write_text(
        path, json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def _gfwlist_is_due(state, now=None):
    now = time.time() if now is None else now
    if not state.get("enabled") or int(state.get("interval_hours", 0)) == 0:
        return False
    retry = _parse_time(state.get("next_retry"))
    if retry and now < retry:
        return False
    success = _parse_time(state.get("last_success"))
    if success is None:
        return True
    return now >= success + int(state["interval_hours"]) * 3600


def _gfwlist_fetch():
    """Fetch the fixed source directly with strict size/time bounds."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        DEFAULT_GFWLIST_URL,
        headers={"User-Agent": f"mihomo-mgr/{VERSION}", "Accept": "text/plain"},
    )
    try:
        with opener.open(request, timeout=GFWLIST_TIMEOUT) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > GFWLIST_MAX_BYTES:
                raise RoutingError("GFWList response exceeds 5 MiB")
            raw = response.read(GFWLIST_MAX_BYTES + 1)
    except RoutingError:
        raise
    except Exception as exc:
        raise RoutingError(f"GFWList download failed: {exc}") from exc
    if len(raw) > GFWLIST_MAX_BYTES:
        raise RoutingError("GFWList response exceeds 5 MiB")
    return raw


def _gfw_domain(value):
    value = value.strip().strip(".")
    try:
        value = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise RoutingError(f"Invalid GFWList domain: {value}") from exc
    if len(value) > 253 or len(value.split(".")) < 2:
        raise RoutingError(f"Invalid GFWList domain: {value}")
    if any(
        not label
        or len(label) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in value.split(".")
    ):
        raise RoutingError(f"Invalid GFWList domain: {value}")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise RoutingError(f"IP literals are not accepted as GFWList domains: {value}")


def _gfw_skip(skipped_reasons, skipped_samples, reason, line):
    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
    samples = skipped_samples.setdefault(reason, [])
    if len(samples) < 5:
        samples.append(line[:300])


def _gfw_conservative_exception(line):
    """Return a safe DIRECT suffix for the narrow exception forms we can bound."""
    if line.startswith("||*."):
        value = line[4:-1] if line.endswith("^") else line[4:]
        if not any(char in value for char in "*/|?"):
            return _gfw_domain(value), "conservative-exception-wildcard"
    if line.startswith("/"):
        # Accept only the exact bounded shape present in the upstream source.
        # A mere terminal-looking suffix is insufficient because a top-level
        # alternation could leave another branch unrestricted.
        match = re.fullmatch(
            r"/\^https\?:\\/\\/\(\?=\.\*\?\((?:[A-Za-z0-9-]+\|)*[A-Za-z0-9-]+\)\)"
            r"\[a-z0-9\.\-\]\+((?:\\\.[A-Za-z0-9-]+){2,})\$/?",
            line,
        )
        if match:
            domain = match.group(1).replace("\\.", ".").lstrip(".")
            return _gfw_domain(domain), "conservative-exception-fixed-suffix"
    raise RoutingError(
        f"Unsupported GFWList exception cannot be represented safely: {line[:200]}"
    )


def _gfwlist_parse(raw):
    """Decode an AutoProxy GFWList into conservative domain-only entries."""
    if not raw or raw.lstrip().lower().startswith((b"<html", b"<!doctype")):
        raise RoutingError("GFWList response is empty or HTML")
    compact = re.sub(rb"\s+", b"", raw)
    try:
        decoded = base64.b64decode(compact, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RoutingError("GFWList response is not valid base64 UTF-8") from exc
    if decoded.lstrip().lower().startswith(("<html", "<!doctype")):
        raise RoutingError("Decoded GFWList is HTML")
    lines = decoded.splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    if not re.fullmatch(r"\[AutoProxy(?:\s+[^\]]+)?\]", first, re.IGNORECASE):
        raise RoutingError("GFWList AutoProxy header is missing")

    direct = []
    proxy = []
    seen_direct = set()
    seen_proxy = set()
    skipped_reasons = {}
    skipped_samples = {}
    conservative_reasons = {}
    conservative_samples = {}
    conservative_count = 0
    for original in lines:
        line = original.strip()
        if not line or line.startswith("!") or line.startswith("["):
            continue
        is_exception = line.startswith("@@")
        rule = line[2:] if is_exception else line
        entry = None
        reason = None
        match = re.fullmatch(r"\|\|([^*?/|^]+)\^?", rule)
        if match:
            try:
                entry = {"type": "domain-suffix", "value": _gfw_domain(match.group(1))}
            except RoutingError:
                reason = "invalid-domain"
        elif re.fullmatch(r"[^*?/|^:\s]+", rule):
            try:
                entry = {"type": "domain", "value": _gfw_domain(rule)}
            except RoutingError:
                reason = "invalid-domain"
        elif is_exception:
            domain, reason = _gfw_conservative_exception(rule)
            entry = {"type": "domain-suffix", "value": domain}
            conservative_count += 1
        else:
            if rule.startswith("/") and rule.endswith("/"):
                reason = "regex"
            elif "*" in rule:
                reason = "wildcard"
            elif "://" in rule or "/" in rule:
                reason = "url-or-path"
            else:
                reason = "unsupported"
        if entry is None:
            if is_exception:
                raise RoutingError(
                    f"Unsupported GFWList exception cannot be represented safely: {line[:200]}"
                )
            _gfw_skip(skipped_reasons, skipped_samples, reason or "unsupported", line)
            continue
        key = (entry["type"], entry["value"])
        destination = direct if is_exception else proxy
        seen = seen_direct if is_exception else seen_proxy
        if key not in seen:
            destination.append(entry)
            seen.add(key)
        if reason:
            _gfw_skip(conservative_reasons, conservative_samples, reason, line)

    if not proxy:
        raise RoutingError("GFWList contains no supported proxy entries")
    return {
        "direct": direct,
        "proxy": proxy,
        "accepted_count": len(direct) + len(proxy),
        "skipped_count": sum(skipped_reasons.values()),
        "skipped_reasons": skipped_reasons,
        "skipped_samples": skipped_samples,
        "conservative_exception_count": conservative_count,
        "conservative_reasons": conservative_reasons,
        "conservative_samples": conservative_samples,
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _routing_has_active():
    policy = _routing_load()
    return bool(policy and policy.get("enabled") and policy.get("active"))


def _guard_is_tripped():
    try:
        until = _guard_parse_until(_guard_load_state().get("disabled_until"))
        return bool(until and until > datetime.now())
    except Exception:
        return False


def _routing_safe_restore_mode(mode):
    return "rule" if mode == "global" and _routing_has_active() else mode


def _routing_load(required=False):
    path = _routing_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        if required:
            raise RoutingError(f"Routing policy is not initialized: {path}")
        return None
    except json.JSONDecodeError as exc:
        raise RoutingError(f"Invalid routing policy JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RoutingError("Unsupported routing policy format")
    for key in ("direct", "proxy"):
        if not isinstance(data.get(key, []), list):
            raise RoutingError(f"routing.{key} must be a list")
        data[key] = [_routing_validate_entry(item) for item in data.get(key, [])]
    if not isinstance(data.get("proxy_target"), str) or not data["proxy_target"].strip():
        raise RoutingError("routing.proxy_target must be a non-empty name")
    active = data.get("active")
    if active is not None:
        if not isinstance(active, dict):
            raise RoutingError("routing.active must be an object")
        active["proxy_target"] = str(active.get("proxy_target", "")).strip()
        if not active["proxy_target"]:
            raise RoutingError("routing.active.proxy_target must be a non-empty name")
        for key in ("direct", "proxy"):
            if not isinstance(active.get(key, []), list):
                raise RoutingError(f"routing.active.{key} must be a list")
            active[key] = [_routing_validate_entry(item) for item in active.get(key, [])]
    return data


def _routing_validate_entry(entry_type, value=None):
    if value is None:
        if not isinstance(entry_type, dict):
            raise RoutingError("Routing entries must be objects")
        value = entry_type.get("value")
        entry_type = entry_type.get("type")
    entry_type = str(entry_type or "").lower()
    value = str(value or "").strip()
    if entry_type not in _ROUTING_TYPES:
        raise RoutingError(f"Unsupported routing type: {entry_type or '-'}")
    if not value or any(char in value for char in (",", "\n", "\r")):
        raise RoutingError("Routing values cannot be empty or contain commas/newlines")
    if entry_type in ("domain", "domain-suffix"):
        value = value.lower().rstrip(".")
        if not value or any(char.isspace() for char in value):
            raise RoutingError("Domain values cannot contain whitespace")
    elif entry_type in ("ip-cidr", "ip-cidr6"):
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise RoutingError(f"Invalid CIDR: {value}") from exc
        expected_version = 4 if entry_type == "ip-cidr" else 6
        if network.version != expected_version:
            raise RoutingError(f"{entry_type} requires IPv{expected_version}: {value}")
        value = str(network)
    return {"type": entry_type, "value": value}


def _routing_save(policy):
    path = _routing_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(policy, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".routing.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(payload)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _routing_block_rules():
    """Only preserve the safety PROCESS-NAME rejects from the idle blocker."""
    if yaml is None:
        raise RoutingError("PyYAML is required for local routing policy")
    content = _read_overlay("blocked-processes.yaml")
    if not content:
        return []
    try:
        payload = (yaml.safe_load(content) or {}).get("payload", [])
    except Exception as exc:
        raise RoutingError(f"Invalid blocked-processes overlay: {exc}") from exc
    result = []
    for item in payload:
        fields = [part.strip() for part in str(item).split(",")]
        if len(fields) >= 2 and fields[0].upper() == "PROCESS-NAME":
            entry = _routing_validate_entry("process-name", fields[1])
            result.append(f"PROCESS-NAME,{entry['value']},REJECT")
    return result


def _routing_rule(entry, target):
    suffix = ",no-resolve" if entry["type"] in ("ip-cidr", "ip-cidr6") else ""
    return f"{_ROUTING_TYPES[entry['type']]},{entry['value']},{target}{suffix}"


def _routing_compose(raw, policy=None, use_draft=False, gfw_state=None):
    """Replace subscription routing with the locally owned effective policy."""
    if policy is None:
        policy = _routing_load()
    if not policy or not policy.get("enabled"):
        return raw
    selected = policy if use_draft else policy.get("active")
    if selected is None:  # initialized policy remains a draft until explicit apply
        return raw
    if yaml is None:
        raise RoutingError("PyYAML is required for local routing policy")
    try:
        config = yaml.safe_load(raw)
    except Exception as exc:
        raise RoutingError(f"Invalid mihomo YAML: {exc}") from exc
    if not isinstance(config, dict):
        raise RoutingError("Mihomo config must be a YAML object")

    target = selected["proxy_target"]
    valid_targets = set()
    for proxy in config.get("proxies") or []:
        if isinstance(proxy, dict) and proxy.get("name"):
            valid_targets.add(str(proxy["name"]))
    for group in config.get("proxy-groups") or []:
        if isinstance(group, dict) and group.get("name"):
            valid_targets.add(str(group["name"]))
    if target not in valid_targets:
        raise RoutingError(f"Proxy target is missing from config: {target}")

    direct_keys = {(item["type"], item["value"]) for item in selected.get("direct", [])}
    rules = _routing_block_rules()
    rules.extend(_routing_rule(item, "DIRECT") for item in selected.get("direct", []))
    rules.extend(
        _routing_rule(item, target)
        for item in selected.get("proxy", [])
        if (item["type"], item["value"]) not in direct_keys
    )
    if gfw_state is None:
        gfw_state = _gfwlist_load()
    if gfw_state.get("enabled"):
        base_direct = gfw_state.get("direct", [])
        base_direct_keys = {(item["type"], item["value"]) for item in base_direct}
        rules.extend(_routing_rule(item, "DIRECT") for item in base_direct)
        rules.extend(
            _routing_rule(item, target)
            for item in gfw_state.get("proxy", [])
            if (item["type"], item["value"]) not in base_direct_keys
        )
    rules.append("MATCH,DIRECT")
    config["mode"] = "direct" if _guard_is_tripped() else "rule"
    config["rules"] = rules
    # Active local rules are self-contained. Removing all rule providers keeps
    # obsolete subscription providers from downloading or influencing startup.
    config.pop("rule-providers", None)
    config.pop("sub-rules", None)
    return yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _routing_validate_with_core(candidate, config_file):
    paths = _get_paths()
    bin_path = paths["bin_path"]
    if not _binary_exists(bin_path):
        raise RoutingError(f"mihomo binary not found; config was not applied: {bin_path}")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".routing-test.", suffix=".yaml", dir=config_file.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(candidate)
        result = subprocess.run(
            [bin_path, "-t", "-d", str(paths["config_dir"]), "-f", temp_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            detail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown error"
            raise RoutingError(f"mihomo rejected generated config: {detail}")
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _atomic_write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _routing_apply_candidate(policy, config_file, dry_run=False, offline=False):
    if not config_file.exists():
        raise RoutingError(f"Mihomo config not found: {config_file}")
    old = config_file.read_text()
    candidate = _routing_compose(old, policy=policy, use_draft=True)
    if dry_run:
        parsed = yaml.safe_load(candidate)
        print(yaml.safe_dump({"mode": parsed.get("mode"), "rules": parsed.get("rules")}, allow_unicode=True, sort_keys=False).rstrip())
        return False
    _routing_validate_with_core(candidate, config_file)
    _atomic_write_text(config_file, candidate)
    payload = json.dumps({"path": str(config_file)}).encode()
    if not offline:
        ok, _ = _api_raw("PUT", "/configs", body=payload)
        if not ok:
            _atomic_write_text(config_file, old)
            _api_raw("PUT", "/configs", body=payload)
            raise RoutingError("Mihomo reload failed; config file was rolled back")
    old_policy_text = _routing_path().read_text() if _routing_path().exists() else None
    published = dict(policy)
    published["active"] = {
        "proxy_target": policy["proxy_target"],
        "direct": list(policy["direct"]),
        "proxy": list(policy["proxy"]),
    }
    try:
        _routing_save(published)
    except Exception as exc:
        _atomic_write_text(config_file, old)
        if old_policy_text is not None:
            _atomic_write_text(_routing_path(), old_policy_text)
        if not offline:
            _api_raw("PUT", "/configs", body=payload)
        raise RoutingError(f"Could not publish routing state; config was rolled back: {exc}") from exc
    policy.clear()
    policy.update(published)
    try:
        _delete_overlay("direct-rules.yaml")
    except OSError as exc:
        print(f"Warning: could not remove legacy direct-rules overlay: {exc}", file=sys.stderr)
    return True


def _cmd_routing_unlocked(args):
    action = args.routing_action
    if action == "show":
        policy = _routing_load()
        if not policy:
            print(f"Routing policy is not initialized: {_routing_path()}")
            return
        print(json.dumps(policy, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if yaml is None:
        raise RoutingError("PyYAML is required for local routing policy")
    if action == "init":
        existing = _routing_load() if _routing_path().exists() else None
        if existing and not args.force:
            raise RoutingError("Routing policy already exists (use --force to replace its draft)")
        direct = []
        for domain in _load_mgr_config().get("direct_domains") or []:
            entry = _routing_validate_entry("domain-suffix", domain)
            if entry not in direct:
                direct.append(entry)
        policy = {
            "version": 1,
            "enabled": True,
            "proxy_target": args.proxy_group.strip(),
            "direct": direct,
            "proxy": [],
            "active": existing.get("active") if existing else None,
        }
        if not policy["proxy_target"] or any(c in policy["proxy_target"] for c in ",\r\n"):
            raise RoutingError("Proxy group cannot be empty or contain commas/newlines")
        _routing_save(policy)
        print(f"Initialized routing draft: {_routing_path()}")
        print("No running config changed. Run 'mihomo-mgr.py routing apply' to publish it.")
        return

    policy = _routing_load(required=True)
    if action in ("add", "remove"):
        list_name = _ROUTING_LIST_ALIASES[args.list_name]
        entry = _routing_validate_entry(args.type, args.value)
        entries = policy[list_name]
        if action == "add":
            if entry not in entries:
                entries.append(entry)
            verb = "Added"
        else:
            if entry in entries:
                entries.remove(entry)
            verb = "Removed"
        _routing_save(policy)
        print(f"{verb} {entry['type']} {entry['value']} in {list_name} draft.")
        print("No running config changed. Run 'mihomo-mgr.py routing apply' to publish it.")
        return
    if action == "apply":
        changed = _routing_apply_candidate(
            policy, _get_paths()["config_file"], dry_run=args.dry_run, offline=args.offline
        )
        if changed:
            if args.offline:
                print("Routing policy generated and saved offline; mihomo was not reloaded.")
            else:
                print("Routing policy applied and mihomo reloaded.")


def cmd_routing(args):
    if args.routing_action == "show":
        return _cmd_routing_unlocked(args)
    with _publish_lock():
        return _cmd_routing_unlocked(args)


def _gfwlist_record_failure(message):
    with _publish_lock():
        state = _gfwlist_load()
        state["last_attempt"] = _time_iso()
        state["next_retry"] = _time_iso(time.time() + GFWLIST_BACKOFF_HOURS * 3600)
        state["error"] = str(message)
        _gfwlist_save(state)


def _gfwlist_publish(parsed, enabled, interval_hours=None, offline=False, if_due=False):
    """Publish parsed base rules while holding the cross-process publication lock."""
    with _publish_lock():
        old_state = _gfwlist_load()
        if if_due and not _gfwlist_is_due(old_state):
            return False
        policy = _routing_load(required=True)
        if not policy.get("enabled") or not policy.get("active"):
            raise RoutingError("Publish the custom routing policy before enabling GFWList")
        config_file = _get_paths()["config_file"]
        if not config_file.exists():
            raise RoutingError(f"Mihomo config not found: {config_file}")
        state = dict(old_state)
        state.update(parsed)
        state["enabled"] = enabled
        if interval_hours is not None:
            state["interval_hours"] = interval_hours
        state["source_url"] = DEFAULT_GFWLIST_URL
        state["last_attempt"] = _time_iso()
        state["last_success"] = state["last_attempt"]
        state["next_retry"] = None
        state["error"] = None

        old_config = config_file.read_text()
        candidate = _routing_compose(old_config, policy=policy, gfw_state=state)
        _routing_validate_with_core(candidate, config_file)
        old_state_text = _gfwlist_path().read_text() if _gfwlist_path().exists() else None
        payload = json.dumps({"path": str(config_file)}).encode()
        _atomic_write_text(config_file, candidate)
        if not offline:
            ok, _ = _api_raw("PUT", "/configs", body=payload)
            if not ok:
                _atomic_write_text(config_file, old_config)
                _api_raw("PUT", "/configs", body=payload)
                raise RoutingError("Mihomo reload failed; GFWList update was rolled back")
        try:
            _gfwlist_save(state)
        except Exception as exc:
            _atomic_write_text(config_file, old_config)
            if old_state_text is not None:
                _atomic_write_text(_gfwlist_path(), old_state_text)
            else:
                _gfwlist_path().unlink(missing_ok=True)
            if not offline:
                _api_raw("PUT", "/configs", body=payload)
            raise RoutingError(f"GFWList cache write failed; config was rolled back: {exc}") from exc
        return True


def _gfwlist_disable(offline=False):
    with _publish_lock():
        old_state = _gfwlist_load()
        if not old_state.get("enabled"):
            return False
        policy = _routing_load(required=True)
        if not policy.get("active"):
            raise RoutingError("Published custom routing policy is missing")
        config_file = _get_paths()["config_file"]
        if not config_file.exists():
            raise RoutingError(f"Mihomo config not found: {config_file}")
        state = dict(old_state)
        state["enabled"] = False
        state["error"] = None
        old_config = config_file.read_text()
        candidate = _routing_compose(old_config, policy=policy, gfw_state=state)
        _routing_validate_with_core(candidate, config_file)
        payload = json.dumps({"path": str(config_file)}).encode()
        _atomic_write_text(config_file, candidate)
        if not offline:
            ok, _ = _api_raw("PUT", "/configs", body=payload)
            if not ok:
                _atomic_write_text(config_file, old_config)
                _api_raw("PUT", "/configs", body=payload)
                raise RoutingError("Mihomo reload failed; GFWList disable was rolled back")
        try:
            _gfwlist_save(state)
        except Exception as exc:
            _atomic_write_text(config_file, old_config)
            if not offline:
                _api_raw("PUT", "/configs", body=payload)
            raise RoutingError(f"GFWList disable failed; config was rolled back: {exc}") from exc
        return True


def cmd_gfwlist(args):
    action = args.gfwlist_action
    if action == "status":
        state = _gfwlist_load()
        if args.json:
            print(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True))
            return
        print(f"Source: {state['source_url']}")
        print(f"Enabled: {'yes' if state['enabled'] else 'no'}")
        print(f"Interval: {state['interval_hours']}h")
        print(f"Last success: {state.get('last_success') or '-'}")
        print(f"Last attempt: {state.get('last_attempt') or '-'}")
        print(f"Entries: {len(state['proxy'])} proxy, {len(state['direct'])} direct")
        print(f"Skipped: {state.get('skipped_count', 0)}")
        print(f"Conservative exceptions: {state.get('conservative_exception_count', 0)}")
        print(f"Error: {state.get('error') or '-'}")
        print(f"Cache: {_gfwlist_path()}")
        if args.skipped:
            print(json.dumps({
                "reasons": state.get("skipped_reasons", {}),
                "samples": state.get("skipped_samples", {}),
                "conservative_reasons": state.get("conservative_reasons", {}),
                "conservative_samples": state.get("conservative_samples", {}),
            }, indent=2, ensure_ascii=False, sort_keys=True))
        return
    if action == "disable":
        try:
            changed = _gfwlist_disable(offline=args.offline)
        except Exception as exc:
            try:
                _gfwlist_record_failure(exc)
            except Exception as state_exc:
                raise RoutingError(f"{exc}; additionally could not record failure: {state_exc}") from exc
            raise
        if changed:
            print("GFWList base disabled; published custom routing remains active.")
        else:
            print("GFWList base is already disabled.")
        return

    if action == "update":
        state = _gfwlist_load()
        if not state.get("enabled"):
            if args.if_due:
                return
            raise RoutingError("GFWList base is disabled; run 'gfwlist enable' first")
        if args.if_due and not _gfwlist_is_due(state):
            return
        interval = None
        enabled = True
    else:  # enable
        interval = args.interval_hours
        if interval < 0:
            raise RoutingError("GFWList interval-hours cannot be negative")
        enabled = True

    try:
        raw = _gfwlist_fetch()
        parsed = _gfwlist_parse(raw)
    except Exception as exc:
        try:
            _gfwlist_record_failure(exc)
        except Exception as state_exc:
            raise RoutingError(f"{exc}; additionally could not record failure: {state_exc}") from exc
        raise
    try:
        changed = _gfwlist_publish(
            parsed,
            enabled=enabled,
            interval_hours=interval,
            offline=args.offline,
            if_due=getattr(args, "if_due", False),
        )
    except Exception as exc:
        try:
            _gfwlist_record_failure(exc)
        except Exception as state_exc:
            raise RoutingError(f"{exc}; additionally could not record failure: {state_exc}") from exc
        raise
    if changed:
        verb = "enabled" if action == "enable" else "updated"
        suffix = " offline" if args.offline else " and reloaded"
        print(f"GFWList {verb}{suffix}: {parsed['accepted_count']} entries, {parsed['skipped_count']} skipped.")


def _strip_json_comments(text):
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _validate_config(cfg):
    """Validate configuration values and apply defaults for invalid entries."""
    # Validate stats.retention_days
    stats = cfg.get("stats", {})
    if isinstance(stats, dict):
        retention = stats.get("retention_days")
        if retention is not None:
            try:
                val = int(retention)
                if val <= 0:
                    raise ValueError
                stats["retention_days"] = val
            except (ValueError, TypeError):
                stats["retention_days"] = 180

        poll_interval = stats.get("poll_interval")
        if poll_interval is not None:
            try:
                val = int(poll_interval)
                if val < 1 or val > 60:
                    raise ValueError
                stats["poll_interval"] = val
            except (ValueError, TypeError):
                stats["poll_interval"] = 5

    # Validate idle.auto_block_level
    idle = cfg.get("idle", {})
    if isinstance(idle, dict):
        level = idle.get("auto_block_level")
        valid_levels = ["notify", "block", "force_block"]
        if level is not None and level not in valid_levels:
            idle["auto_block_level"] = "notify"

        count = idle.get("block_after_notify_count")
        if count is not None:
            try:
                val = int(count)
                if val < 1:
                    raise ValueError
                idle["block_after_notify_count"] = val
            except (ValueError, TypeError):
                idle["block_after_notify_count"] = 3

        cooldown = idle.get("cooldown_minutes")
        if cooldown is not None:
            try:
                val = int(cooldown)
                if val < 1:
                    raise ValueError
                idle["cooldown_minutes"] = val
            except (ValueError, TypeError):
                idle["cooldown_minutes"] = 30

    # Validate schedule.work_hours format
    schedule = cfg.get("schedule", {})
    if isinstance(schedule, dict):
        work_hours = schedule.get("work_hours")
        if work_hours and isinstance(work_hours, str):
            if "-" not in work_hours:
                schedule["work_hours"] = "09:00-22:00"

    return cfg


def _default_mgr_config_text():
    return """# mihomo-mgr configuration
# This file may be edited by hand.

# ── Basic Configuration ──

# Subscription URL (REQUIRED for sub-pull)
sub_url: ""

# mihomo working directory
config_dir: ""

# mihomo binary directory or path
bin_dir: ""
bin: ""

# Log and PID files
log_file: ""
pid_file: ""

# mihomo external controller
api: "http://127.0.0.1:9090"
sock: ""
secret: ""

# Proxy ports
mixed_port: "10808"
proxy_host: "127.0.0.1"
proxy_http_port: ""
proxy_socks_port: ""
proxy_http: ""
proxy_socks: ""
no_proxy: "localhost,127.0.0.1,::1,*.local"

# Direct domains (injected as DOMAIN-SUFFIX rules)
direct_domains: []

# Health check URL
health_check_url: "http://www.gstatic.com/generate_204"

# ── Traffic Stats ──
stats:
  enabled: true
  db: "~/.config/mihomo-mgr/traffic.db"
  retention_days: 180
  poll_interval: 5

# ── Idle Detection ──
idle:
  enabled: true
  auto_block_level: "notify"  # notify | block | force_block
  block_after_notify_count: 3
  cooldown_minutes: 30
  monitored:
    codex:
      idle_check: "history_jsonl"
      idle_file: "~/.codex/history.jsonl"
      idle_field: "ts"
      threshold_hours: 2
      block_mode: "PROCESS-NAME"
    opencode:
      idle_check: "session_mtime"
      idle_dir: "~/.local/state/opencode/"
      threshold_hours: 4
      block_mode: "PROCESS-NAME"
  whitelist:
    - "clawd-ding"
    - "tokensflow"
    - "mihomo"
  blacklist: []

# ── Schedule (Auto Start/Stop) ──
schedule:
  enabled: false
  work_hours: "09:00-22:00"
  work_days: "mon-fri"

# ── Notifications ──
notify:
  channels:
    - "file"
    - "terminal"
    - "dingtalk"
  dingtalk:
    webhook: ""
    secret: ""
"""


# ── Overlay System ────────────────────────────────────────────────────────


def _get_overlays_dir() -> Path:
    """Get overlays directory, colocated with config_dir."""
    cfg = _load_mgr_config()
    config_dir = Path(
        os.environ.get(
            "MIHOMO_CONFIG_DIR", _cfg_value(cfg, "config_dir", str(Path.cwd()))
        )
    )
    return config_dir / "overlays"


def _ensure_overlays_dir():
    """Create overlays directory if it doesn't exist."""
    _get_overlays_dir().mkdir(parents=True, exist_ok=True)


def _overlay_path(name: str) -> Path:
    """Get path for an overlay file."""
    return _get_overlays_dir() / name


def _read_overlay(name: str) -> str:
    """Read overlay file content. Returns empty string if not found."""
    path = _overlay_path(name)
    if path.exists():
        return path.read_text()
    return ""


def _write_overlay(name: str, content: str):
    """Write content to overlay file."""
    _ensure_overlays_dir()
    path = _overlay_path(name)
    path.write_text(content)


def _delete_overlay(name: str):
    """Delete overlay file."""
    path = _overlay_path(name)
    if path.exists():
        path.unlink()


def _list_overlays() -> list:
    """List all overlay files."""
    overlays_dir = _get_overlays_dir()
    overlays_dir.mkdir(parents=True, exist_ok=True)
    return [f.name for f in overlays_dir.iterdir() if f.is_file()]


def _reapply_watch_groups(content: str) -> str:
    """Re-inject watch-managed url-test proxy-groups from overlay.

    Reads watch-groups.yaml overlay and:
    1. Inserts the group definition line after proxy-groups:
    2. Adds the watch group name to the target selector's proxies list
    """
    try:
        overlay_content = _read_overlay("watch-groups.yaml")
        if not overlay_content:
            return content

        if yaml is None:
            return content
        data = yaml.safe_load(overlay_content)
        group_def = data.get("group_definition", "").strip()
        target_group = data.get("target_group", "")
        group_name = data.get("group_name", "").strip('"').strip("'")

        if not group_def or not target_group or not group_name:
            return content

        config = yaml.safe_load(content)
        definitions = yaml.safe_load(group_def)
        if not isinstance(config, dict) or not isinstance(definitions, list) or not definitions:
            return content
        groups = config.get("proxy-groups")
        if not isinstance(groups, list):
            return content
        if not any(isinstance(group, dict) and group.get("name") == group_name for group in groups):
            groups.insert(0, definitions[0])
        for group in groups:
            if isinstance(group, dict) and group.get("name") == target_group:
                proxies = group.setdefault("proxies", [])
                if isinstance(proxies, list) and group_name not in proxies:
                    proxies.insert(0, group_name)
                break
        return yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception:
        return content


def _compose_overlays(content):
    """Compose manager overlays into YAML text without writing or reloading.

    This function:
    1. Reads all overlay files from overlays/ directory
    2. Injects rule-providers entries into config.yaml
    3. Injects RULE-SET references into rules section
    4. Re-injects watch-managed proxy-groups from watch-groups.yaml
    5. Reloads mihomo config
    """
    content = _reapply_watch_groups(content)
    if yaml is None:
        if _routing_load():
            raise RoutingError("PyYAML is required for local routing policy")
        return content
    try:
        config = yaml.safe_load(content) or {}
    except Exception as exc:
        raise RoutingError(f"Invalid mihomo YAML: {exc}") from exc

    providers = config.get("rule-providers")
    if not isinstance(providers, dict):
        providers = {}
    # Remove only manager-owned providers and references. Subscription
    # providers remain intact, and watch-groups are never treated as rulesets.
    managed = {
        "direct_rules": ("direct-rules.yaml", "DIRECT"),
        "blocked_processes": ("blocked-processes.yaml", "REJECT"),
    }
    rules = [
        str(rule)
        for rule in (config.get("rules") or [])
        if not any(str(rule).startswith(f"RULE-SET,{name},") for name in managed)
    ]
    refs = []
    for name, (overlay_name, target) in managed.items():
        providers.pop(name, None)
        overlay_path = _overlay_path(overlay_name)
        if overlay_path.exists():
            providers[name] = {
                "type": "file",
                "behavior": "classical",
                "path": str(overlay_path),
            }
            refs.append(f"RULE-SET,{name},{target}")
    if providers:
        config["rule-providers"] = providers
    else:
        config.pop("rule-providers", None)
    config["rules"] = refs + rules
    content = yaml.safe_dump(config, default_flow_style=False, allow_unicode=True, sort_keys=False)
    content = _routing_compose(content)
    return content


def _reapply_overlays_unlocked():
    """Reapply overlays to the managed config and reload when a core is reachable."""
    config_file = _get_paths()["config_file"]
    if not config_file.exists():
        return
    old = config_file.read_text()
    content = _compose_overlays(old)
    if _routing_has_active():
        _routing_validate_with_core(content, config_file)
    _atomic_write_text(config_file, content)

    reachable, _ = _api_raw("GET", "/version")
    if reachable:
        payload = json.dumps({"path": str(config_file)}).encode()
        ok, _ = _api_raw("PUT", "/configs", body=payload)
        if not ok:
            _atomic_write_text(config_file, old)
            _api_raw("PUT", "/configs", body=payload)
            raise RoutingError("Mihomo reload failed; config file was rolled back")


def _reapply_overlays():
    with _publish_lock():
        return _reapply_overlays_unlocked()


# ── Traffic Stats Database ──────────────────────────────────────────────────


def _get_stats_db_path() -> Path:
    """Get the path to the traffic stats SQLite database."""
    cfg = _load_mgr_config()
    stats_cfg = cfg.get("stats", {})
    db_path = stats_cfg.get("db", "~/.config/mihomo-mgr/traffic.db")
    return Path(db_path).expanduser()


def _init_stats_db(db_path: Path = None):
    """Initialize the traffic stats SQLite database with required tables."""
    if db_path is None:
        db_path = _get_stats_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create hourly_domain table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hourly_domain (
            hour TEXT NOT NULL,
            domain TEXT NOT NULL,
            upload_bytes INTEGER DEFAULT 0,
            download_bytes INTEGER DEFAULT 0,
            connection_count INTEGER DEFAULT 0,
            PRIMARY KEY (hour, domain)
        )
    """)

    # Create hourly_node table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hourly_node (
            hour TEXT NOT NULL,
            node TEXT NOT NULL,
            upload_bytes INTEGER DEFAULT 0,
            download_bytes INTEGER DEFAULT 0,
            connection_count INTEGER DEFAULT 0,
            PRIMARY KEY (hour, node)
        )
    """)

    # Create hourly_rule table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hourly_rule (
            hour TEXT NOT NULL,
            rule TEXT NOT NULL,
            upload_bytes INTEGER DEFAULT 0,
            download_bytes INTEGER DEFAULT 0,
            connection_count INTEGER DEFAULT 0,
            PRIMARY KEY (hour, rule)
        )
    """)

    # Create daily_summary table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date TEXT PRIMARY KEY,
            total_upload_bytes INTEGER DEFAULT 0,
            total_download_bytes INTEGER DEFAULT 0,
            total_connections INTEGER DEFAULT 0,
            unique_domains INTEGER DEFAULT 0
        )
    """)

    # Create monthly_summary table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_summary (
            month TEXT PRIMARY KEY,
            total_upload_bytes INTEGER DEFAULT 0,
            total_download_bytes INTEGER DEFAULT 0,
            total_connections INTEGER DEFAULT 0,
            unique_domains INTEGER DEFAULT 0
        )
    """)

    # Create calibration table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calibration (
            timestamp TEXT PRIMARY KEY,
            db_upload_bytes INTEGER,
            db_download_bytes INTEGER,
            api_upload_bytes INTEGER,
            api_download_bytes INTEGER,
            drift_pct REAL
        )
    """)

    # Create meta table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Create large_downloads table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS large_downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            domain TEXT NOT NULL,
            node TEXT,
            process TEXT,
            process_path TEXT,
            source_ip TEXT,
            source_port TEXT,
            destination_ip TEXT,
            destination_port TEXT,
            download_bytes INTEGER NOT NULL,
            duration_seconds REAL,
            rule TEXT
        )
    """)

    conn.commit()
    conn.close()

    return db_path


def _update_hourly_stats(
    db_path: Path,
    hour: str,
    domain: str,
    node: str,
    rule: str,
    upload: int,
    download: int,
):
    """Update hourly statistics for domain, node, and rule."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Update hourly_domain
    cursor.execute(
        """
        INSERT INTO hourly_domain (hour, domain, upload_bytes, download_bytes, connection_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(hour, domain) DO UPDATE SET
            upload_bytes = upload_bytes + ?,
            download_bytes = download_bytes + ?,
            connection_count = connection_count + 1
    """,
        (hour, domain, upload, download, upload, download),
    )

    # Update hourly_node
    cursor.execute(
        """
        INSERT INTO hourly_node (hour, node, upload_bytes, download_bytes, connection_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(hour, node) DO UPDATE SET
            upload_bytes = upload_bytes + ?,
            download_bytes = download_bytes + ?,
            connection_count = connection_count + 1
    """,
        (hour, node, upload, download, upload, download),
    )

    # Update hourly_rule
    cursor.execute(
        """
        INSERT INTO hourly_rule (hour, rule, upload_bytes, download_bytes, connection_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(hour, rule) DO UPDATE SET
            upload_bytes = upload_bytes + ?,
            download_bytes = download_bytes + ?,
            connection_count = connection_count + 1
    """,
        (hour, rule, upload, download, upload, download),
    )

    conn.commit()
    conn.close()


def _update_daily_summary(db_path: Path, date: str):
    """Update daily summary by aggregating hourly data."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            SUM(upload_bytes),
            SUM(download_bytes),
            SUM(connection_count),
            COUNT(DISTINCT domain)
        FROM hourly_domain
        WHERE hour LIKE ?
    """,
        (f"{date}%",),
    )

    result = cursor.fetchone()
    if result and result[0]:
        cursor.execute(
            """
            INSERT INTO daily_summary (date, total_upload_bytes, total_download_bytes,
                                      total_connections, unique_domains)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_upload_bytes = ?,
                total_download_bytes = ?,
                total_connections = ?,
                unique_domains = ?
        """,
            (
                date,
                result[0],
                result[1],
                result[2],
                result[3],
                result[0],
                result[1],
                result[2],
                result[3],
            ),
        )

    conn.commit()
    conn.close()


def _update_monthly_summary(db_path: Path, month: str):
    """Update monthly summary by aggregating daily data."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            SUM(total_upload_bytes),
            SUM(total_download_bytes),
            SUM(total_connections),
            MAX(unique_domains)
        FROM daily_summary
        WHERE date LIKE ?
    """,
        (f"{month}%",),
    )

    result = cursor.fetchone()
    if result and result[0]:
        cursor.execute(
            """
            INSERT INTO monthly_summary (month, total_upload_bytes, total_download_bytes,
                                        total_connections, unique_domains)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(month) DO UPDATE SET
                total_upload_bytes = ?,
                total_download_bytes = ?,
                total_connections = ?,
                unique_domains = ?
        """,
            (
                month,
                result[0],
                result[1],
                result[2],
                result[3],
                result[0],
                result[1],
                result[2],
                result[3],
            ),
        )

    conn.commit()
    conn.close()


def _record_calibration(
    db_path: Path, db_upload: int, db_download: int, api_upload: int, api_download: int
):
    """Record calibration data comparing DB totals with API totals."""

    timestamp = datetime.now().isoformat()

    if api_upload > 0:
        drift_pct = abs(db_upload - api_upload) / api_upload * 100
    else:
        drift_pct = 0.0

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO calibration (timestamp, db_upload_bytes, db_download_bytes,
                                api_upload_bytes, api_download_bytes, drift_pct)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (timestamp, db_upload, db_download, api_upload, api_download, drift_pct),
    )

    conn.commit()
    conn.close()


def _cleanup_old_data(db_path: Path, retention_days: int):
    """Delete data older than retention_days."""
    from datetime import timedelta

    cutoff_date = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    cutoff_hour = cutoff_date + "T00"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Delete old hourly data
    cursor.execute("DELETE FROM hourly_domain WHERE hour < ?", (cutoff_hour,))
    cursor.execute("DELETE FROM hourly_node WHERE hour < ?", (cutoff_hour,))
    cursor.execute("DELETE FROM hourly_rule WHERE hour < ?", (cutoff_hour,))

    # Delete old daily summaries
    cursor.execute("DELETE FROM daily_summary WHERE date < ?", (cutoff_date,))

    # Delete old calibration data
    cutoff_timestamp = cutoff_date + "T00:00:00"
    cursor.execute("DELETE FROM calibration WHERE timestamp < ?", (cutoff_timestamp,))

    conn.commit()
    conn.close()


# ── Traffic Collector ───────────────────────────────────────────────────────


# ── Guard 流量熔断 ─────────────────────────────────────────────


GUARD_DEFAULTS = {
    "enabled": True,             # 总开关
    "monthly_quota_gb": 100.0,   # 机场月配额（GB），阈值与月预警的基准
    "trip_threshold_pct": 10.0,  # 熔断阈值 = 配额 × 百分比（滚动 1 小时代理流量）
    "warn_threshold_pct": 5.0,   # 预警阈值 = 配额 × 百分比，仅通知；0 关闭
    "monthly_warn_pct": 80.0,    # 月累计预警百分比；0 关闭
    "disable_hours": 24.0,       # 熔断持续小时数，到期自动恢复原模式
    "wall": True,                # 熔断/预警时 wall 广播全部已登录终端
}
GUARD_GB = 1024 ** 3
GUARD_ROLLING_MINUTES = 60


def _guard_cfg():
    """guard 配置：默认值与 config.yaml guard 节合并。"""
    g = _load_mgr_config().get("guard", {})
    if not isinstance(g, dict):
        g = {}
    merged = dict(GUARD_DEFAULTS)
    merged.update({k: v for k, v in g.items() if k in GUARD_DEFAULTS})
    return merged


def _guard_state_path():
    return _mgr_config_path().parent / "guard-state.json"


def _guard_load_state():
    """guard 状态：rolling 分钟桶 + 熔断状态；daemon 与 CLI 通过它协作。"""
    state = {"minute_buckets": [], "disabled_until": None, "saved_mode": "rule",
             "trip_event": None, "warn_active": False, "monthly_warned": {},
             "last_anomaly": None}
    try:
        data = json.loads(_guard_state_path().read_text())
        if isinstance(data, dict):
            state.update({k: v for k, v in data.items() if k in state})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return state


def _guard_save_state(state):
    path = _guard_state_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False))
    os.replace(tmp, path)


def _guard_api(method, path, body=None):
    """daemon 安全版 api：任何失败都不退出进程，失败返回 None。"""
    try:
        return api(method, path, body, quiet=True)
    except (SystemExit, Exception):
        return None


def _guard_trip_bytes(cfg):
    return cfg["monthly_quota_gb"] * cfg["trip_threshold_pct"] / 100.0 * GUARD_GB


def _guard_warn_bytes(cfg):
    if not cfg["warn_threshold_pct"]:
        return 0
    return cfg["monthly_quota_gb"] * cfg["warn_threshold_pct"] / 100.0 * GUARD_GB


def _guard_fmt(nbytes):
    return f"{nbytes / GUARD_GB:.2f}GB"


def _guard_month_used(db_path):
    """当月累计代理流量（hourly_domain 求和，含上传下载）；无库返回 None。"""
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT SUM(upload_bytes+download_bytes) FROM hourly_domain WHERE hour LIKE ?",
            (datetime.now().strftime("%Y-%m") + "%",),
        ).fetchone()
        conn.close()
        return row[0] or 0
    except sqlite3.Error:
        return None


def _guard_notify(title, message):
    """复用 mm 通知通道（文件/钉钉/tmux），叠加 wall 终端广播；通知失败不拖垮熔断。"""
    try:
        _send_notification(title, message)
    except Exception:
        pass
    if _guard_cfg().get("wall", True):
        try:
            subprocess.run(
                ["wall"],
                input=f"{title}\n{message}".encode(),
                timeout=10,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def _guard_write_report(db_path, cfg, reason, rolling, saved_mode):
    """写事件取证报告（元凶域名/进程），返回文件路径。"""
    events = _mgr_config_path().parent / "guard-events"
    try:
        events.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # 报告目录建不了时降级为内存字符串路径，不阻断熔断
    now = datetime.now()
    fname = now.strftime("%Y-%m-%d_%H%M%S") + ".md"
    until = now + timedelta(hours=cfg["disable_hours"])
    lines = [
        f"# mm guard 熔断事件 {now.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- **触发原因**：{reason}",
        f"- **滚动 60 分钟代理流量**：{_guard_fmt(rolling)}"
        f"（阈值 {_guard_fmt(_guard_trip_bytes(cfg))} ="
        f" 月配额 {cfg['monthly_quota_gb']:g}GB × {cfg['trip_threshold_pct']:g}%）",
        f"- **动作**：mihomo 切 direct 模式 + 断开全部连接（机场流量归零，监控继续）",
        f"- **熔断至**：{until.strftime('%Y-%m-%d %H:%M')}"
        f"（到期恢复 {saved_mode}；手动解除：mm guard release）",
        "",
        "## 元凶域名（本小时）",
        "",
    ]
    domains, processes = [], []
    try:
        conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
        hour_key = now.strftime("%Y-%m-%dT%H")
        domains = conn.execute(
            "SELECT domain, SUM(upload_bytes+download_bytes), COUNT(*) FROM hourly_domain "
            "WHERE hour >= ? GROUP BY domain ORDER BY 2 DESC LIMIT 5",
            (hour_key,),
        ).fetchall()
        cutoff = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        processes = conn.execute(
            "SELECT process, domain, COUNT(*), SUM(download_bytes) FROM large_downloads "
            "WHERE timestamp >= ? GROUP BY process, domain ORDER BY 4 DESC LIMIT 5",
            (cutoff,),
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        pass
    if domains:
        lines += ["| 域名 | 流量 | 连接数 |", "|---|---|---|"]
        lines += [f"| {d} | {_guard_fmt(b)} | {c} |" for d, b, c in domains]
    else:
        lines.append("（本小时无记录）")
    lines += ["", "## 大文件下载进程（近 2 小时，>30MB）", ""]
    if processes:
        lines += ["| 进程 | 域名 | 次数 | 下载量 |", "|---|---|---|---|"]
        lines += [f"| {p} | {dm} | {c} | {_guard_fmt(b)} |" for p, dm, c, b in processes]
    else:
        lines.append("（近 2 小时无 >30MB 记录）")
    target = events / fname
    try:
        target.write_text("\n".join(lines) + "\n")
        return str(target)
    except OSError as e:
        return f"(报告写入失败: {e})"


def _guard_trip(cfg, state, db_path, reason, rolling):
    """执行熔断：切 direct、断连接、写报告、通知、记状态。"""
    mode = (_guard_api("GET", "/configs") or {}).get("mode") or "rule"
    saved_mode = mode if mode != "direct" else "rule"
    saved_mode = _routing_safe_restore_mode(saved_mode)
    _guard_api("PATCH", "/configs", {"mode": "direct"})
    _guard_api("DELETE", "/connections")
    report = _guard_write_report(db_path, cfg, reason, rolling, saved_mode)
    state["saved_mode"] = saved_mode
    state["trip_event"] = report
    state["disabled_until"] = (
        datetime.now() + timedelta(hours=cfg["disable_hours"])
    ).isoformat()
    until = datetime.fromisoformat(state["disabled_until"]).strftime("%m-%d %H:%M")
    _guard_notify(
        "mm guard: 代理已熔断",
        f"{reason}\n已切 direct 模式并断开全部连接，机场流量归零\n"
        f"将于 {until} 自动恢复；手动解除: mm guard release\n详情: {report}",
    )
    return report


def _guard_parse_until(value):
    """解析 disabled_until；损坏/缺失返回 None（调用方按未熔断自愈）。"""
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _guard_check(cfg, state, db_path):
    """guard 核心检查（daemon 每 30 秒 / mm guard check 调用）。"""
    now = datetime.now()
    rolling = sum(b[1] for b in state.get("minute_buckets", []))

    # 月累计预警（每自然月一次）
    if cfg["monthly_warn_pct"] and cfg["monthly_quota_gb"] > 0:
        ym = now.strftime("%Y-%m")
        if not state.get("monthly_warned", {}).get(ym):
            used = _guard_month_used(db_path)
            limit = cfg["monthly_quota_gb"] * GUARD_GB
            if used is not None and used >= limit * cfg["monthly_warn_pct"] / 100.0:
                state.setdefault("monthly_warned", {})[ym] = True
                _guard_notify(
                    "mm guard: 月流量预警",
                    f"本月累计代理流量 {_guard_fmt(used)} / 配额 {cfg['monthly_quota_gb']:g}GB"
                    f"（{used / limit * 100:.0f}%，已过 {cfg['monthly_warn_pct']:g}% 预警线）",
                )

    until = state.get("disabled_until")
    if until:
        until_dt = _guard_parse_until(until)
        if not until_dt:
            state["disabled_until"] = None  # 损坏状态自愈，下轮按未熔断处理
            return
        if now >= until_dt:
            # 熔断期满：恢复原模式并通知
            restore = _routing_safe_restore_mode(state.get("saved_mode") or "rule")
            _guard_api("PATCH", "/configs", {"mode": restore})
            state["disabled_until"] = None
            state["trip_event"] = None
            state["warn_active"] = False
            _guard_notify("mm guard: 熔断期满已恢复", f"已恢复 {restore} 模式")
        else:
            # 防篡改：被外部改回则重新熔断（通知 10 分钟限频）
            mode = (_guard_api("GET", "/configs") or {}).get("mode")
            if mode and mode != "direct":
                # 先核对磁盘状态：可能是 CLI release 刚解除，避免用陈旧内存状态回滚解除
                fresh = _guard_load_state()
                if not fresh.get("disabled_until"):
                    state["disabled_until"] = None
                    state["trip_event"] = None
                    state["warn_active"] = False
                    return
                _guard_api("PATCH", "/configs", {"mode": "direct"})
                _guard_api("DELETE", "/connections")
                last = state.get("last_anomaly")
                elapsed = None
                try:
                    if last:
                        elapsed = now - datetime.fromisoformat(last)
                except (TypeError, ValueError):
                    elapsed = None  # 损坏时间戳视为可通知
                if elapsed is None or elapsed > timedelta(minutes=10):
                    state["last_anomaly"] = now.isoformat()
                    _guard_notify(
                        "mm guard: 检测到熔断被绕过",
                        f"模式被外部改回 {mode}，已重新切回 direct。\n如确需解除: mm guard release",
                    )
        return

    tb, wb = _guard_trip_bytes(cfg), _guard_warn_bytes(cfg)
    if wb and wb <= rolling < tb and not state.get("warn_active"):
        state["warn_active"] = True
        _guard_notify(
            "mm guard: 流量预警",
            f"最近 60 分钟代理流量 {_guard_fmt(rolling)} ≥ 预警线 {_guard_fmt(wb)}"
            f"（熔断线 {_guard_fmt(tb)}）",
        )
    elif state.get("warn_active") and rolling < wb * 0.5:
        state["warn_active"] = False  # 回落后允许再次预警
    if rolling >= tb:
        _guard_trip(
            cfg, state, db_path,
            f"滚动 60 分钟代理流量 {_guard_fmt(rolling)} ≥ 熔断阈值 {_guard_fmt(tb)}",
            rolling,
        )


class _TrafficCollector:
    """Collects traffic statistics from mihomo API."""

    def __init__(self, db_path: Path = None, poll_interval: int = 5):
        self.db_path = db_path or _get_stats_db_path()
        self.poll_interval = poll_interval
        self._connections = {}  # id -> {upload, download, domain, node, rule, start_time}
        self._running = False
        self._last_cleanup_date = None
        self._schedule_check_counter = 0
        self._idle_check_counter = 0
        self._guard_check_counter = 0
        self._gfwlist_check_counter = 0
        self._gfwlist_child = None
        self._guard_uncommitted = 0  # 自上次 guard 检查以来累计的代理流量（字节）
        self._primed = False  # 首轮 poll 只建基线不入账，防 daemon 重启后重计存活连接

        # Initialize database
        _init_stats_db(self.db_path)

    def start(self):
        """Start the traffic collector."""
        self._running = True
        self._collect_loop()

    def stop(self):
        """Stop the traffic collector."""
        self._running = False
        child = self._gfwlist_child
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        self._gfwlist_child = None

    def _collect_loop(self):
        """Main collection loop."""
        while self._running:
            try:
                self._poll_connections()
                self._check_cleanup()
                self._check_schedule_tick()
                self._check_idle_tick()
                self._check_gfwlist_tick()
                self._check_guard_tick()
                time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                self._running = False
                break
            except Exception as e:
                print(f"Traffic collector error: {e}", file=sys.stderr)
                time.sleep(self.poll_interval)

    def _check_schedule_tick(self):
        """Check schedule every 60 seconds."""
        self._schedule_check_counter += 1
        if self._schedule_check_counter < 60 // max(self.poll_interval, 1):
            return
        self._schedule_check_counter = 0
        try:
            _check_schedule()
        except Exception as e:
            print(f"Schedule check error: {e}", file=sys.stderr)

    def _check_idle_tick(self):
        """Check idle processes every 5 minutes (300 * poll_interval)."""
        self._idle_check_counter += 1
        if self._idle_check_counter < 300 // max(self.poll_interval, 1):
            return
        self._idle_check_counter = 0
        try:
            _run_idle_check()
        except Exception as e:
            print(f"Idle check error: {e}", file=sys.stderr)

    def _check_gfwlist_tick(self):
        """Spawn at most one due updater without blocking collection or guard checks."""
        if self._gfwlist_child is not None:
            if self._gfwlist_child.poll() is None:
                return
            self._gfwlist_child = None
        self._gfwlist_check_counter += 1
        if self._gfwlist_check_counter < 60 // max(self.poll_interval, 1):
            return
        self._gfwlist_check_counter = 0
        try:
            state = _gfwlist_load()
            if not _gfwlist_is_due(state):
                return
            self._gfwlist_child = subprocess.Popen(
                [sys.executable, __file__, "gfwlist", "update", "--if-due"],
                stdin=subprocess.DEVNULL,
            )
        except Exception as exc:
            print(f"GFWList schedule check error: {exc}", file=sys.stderr)

    def _check_guard_tick(self):
        """流量熔断检查：每 30 秒一次；rolling 桶持久化在 guard-state.json。"""
        self._guard_check_counter += 1
        if self._guard_check_counter < 30 // max(self.poll_interval, 1):
            return
        self._guard_check_counter = 0
        _invalidate_config_cache()  # 让运行中的 daemon 也能读到 config-set 的新值
        cfg = _guard_cfg()
        if not cfg.get("enabled"):
            self._guard_uncommitted = 0  # 停用期间不积压，避免重新启用后瞬间误熔断
            return
        state = _guard_load_state()  # 每次重读，与 mm guard release 等 CLI 协作
        if self._guard_uncommitted:
            now = datetime.now()
            minute = now.strftime("%Y-%m-%dT%H:%M")
            buckets = state.get("minute_buckets", [])
            if buckets and buckets[-1][0] == minute:
                buckets[-1][1] += self._guard_uncommitted
            else:
                buckets.append([minute, self._guard_uncommitted])
            cutoff = (now - timedelta(minutes=GUARD_ROLLING_MINUTES)).strftime("%Y-%m-%dT%H:%M")
            state["minute_buckets"] = [b for b in buckets if b[0] >= cutoff]
            self._guard_uncommitted = 0
        _guard_check(cfg, state, self.db_path)
        _guard_save_state(state)

    def _poll_connections(self):
        """Poll /connections API and update statistics."""
        try:
            data = _guard_api("GET", "/connections")  # SystemExit 安全，失败不杀 daemon

            # Distinguish between transient errors and authoritative empty
            # None or null connections = transient error, preserve existing state
            # Empty list [] = authoritative "no connections", close all
            if data is None:
                return  # Transient error, preserve existing connections

            connections_list = data.get("connections")
            if connections_list is None:
                return  # Transient error, preserve existing connections

            current_connections = {}

            for conn in connections_list:
                # Skip malformed connection entries
                if not isinstance(conn, dict):
                    continue

                conn_id = conn.get("id")
                if not conn_id:
                    continue

                metadata = conn.get("metadata") or {}
                if not isinstance(metadata, dict):
                    metadata = {}

                domain = metadata.get("host", "unknown")
                chains = conn.get("chains") or []
                if not isinstance(chains, list):
                    chains = []
                node = chains[0] if chains else "unknown"
                rule = conn.get("rule", "unknown")
                upload = conn.get("upload", 0)
                download = conn.get("download", 0)

                # Ensure upload/download are numeric
                try:
                    upload = int(upload) if upload else 0
                except (ValueError, TypeError):
                    upload = 0
                try:
                    download = int(download) if download else 0
                except (ValueError, TypeError):
                    download = 0
                start_time = conn.get("start", "")
                process = metadata.get("process", "")
                process_path = metadata.get("processPath", "")
                source_ip = metadata.get("sourceIP", "")
                source_port = metadata.get("sourcePort", "")
                destination_ip = metadata.get("destinationIP", "")
                destination_port = metadata.get("destinationPort", "")

                current_connections[conn_id] = {
                    "upload": upload,
                    "download": download,
                    "domain": domain,
                    "node": node,
                    "rule": rule,
                    "start_time": start_time,
                    "process": process,
                    "process_path": process_path,
                    "source_ip": source_ip,
                    "source_port": source_port,
                    "destination_ip": destination_ip,
                    "destination_port": destination_port,
                }

                # Track new connection
                if conn_id not in self._connections:
                    self._connections[conn_id] = current_connections[conn_id]
                    # 首次发现的连接：首采前已产生的字节直接入账（只记这一次）；
                    # 首轮 poll 除外（基线，防 daemon 重启重计）
                    if self._primed and (upload or download):
                        _update_hourly_stats(
                            self.db_path,
                            datetime.now().strftime("%Y-%m-%dT%H"),
                            domain,
                            node,
                            rule,
                            upload,
                            download,
                        )

            # Detect closed connections
            closed_ids = set(self._connections.keys()) - set(current_connections.keys())
            for conn_id in closed_ids:
                conn_data = self._connections[conn_id]
                # 字节已在「发现时(首采) + 存活期增量」各记一次，关闭不再重复记全量；
                # 采样间隔内的收尾字节无法观测，属采样固有损耗

                # Check for large download (>30MB)
                if conn_data["download"] > 30 * 1024 * 1024:
                    self._record_large_download(conn_data)

                del self._connections[conn_id]

            # Update existing connections
            for conn_id, conn_data in current_connections.items():
                if conn_id in self._connections:
                    old_data = self._connections[conn_id]
                    upload_delta = conn_data["upload"] - old_data["upload"]
                    download_delta = conn_data["download"] - old_data["download"]

                    upload_delta = max(0, upload_delta)
                    download_delta = max(0, download_delta)
                    if upload_delta or download_delta:
                        # 增量入账（计数器回退截断为 0，DB 与 guard 口径一致）
                        hour = datetime.now().strftime("%Y-%m-%dT%H")
                        _update_hourly_stats(
                            self.db_path,
                            hour,
                            conn_data["domain"],
                            conn_data["node"],
                            conn_data["rule"],
                            upload_delta,
                            download_delta,
                        )
                        # guard：只累计走代理节点的增量（DIRECT 不耗机场配额）
                        if conn_data["node"] != "DIRECT":
                            self._guard_uncommitted += upload_delta + download_delta

                    self._connections[conn_id] = conn_data

            self._primed = True  # 首轮基线完成，后续新连接的首采字节才入账

        except Exception as e:
            print(f"Failed to poll connections: {e}", file=sys.stderr)

    def _record_large_download(self, conn_data: dict):
        """Record a large download (>30MB) to the database."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Calculate duration if start_time is available
            duration = None
            if conn_data.get("start_time"):
                try:
                    start = datetime.fromisoformat(
                        conn_data["start_time"].replace("Z", "+00:00")
                    )
                    duration = (datetime.now(start.tzinfo) - start).total_seconds()
                except Exception:
                    pass

            cursor.execute(
                """
                INSERT INTO large_downloads
                (timestamp, domain, node, process, process_path, source_ip, source_port,
                 destination_ip, destination_port, download_bytes, duration_seconds, rule)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    conn_data.get("domain", ""),
                    conn_data.get("node", ""),
                    conn_data.get("process", ""),
                    conn_data.get("process_path", ""),
                    conn_data.get("source_ip", ""),
                    conn_data.get("source_port", ""),
                    conn_data.get("destination_ip", ""),
                    conn_data.get("destination_port", ""),
                    conn_data.get("download", 0),
                    duration,
                    conn_data.get("rule", ""),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Failed to record large download: {e}", file=sys.stderr)

    def _check_cleanup(self):
        """Check if daily cleanup is needed."""

        today = datetime.now().strftime("%Y-%m-%d")
        current_hour = datetime.now().hour

        # Run cleanup once per day at midnight
        if current_hour == 0 and self._last_cleanup_date != today:
            cfg = _load_mgr_config()
            retention_days = cfg.get("stats", {}).get("retention_days", 180)
            _cleanup_old_data(self.db_path, retention_days)
            self._last_cleanup_date = today

            # Update daily and monthly summaries
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            _update_daily_summary(self.db_path, yesterday)

            last_month = (datetime.now() - timedelta(days=1)).strftime("%Y-%m")
            _update_monthly_summary(self.db_path, last_month)


# ── Schedule Proxy ─────────────────────────────────────────────────────────

_SCHEDULE_MANUAL_FILE = Path("~/.config/mihomo-mgr/schedule-manual.json").expanduser()

_WORK_DAY_MAP = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def _parse_work_hours(work_hours: str):
    """Parse 'HH:MM-HH:MM' into (start_hour, start_min, end_hour, end_min)."""
    try:
        parts = work_hours.split("-")
        if len(parts) != 2:
            return None
        sh, sm = parts[0].strip().split(":")
        eh, em = parts[1].strip().split(":")
        return int(sh), int(sm), int(eh), int(em)
    except (ValueError, IndexError):
        return None


def _parse_work_days(work_days: str) -> list:
    """Parse 'mon-fri' or 'mon,wed,fri' into list of weekday ints (0=Mon)."""
    work_days = work_days.strip().lower()
    if "-" in work_days and "," not in work_days:
        parts = work_days.split("-")
        if len(parts) == 2:
            start = _WORK_DAY_MAP.get(parts[0].strip())
            end = _WORK_DAY_MAP.get(parts[1].strip())
            if start is not None and end is not None:
                if start <= end:
                    return list(range(start, end + 1))
                else:
                    return list(range(start, 7)) + list(range(0, end + 1))
    days = []
    for part in work_days.split(","):
        d = _WORK_DAY_MAP.get(part.strip())
        if d is not None:
            days.append(d)
    return days


def _should_proxy_be_running() -> bool:
    """Check if proxy should be running based on schedule config."""
    cfg = _load_mgr_config()
    schedule = cfg.get("schedule", {})
    if not isinstance(schedule, dict) or not schedule.get("enabled"):
        return True  # schedule disabled = always running

    work_hours = schedule.get("work_hours", "09:00-22:00")
    work_days_str = schedule.get("work_days", "mon-fri")

    parsed = _parse_work_hours(work_hours)
    if not parsed:
        return True
    sh, sm, eh, em = parsed

    work_days = _parse_work_days(work_days_str)
    if not work_days:
        return True

    now = datetime.now()
    if now.weekday() not in work_days:
        return False

    current_minutes = now.hour * 60 + now.minute
    start_minutes = sh * 60 + sm
    end_minutes = eh * 60 + em

    return start_minutes <= current_minutes < end_minutes


def _record_manual_override(action: str):
    """Record that user manually started/stopped mihomo."""
    data = {
        "action": action,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        _SCHEDULE_MANUAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SCHEDULE_MANUAL_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _get_manual_override():
    """Read manual override. Returns (action, timestamp) or (None, None)."""
    try:
        if not _SCHEDULE_MANUAL_FILE.exists():
            return None, None
        data = json.loads(_SCHEDULE_MANUAL_FILE.read_text())
        return data.get("action"), data.get("timestamp")
    except Exception:
        return None, None


def _is_manual_override_active() -> bool:
    """Check if a manual override is still active (within current schedule period)."""
    action, ts_str = _get_manual_override()
    if not action or not ts_str:
        return False
    try:
        manual_time = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return False

    now = datetime.now()
    # Override is active if within the same schedule period boundary
    # i.e., no schedule tick has occurred since the manual action
    cfg = _load_mgr_config()
    schedule = cfg.get("schedule", {})
    work_hours = schedule.get("work_hours", "09:00-22:00")
    parsed = _parse_work_hours(work_hours)
    if not parsed:
        return False
    sh, sm, eh, em = parsed

    # If manual action was today and within the same work period, it's active
    if manual_time.date() == now.date():
        return True
    # If manual action was yesterday after end_time and now is before start_time
    # (overnight case), still active
    if manual_time.date() == (now - timedelta(days=1)).date():
        if manual_time.hour * 60 + manual_time.minute >= eh * 60 + em:
            return True
    return False


def _check_schedule():
    """Check schedule and start/stop mihomo if needed. Called from daemon."""
    cfg = _load_mgr_config()
    schedule = cfg.get("schedule", {})
    if not isinstance(schedule, dict) or not schedule.get("enabled"):
        return

    # If user manually overrode, skip auto action until next period boundary
    if _is_manual_override_active():
        return

    should_run = _should_proxy_be_running()
    paths = _get_paths()
    is_running = bool(_read_running_pid(paths["pid_file"]))

    if should_run and not is_running:
        _log_schedule_event("auto-start", "Work hours started, starting mihomo")
        _send_notification("代理自动启动", "工作时间开始，mihomo 已自动启动")
        _mihomo_start_internal(paths)
    elif not should_run and is_running:
        _log_schedule_event("auto-stop", "Outside work hours, stopping mihomo")
        _send_notification("代理自动停止", "工作时间结束，mihomo 已自动停止")
        _mihomo_stop_internal(paths)


def _mihomo_start_internal(paths):
    """Start mihomo process internally (from daemon)."""
    if _read_running_pid(paths["pid_file"]):
        return
    paths["config_dir"].mkdir(parents=True, exist_ok=True)
    paths["log_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["pid_file"].parent.mkdir(parents=True, exist_ok=True)
    policy = _routing_load()
    if policy and policy.get("enabled") and policy.get("active") and paths["config_file"].exists():
        with _publish_lock():
            policy = _routing_load(required=True)
            current = paths["config_file"].read_text()
            composed = _routing_compose(current, policy=policy)
            if composed != current:
                _routing_validate_with_core(composed, paths["config_file"])
                _atomic_write_text(paths["config_file"], composed)
    cmd = [paths["bin_path"], "-d", str(paths["config_dir"])]
    if paths["config_file"].exists():
        cmd.extend(["-f", str(paths["config_file"])])
    with paths["log_file"].open("ab") as log:
        proc = subprocess.Popen(
            cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
    paths["pid_file"].write_text(str(proc.pid) + "\n")


def _mihomo_stop_internal(paths):
    """Stop mihomo process internally (from daemon)."""
    pid = _read_pid(paths["pid_file"])
    if not pid or not _is_pid_running(pid):
        _unlink_if_exists(paths["pid_file"])
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _unlink_if_exists(paths["pid_file"])


def _log_schedule_event(event_type: str, message: str):
    """Log a schedule event to daemon log and alerts.jsonl."""
    ts = datetime.now().isoformat()
    log_line = f"{ts} [schedule] {event_type}: {message}\n"
    try:
        _DAEMON_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_DAEMON_LOG_FILE, "a") as f:
            f.write(log_line)
    except Exception:
        pass
    # Also write to alerts.jsonl
    try:
        alerts_file = Path("~/.config/mihomo-mgr/alerts.jsonl").expanduser()
        alerts_file.parent.mkdir(parents=True, exist_ok=True)
        alert = json.dumps({"time": ts, "type": event_type, "message": message})
        with open(alerts_file, "a") as f:
            f.write(alert + "\n")
    except Exception:
        pass


# ── Traffic Stats Daemon ────────────────────────────────────────────────────

_DAEMON_PID_FILE = Path("~/.config/mihomo-mgr/traffic-daemon.pid").expanduser()
_DAEMON_LOG_FILE = Path("~/.config/mihomo-mgr/traffic-daemon.log").expanduser()


def _start_traffic_daemon():
    """Start the traffic collection daemon as a background process."""
    cfg = _load_mgr_config()
    stats_cfg = cfg.get("stats", {})

    if not stats_cfg.get("enabled", True):
        return

    # Check if daemon is already running
    if _DAEMON_PID_FILE.exists():
        pid = _read_pid(_DAEMON_PID_FILE)
        if pid and _is_pid_running(pid):
            return  # Already running
        else:
            # Stale PID file
            _unlink_if_exists(_DAEMON_PID_FILE)

    # Start daemon in background
    _DAEMON_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(_DAEMON_LOG_FILE, "a") as log_file:
        proc = subprocess.Popen(
            [sys.executable, __file__, "__stats_daemon"],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )

    _DAEMON_PID_FILE.write_text(str(proc.pid))


def _stop_traffic_daemon():
    """Stop the traffic collection daemon."""
    if not _DAEMON_PID_FILE.exists():
        return False

    pid = _read_pid(_DAEMON_PID_FILE)
    if not pid or not _is_pid_running(pid):
        _unlink_if_exists(_DAEMON_PID_FILE)
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for graceful shutdown
        for _ in range(10):
            if not _is_pid_running(pid):
                break
            time.sleep(0.1)
        else:
            # Force kill
            os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass

    _unlink_if_exists(_DAEMON_PID_FILE)
    return True


def _traffic_daemon_status():
    """Get traffic daemon status."""
    if not _DAEMON_PID_FILE.exists():
        return {"running": False, "pid": None}

    pid = _read_pid(_DAEMON_PID_FILE)
    if pid and _is_pid_running(pid):
        return {"running": True, "pid": pid}
    else:
        return {"running": False, "pid": None, "stale": True}


def _run_traffic_daemon():
    """Run the traffic daemon (called from subprocess)."""
    # Set up signal handlers
    collector = None

    def signal_handler(signum, frame):
        if collector:
            collector.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        cfg = _load_mgr_config()
        stats_cfg = cfg.get("stats", {})
        poll_interval = stats_cfg.get("poll_interval", 5)

        collector = _TrafficCollector(poll_interval=poll_interval)
        collector.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Traffic daemon error: {e}", file=sys.stderr)
        sys.exit(1)


def _read_pid(pid_file):
    try:
        raw = pid_file.read_text().strip()
        return int(raw) if raw else None
    except (FileNotFoundError, ValueError):
        return None


def _read_running_pid(pid_file):
    pid = _read_pid(pid_file)
    return pid if pid and _is_pid_running(pid) else None


def _is_pid_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _unlink_if_exists(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _missing_db_files(names):
    config_dir = _get_paths()["config_dir"]
    return [name for name in names if not (config_dir / name).exists()]


def _selected_db_files(args):
    if getattr(args, "all", False):
        return list(DB_FILES.keys())
    names = list(DEFAULT_DB_FILES)
    if getattr(args, "geodata", False):
        names.append("geoip.dat")
    if getattr(args, "asn", False):
        names.append("GeoLite2-ASN.mmdb")
    return names


def _binary_exists(bin_path):
    path = Path(bin_path).expanduser()
    if path.parent != Path("."):
        return path.exists() and os.access(path, os.X_OK)
    return shutil.which(bin_path) is not None


def _download_db_files(names):
    config_dir = _get_paths()["config_dir"]
    config_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    for name in names:
        target = config_dir / name
        urls = DB_FILES[name]
        for url in urls:
            try:
                print(f"Downloading {name}: {url}")
                tmp = target.with_suffix(target.suffix + ".tmp")
                with urllib.request.urlopen(url, timeout=30) as resp:
                    tmp.write_bytes(resp.read())
                tmp.replace(target)
                print(f"Saved {target}")
                break
            except Exception as e:
                print(f"  failed: {e}", file=sys.stderr)
        else:
            failed.append(name)
    if failed:
        print(f"Failed to download: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)


def _proxy_values(args):
    cfg = _load_mgr_config()
    # 配置已提供完整端口和主机时跳过 mihomo API（避免未运行时 10s 超时）
    _has_port = _cfg_value(cfg, "mixed_port") or (
        _cfg_value(cfg, "proxy_http_port") and _cfg_value(cfg, "proxy_socks_port")
    )
    if _has_port and _cfg_value(cfg, "proxy_host"):
        mihomo_cfg = {}
    else:
        mihomo_cfg = _get_mihomo_config_quiet()
    host = (
        args.host
        or _cfg_value(cfg, "proxy_host")
        or _proxy_host_from_mihomo(mihomo_cfg)
        or DEFAULT_PROXY_HOST
    )
    http_port = str(
        args.http_port
        or _cfg_value(cfg, "mixed_port")
        or _cfg_value(cfg, "proxy_http_port")
        or _proxy_http_port_from_mihomo(mihomo_cfg)
        or DEFAULT_HTTP_PROXY_PORT
    )
    socks_port = str(
        args.socks_port
        or _cfg_value(cfg, "mixed_port")
        or _cfg_value(cfg, "proxy_socks_port")
        or _proxy_socks_port_from_mihomo(mihomo_cfg)
        or DEFAULT_SOCKS_PROXY_PORT
    )
    no_proxy = args.no_proxy or _cfg_value(cfg, "no_proxy", DEFAULT_NO_PROXY)
    http_url = args.http or _cfg_value(cfg, "proxy_http", f"http://{host}:{http_port}")
    socks_url = args.socks or _cfg_value(
        cfg, "proxy_socks", f"socks5://{host}:{socks_port}"
    )
    return http_url, socks_url, no_proxy


def _get_mihomo_config_quiet():
    try:
        return api("GET", "/configs", quiet=True)
    except SystemExit:
        return {}


def _proxy_host_from_mihomo(cfg):
    bind = cfg.get("bind-address") or cfg.get("interface-name") or ""
    if bind and bind not in ("*", "0.0.0.0", "::"):
        return bind
    return None


def _proxy_http_port_from_mihomo(cfg):
    return cfg.get("mixed-port") or cfg.get("port")


def _proxy_socks_port_from_mihomo(cfg):
    return cfg.get("mixed-port") or cfg.get("socks-port")


def _shell_quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _fetch_subscription(url, proxy_port=None):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "mihomo-mgr/1.0",
            "Accept": "text/yaml,application/yaml,text/plain,*/*",
        },
    )
    if proxy_port:
        proxy_url = f"http://127.0.0.1:{proxy_port}"
        proxy_handler = urllib.request.ProxyHandler(
            {
                "http": proxy_url,
                "https": proxy_url,
            }
        )
        opener = urllib.request.build_opener(proxy_handler)
        open_fn = opener.open
    else:
        open_fn = urllib.request.urlopen
    try:
        with open_fn(req, timeout=30) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        print(f"Subscription fetch failed: {e}", file=sys.stderr)
        sys.exit(1)
    return data.decode("utf-8-sig", errors="replace")


def _build_config_updates(cfg):
    """构建 config.yaml 的覆盖项（mixed-port、bind-address 等）。"""
    host = _cfg_value(cfg, "proxy_host", DEFAULT_PROXY_HOST)
    mixed_port = (
        _cfg_value(cfg, "mixed_port")
        or _cfg_value(cfg, "proxy_http_port")
        or _cfg_value(cfg, "proxy_socks_port")
        or DEFAULT_HTTP_PROXY_PORT
    )
    api_url = _cfg_value(cfg, "api", DEFAULT_HTTP)
    controller = _controller_from_api(api_url)
    secret = _cfg_value(cfg, "secret", "")

    updates = {
        "mixed-port": str(mixed_port),
        "bind-address": _yaml_quote(host),
        "external-controller": _yaml_quote(controller),
    }
    if secret:
        updates["secret"] = _yaml_quote(secret)
    return updates


def _normalize_subscription_config(raw, cfg):
    updates = _build_config_updates(cfg)
    # sub-pull 额外覆盖策略性设置
    updates["port"] = None
    updates["socks-port"] = None
    updates["allow-lan"] = "false"
    result = _update_top_level_yaml(raw, updates)
    result = _inject_direct_rules(result, cfg)
    result = _apply_health_check_url(result, cfg)
    result = _routing_compose(result)
    return result


def _get_watch_group_names() -> set:
    """Return set of watch-managed url-test group names from overlay."""
    try:
        content = _read_overlay("watch-groups.yaml")
        if not content:
            return set()
        import yaml

        data = yaml.safe_load(content)
        name = data.get("group_name", "")
        # Strip surrounding quotes if present
        return {name.strip('"').strip("'")} if name else set()
    except Exception:
        return set()


def _apply_health_check_url(raw, cfg):
    """Apply health_check_url from mihomo-mgr config to all url-test groups.

    Watch-managed url-test groups (from best --watch) are skipped because
    their URL is controlled by the watch overlay.
    """
    health_check_url = cfg.get("health_check_url")
    if not health_check_url:
        return raw

    # Parse YAML to modify url-test groups
    import yaml

    try:
        config = yaml.safe_load(raw)
        if not config or "proxy-groups" not in config:
            return raw

        watch_groups = _get_watch_group_names()
        modified = False
        for group in config["proxy-groups"]:
            if group.get("type") == "url-test":
                if group.get("name") in watch_groups:
                    continue
                if group.get("url") != health_check_url:
                    group["url"] = health_check_url
                    modified = True

        if modified:
            return yaml.dump(config, default_flow_style=False, allow_unicode=True)
        return raw
    except Exception:
        return raw


def _inject_direct_rules(raw, cfg):
    """Migrate direct rules to overlay system."""
    # Once routing.json exists, its draft/active snapshots are the sole source
    # of local direct rules.  Do not resurrect removed migrated entries.
    if _routing_path().exists():
        return raw
    domains = cfg.get("direct_domains") or []
    if not domains:
        # Remove overlay if no domains
        _delete_overlay("direct-rules.yaml")
        return raw

    # Write to overlay file
    overlay_content = "payload:\n"
    for domain in domains:
        domain = domain.strip()
        if domain:
            overlay_content += f"  - DOMAIN-SUFFIX,{domain},🎯 全球直连\n"
    _write_overlay("direct-rules.yaml", overlay_content)

    # Return raw unchanged - _reapply_overlays() will inject the reference
    return raw


def _update_top_level_yaml(raw, updates):
    lines = raw.splitlines()
    found = set()
    out = []
    for line in lines:
        key = _top_level_yaml_key(line)
        if key in updates:
            if updates[key] is not None:
                out.append(f"{key}: {updates[key]}")
            found.add(key)
        else:
            out.append(line)

    missing = [key for key in updates if key not in found and updates[key] is not None]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# Generated by mihomo-mgr")
        for key in missing:
            out.append(f"{key}: {updates[key]}")
    return "\n".join(out).rstrip() + "\n"


def _top_level_yaml_key(line):
    if not line or line[0].isspace() or line.lstrip().startswith("#"):
        return None
    if ":" not in line:
        return None
    key = line.split(":", 1)[0].strip()
    return key or None


def _patch_config_yaml_unlocked(cfg, paths):
    """启动前把 config.json 的可配置参数同步写入现有 config.yaml。

    覆盖 config-set 管理的 key，同时移除与 mixed-port 冲突的 port/socks-port。
    不动 allow-lan / mode 等策略性设置。
    返回是否发生了修改。
    """
    config_file = paths["config_file"]
    if not config_file.exists():
        return False
    raw = config_file.read_text()

    updates = _build_config_updates(cfg)
    # 移除与 mixed-port 冲突的独立端口
    updates["port"] = None
    updates["socks-port"] = None

    patched = _update_top_level_yaml(raw, updates)
    patched = _routing_compose(patched)
    if patched != raw:
        if _routing_has_active():
            _routing_validate_with_core(patched, config_file)
        _atomic_write_text(config_file, patched)
        return True
    return False


def _patch_config_yaml(cfg, paths):
    with _publish_lock():
        return _patch_config_yaml_unlocked(cfg, paths)


def _yaml_quote(value):
    value = str(value)
    if not value:
        return '""'
    if all(c.isalnum() or c in ".:_-/" for c in value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _controller_from_api(api_url):
    parsed = urllib.parse.urlparse(api_url)
    if parsed.netloc:
        return parsed.netloc
    return api_url.replace("http://", "").replace("https://", "").strip("/")


def _redact_url(url):
    parsed = urllib.parse.urlparse(url)
    if not parsed.query and not parsed.password:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    redacted = parsed._replace(netloc=netloc, query="<redacted>")
    return urllib.parse.urlunparse(redacted)


def _file_status(path):
    if not path.exists():
        return "missing"
    size = path.stat().st_size
    mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
    return f"{size} bytes, updated {mtime}"


def _tail(path, lines):
    if lines <= 0:
        return []
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        block_size = 8192
        data = b""
        while end > 0 and data.count(b"\n") <= lines:
            step = min(block_size, end)
            end -= step
            f.seek(end)
            data = f.read(step) + data
        return [
            line.decode(errors="replace")
            for line in data.splitlines(keepends=True)[-lines:]
        ]


def _find_mihomo_processes():
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return []

    current_pid = os.getpid()
    results = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        comm = parts[1]
        cmd = parts[2] if len(parts) > 2 else comm
        if pid == current_pid or "mihomo-mgr.py" in cmd:
            continue
        if comm == "mihomo" or cmd.endswith("/mihomo") or " mihomo " in f" {cmd} ":
            results.append({"pid": pid, "cmd": cmd})
    return results


# ── Help ────────────────────────────────────────────────────────────


def _get_api_groups():
    """Fetch proxy group names from mihomo API (returns empty list if unavailable)."""
    try:
        data = api("GET", "/proxies", quiet=True)
    except SystemExit:
        return []
    proxies = data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    return sorted(k for k, v in proxies.items() if v.get("type") in group_types)


def _get_api_nodes(group):
    """Fetch node names in a group from mihomo API (returns empty list if unavailable)."""
    try:
        data = api("GET", f"/proxies/{_urlencode(group)}", quiet=True)
    except SystemExit:
        return []
    return sorted(data.get("all") or []) if "all" in data else []


def _get_all_api_nodes():
    """Fetch all node names from mihomo API (returns empty list if unavailable)."""
    try:
        data = api("GET", "/proxies", quiet=True)
    except SystemExit:
        return []
    proxies = data.get("proxies") or {}
    group_types = ("Selector", "URLTest", "Fallback", "LoadBalance")
    all_nodes = set()
    for k, v in proxies.items():
        if v.get("type") in group_types:
            for n in v.get("all") or []:
                all_nodes.add(n)
    return sorted(all_nodes)


# Map of commands to their completion logic:
# key → (arg_index, completer_type)
# completer_type: "group" | "node" | "all_nodes" | "mode" | None
_COMPLETE_MAP = {
    "nodes": [(1, "group")],
    "select": [(1, "group"), (2, "node")],
    "best": [(1, "group")],
    "delay": [(1, "all_nodes")],
    "delay-group": [(1, "group")],
    "mode": [(1, "mode")],
}


def cmd_completion(args):
    """Generate shell completion script."""
    script_path = os.path.abspath(sys.argv[0])
    # Subcommands and dynamic completions — keep in sync with dispatch
    subcmds = " ".join(
        sorted(
            [
                "status",
                "mode",
                "groups",
                "nodes",
                "select",
                "best",
                "delay",
                "delay-group",
                "conns",
                "conns-close",
                "rules",
                "dns",
                "flush-dns",
                "api-restart",
                "upgrade-geo",
                "db-check",
                "db-download",
                "start",
                "stop",
                "restart",
                "logs",
                "logs-clear",
                "sub-pull",
                "sub-import",
                "sub-show",
                "routing",
                "gfwlist",
                "config",
                "config-init",
                "config-set",
                "config-clear",
                "proxy-status",
                "proxy-on",
                "proxy-off",
                "completion",
            ]
        )
    )
    dynamic_cmds = "nodes|select|best|delay|delay-group|mode"

    bash_script = f"""# mihomo-mgr bash completion — source this file or add to ~/.bashrc
_mihomo_mgr_complete() {{
    local cur prev words cword cmd result
    COMPREPLY=()
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    # Collect non-flag words as positional args
    words=()
    for w in "${{COMP_WORDS[@]:1}}"; do
        [[ "$w" != -* ]] && words+=("$w")
    done

    cmd="${{words[0]:-}}"

    # First word: subcommand
    if [[ ${{#words[@]}} -eq 0 || ( ${{#words[@]}} -eq 1 && -z "$cur" ) ]]; then
        COMPREPLY=($(compgen -W "{subcmds}" -- "$cur"))
        return
    fi

    # Dynamic completion via API for known commands
    case "$cmd" in
        {dynamic_cmds})
            result=$({script_path} __complete "$cmd" "${{words[@]:1}}" 2>/dev/null)
            if [[ -n "$result" ]]; then
                COMPREPLY=($(compgen -W "$result" -- "$cur"))
            fi
            ;;
    esac
}}
complete -F _mihomo_mgr_complete {script_path}
complete -F _mihomo_mgr_complete mihomo-mgr.py
"""

    zsh_script = f"""# mihomo-mgr zsh completion — source this file or add to ~/.zshrc
_mihomo_mgr_complete() {{
    local -a words
    words=(${{(@)words:#-*}})
    local cmd="${{words[1]:-}}"

    if [[ -z "$cmd" ]]; then
        local cmds=({subcmds})
        _describe 'command' cmds
        return
    fi

    case "$cmd" in
        {dynamic_cmds})
            local result
            result=$({script_path} __complete "$cmd" "${{words[@]:2}}" 2>/dev/null)
            if [[ -n "$result" ]]; then
                local -a candidates
                candidates=(${{(f)result}})
                _describe 'value' candidates
            fi
            ;;
    esac
}}
compdef _mihomo_mgr_complete {script_path}
compdef _mihomo_mgr_complete mihomo-mgr.py
"""

    if args.shell == "bash":
        print(bash_script)
        print("# Install: source <(mihomo-mgr.py completion bash)")
    elif args.shell == "zsh":
        print(zsh_script)
        print("# Install: source <(mihomo-mgr.py completion zsh)")


def cmd_internal_complete(args):
    """Internal completion handler (hidden from help, used by shell completion)."""
    cmd = args.complete_cmd
    # Get all positional args after the command (stripping flags)
    positional = [a for a in args.complete_args if not a.startswith("-")]
    arg_index = len(positional)

    spec = _COMPLETE_MAP.get(cmd, [])
    candidates = []
    for idx, ctype in spec:
        if arg_index == idx:
            if ctype == "group":
                candidates = _get_api_groups()
            elif ctype == "node":
                group_name = positional[0] if positional else ""
                candidates = _get_api_nodes(group_name) if group_name else []
            elif ctype == "all_nodes":
                candidates = _get_all_api_nodes()
            elif ctype == "mode":
                candidates = ["rule", "global", "direct"]
            break

    for c in candidates:
        print(c)


CMD_GROUPS = OrderedDict(
    [
        (
            "Status & Monitoring",
            [
                ("status", "Show overall process and proxy status"),
                ("mode", "Get/set proxy mode (rule|global|direct)"),
                ("groups", "List all proxy groups"),
                ("nodes", "List nodes in a group"),
                ("conns", "List active connections"),
                ("rules", "List routing rules"),
                ("dns", "Query DNS resolution"),
                ("logs", "Show recent mihomo logs"),
                ("logs-clear", "Clear or trim the mihomo log file"),
            ],
        ),
        (
            "Control",
            [
                ("select", "Switch node in a proxy group"),
                ("best", "Auto-select fastest node matching keywords"),
                ("delay", "Test node delay"),
                ("delay-group", "Test all nodes in a group"),
                ("conns-close", "Close connections"),
                ("flush-dns", "Flush DNS cache"),
            ],
        ),
        (
            "Process",
            [
                ("start", "Start mihomo in background"),
                ("stop", "Stop mihomo gracefully"),
                ("restart", "Restart mihomo process"),
            ],
        ),
        (
            "Configuration",
            [
                ("config", "Show persisted and effective config"),
                ("config-init", "Create editable default config file"),
                ("config-set", "Persist configuration values"),
                ("config-clear", "Remove persisted configuration"),
                ("routing", "Manage local direct/proxy routing policy"),
                ("gfwlist", "Manage the GFWList base routing layer"),
            ],
        ),
        (
            "Subscription",
            [
                ("sub-pull", "Pull subscription and generate config.yaml"),
                ("sub-import", "Import a local YAML file as subscription"),
                ("sub-show", "Show subscription cache status"),
            ],
        ),
        (
            "Database",
            [
                ("db-check", "Check required DB files"),
                ("db-download", "Download DB files"),
            ],
        ),
        (
            "Terminal Proxy",
            [
                ("proxy-status", "Show current terminal proxy vars"),
                ("proxy-on", "Print shell exports to enable proxy"),
                ("proxy-off", "Print shell commands to disable proxy"),
            ],
        ),
        (
            "Maintenance",
            [
                ("api-restart", "Restart mihomo core via API"),
                ("upgrade-geo", "Update GeoIP/GeoSite databases"),
                ("completion", "Generate shell completion script"),
            ],
        ),
    ]
)

HELP_EXAMPLES = [
    ("Show overall status", "mihomo-mgr.py status"),
    ("Switch proxy node", 'mihomo-mgr.py select "\U0001f680 节点选择" "S-IEPL-香港7"'),
    (
        "Auto-select fastest JP/US node",
        'mihomo-mgr.py best "\U0001f680 节点选择" 日本 美国',
    ),
    (
        "Watch & auto-failover JP/US nodes",
        'mihomo-mgr.py best "\U0001f680 节点选择" 日本 美国 --watch',
    ),
    ("List active watch groups", "mihomo-mgr.py best --list"),
    (
        "Switch to watch group",
        'mihomo-mgr.py best "\U0001f680 节点选择" 日本 美国 --switch',
    ),
    ("Enable terminal proxy", 'eval "$(mihomo-mgr.py proxy-on)"'),
    ("Disable terminal proxy", 'eval "$(mihomo-mgr.py proxy-off)"'),
    ("Start mihomo", "mihomo-mgr.py start"),
    ("Configure bin path", "mihomo-mgr.py config-set --bin ~/clash/mihomo"),
    ("Pull subscription", 'mihomo-mgr.py sub-pull --url "https://..."'),
    ("Download required DB files", "mihomo-mgr.py db-download"),
    ("Show per-command help", "mihomo-mgr.py CMD --help"),
]


def _print_help(cmd=None):
    """Print user-friendly help with grouped commands and examples."""
    if cmd:
        subprocess.run([sys.executable, sys.argv[0], cmd, "--help"])
        return

    print("mihomo-mgr – manage a mihomo core process and control it via API")
    print()
    print("Usage: mihomo-mgr.py [GLOBAL-FLAGS] COMMAND [ARGS...]")
    print()
    print("Global flags:")
    print("  --sock PATH       Unix socket path for API")
    print("  --api URL         HTTP API URL (default: http://127.0.0.1:9090)")
    print("  --secret SECRET   API secret")
    print("  --config-dir DIR  mihomo config directory")
    print("  --bin-dir DIR     directory containing mihomo binary")
    print("  --bin PATH        mihomo binary path or command")
    print("  --log-file PATH   mihomo log file")
    print("  --pid-file PATH   mihomo pid file")
    print("  --version          show version and exit")
    print()
    print("Commands:")

    for group, cmds in CMD_GROUPS.items():
        print(f"  {group}:")
        for name, desc in cmds:
            print(f"    {name:<20}  {desc}")
        print()

    print("Quick examples:")
    for desc, example in HELP_EXAMPLES:
        print(f"  # {desc}")
        print(f"  $ {example}")
        print()
    print("Configuration:  ~/.config/mihomo-mgr/config.json")
    print("Use 'mihomo-mgr.py CMD --help' for per-command flags.")


# ── Main ─────────────────────────────────────────────────────────────


# 中文快捷方式映射
SHORTCUTS = {
    # 中文动词 → 命令
    "切换": "best",
    "选": "best",
    "测速": "delay",
    "测试": "delay",
    "列表": "nodes",
    "节点": "nodes",
    "状态": "status",
    "连接": "conns",
    "日志": "logs",
    "订阅": "sub",
    "配置": "config",
    "代理": "proxy",
    "启动": "start",
    "停止": "stop",
    "重启": "restart",
    "选择": "pick",
    # 英文简写
    "p": "pick",
    "s": "status",
    "st": "status",
    "g": "groups",
    "n": "nodes",
    "sw": "select",
    "b": "best",
    "d": "delay",
    "c": "conns",
    "l": "logs",
}


def _preprocess_args():
    """智能快捷方式预处理。

    转换规则：
    - 无参数 → status
    - 第一个参数是中文快捷 → 转换为对应命令
    - mm 节点 → mm nodes 节点
    - mm 切换 香港 → mm best 节点 香港
    - mm 测速 → mm delay 节点
    """
    args = sys.argv[1:]

    # 无参数 → status
    if not args:
        return ["status"]

    # 跳过全局选项（--sock, --api 等）
    first_arg_idx = 0
    for i, arg in enumerate(args):
        if not arg.startswith("-"):
            first_arg_idx = i
            break
    else:
        # 全是选项，没有命令
        return args

    first_arg = args[first_arg_idx]

    # 检查是否是快捷方式
    if first_arg in SHORTCUTS:
        cmd = SHORTCUTS[first_arg]
        rest = args[:first_arg_idx] + args[first_arg_idx + 1 :]

        # 特殊处理："切换 xxx" → "best 节点 xxx"
        if first_arg in ("切换", "选") and rest:
            # 尝试找到默认组
            return [cmd, "节点"] + rest

        # 特殊处理："测速" → "delay 节点"
        if first_arg == "测速" and not rest:
            return [cmd, "节点"]

        # 特殊处理："节点"/"列表" 无参数 → "nodes 节点"
        if first_arg in ("节点", "列表") and not rest:
            return [cmd, "节点"]

        return [cmd] + rest

    return args


def main():
    # 智能快捷方式预处理
    sys.argv = [sys.argv[0]] + _preprocess_args()

    # 内部补全命令：在 argparse 之前处理，不暴露给用户
    if len(sys.argv) >= 2 and sys.argv[1] == "__complete":
        ns = argparse.Namespace(
            complete_cmd=sys.argv[2] if len(sys.argv) > 2 else "",
            complete_args=sys.argv[3:] if len(sys.argv) > 3 else [],
        )
        cmd_internal_complete(ns)
        return

    # 内部守护进程命令：在 argparse 之前处理，不暴露给用户
    if len(sys.argv) >= 2 and sys.argv[1] == "__stats_daemon":
        _run_traffic_daemon()
        return

    p = argparse.ArgumentParser(description="mihomo-mgr - control mihomo via API")
    p.add_argument("--sock", help="Unix socket path")
    p.add_argument("--api", help=f"HTTP API URL (default: {DEFAULT_HTTP})")
    p.add_argument("--secret", help="API secret")
    p.add_argument("--config-dir", help="mihomo config directory")
    p.add_argument("--bin-dir", help="directory containing the mihomo binary")
    p.add_argument("--bin", help="mihomo binary path or command")
    p.add_argument("--log-file", help="mihomo log file")
    p.add_argument("--pid-file", help="mihomo pid file")
    p.add_argument("--version", action="version", version=f"mihomo-mgr {VERSION}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser(
        "pick",
        help="Interactive picker for groups and nodes",
        description="Interactive picker with two-level menu:\n"
        "  1. Select group → 2. Group actions → 3. Select node → 4. Node actions\n\n"
        "Group actions:\n"
        "  • Select node (switch/test/details)\n"
        "  • Test all nodes delay\n"
        "  • Auto-select fastest node (with keyword filter)\n"
        "  • View group details\n\n"
        "Node actions:\n"
        "  • Switch to this node\n"
        "  • Test delay\n"
        "  • View details\n\n"
        "All lists support:\n"
        "  • Keyword filtering (e.g.: 节点, 香港, IEPL)\n"
        "  • Regex with /pattern/ syntax (e.g.: /IEPL.*港/)\n"
        "  • Number selection (e.g.: 1, 2, 3)\n"
        "  • q to go back or quit",
        epilog="Examples:\n"
        "  mihomo-mgr.py pick\n"
        '  # 1. Type "节点" to filter groups → select "🚀 节点选择"\n'
        '  # 2. Choose [3] auto-select fastest → type "香港" → auto-pick fastest HK node\n'
        '  # 3. Or choose [1] select node → type "/IEPL.*港2/" → switch to it',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s = sub.add_parser(
        "guard",
        help="Traffic circuit breaker (trip to direct on burst)",
        description="流量熔断器：滚动 60 分钟代理流量超过阈值（默认 月配额×10%）时，"
        "切 direct 模式并断开全部连接，持续 disable_hours 后自动恢复。\n"
        "由 stats daemon 内置执行（mm stats daemon 启动）；DIRECT 直连不计入。\n"
        "阈值通过 config-set --guard-* 调整。",
        epilog="Examples:\n  mihomo-mgr.py guard            # 查看状态\n"
        "  mihomo-mgr.py guard release    # 手动解除熔断\n"
        "  mihomo-mgr.py guard trip       # 强制触发（测试）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["status", "release", "report", "test", "trip", "check"],
        help="action (default: status)",
    )

    s = sub.add_parser(
        "status",
        help="Show overall process and proxy status",
        description="Display mihomo process status, version, mode, TUN, traffic, connection count, and proxy group selections.",
        epilog="Examples:\n  mihomo-mgr.py status\n  mihomo-mgr.py status --json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--json", action="store_true", help="Output in JSON format")

    s = sub.add_parser(
        "mode",
        help="Get/set proxy mode (rule|global|direct)",
        description="Get or set the proxy mode. When a value is given, updates it via the API. Otherwise prints the current mode.",
        epilog="Examples:\n  mihomo-mgr.py mode          # Show current mode\n  mihomo-mgr.py mode global   # Switch to global mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "value",
        nargs="?",
        choices=["rule", "global", "direct"],
        help="proxy mode to set (omit to show current)",
    )

    sub.add_parser(
        "groups",
        help="List all proxy groups with current node",
        description="List all proxy groups with their current node selection and node count.",
        epilog="Examples:\n  mihomo-mgr.py groups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s = sub.add_parser(
        "nodes",
        help="List nodes in a group with delay info",
        description="List all nodes in a proxy group, showing their current selection and last-known delay.\n"
        "Group name supports partial match: '节点' matches '🚀 节点选择'.\n"
        "With --regex, group name and --filter patterns are treated as regex.",
        epilog="Examples:\n"
        '  mihomo-mgr.py nodes "节点"                    # partial match\n'
        '  mihomo-mgr.py nodes "节点" --filter 香港 日本\n'
        '  mihomo-mgr.py nodes "节点" --filter "IEPL.*港" --regex',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("group", help="Group name (partial match supported)")
    s.add_argument(
        "--filter",
        nargs="+",
        metavar="PATTERN",
        help="Filter nodes by keyword or regex (use --regex for regex mode)",
    )
    s.add_argument(
        "--regex",
        action="store_true",
        help="Treat group name and --filter patterns as regular expressions",
    )

    s = sub.add_parser(
        "select",
        help="Switch node in a proxy group",
        description="Switch a proxy group to use a different node.\n"
        "Group name supports partial match: '节点' matches '🚀 节点选择'.\n"
        "With --regex, node name is treated as regex; first match is selected.",
        epilog="Examples:\n"
        '  mihomo-mgr.py select "节点" "S-IEPL-香港7"     # partial group match\n'
        '  mihomo-mgr.py select "节点" "IEPL.*港" --regex  # regex node match',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("group", help="Group name (partial match supported)")
    s.add_argument("node", help="Node name (or regex pattern with --regex)")
    s.add_argument(
        "--regex", action="store_true", help="Treat node name as regex pattern"
    )

    s = sub.add_parser(
        "best",
        help="Auto-select fastest node matching keywords",
        description="Filter nodes in a proxy group by one or more keywords (region names)\n"
        "or regex patterns (--regex), test their delays concurrently, and\n"
        "automatically select the fastest one.\n"
        "Group name supports partial match: '节点' matches '🚀 节点选择'.\n"
        "With --regex, keywords are treated as regex patterns.\n"
        "Keywords are matched case-insensitively against node names.\n\n"
        "With --watch, creates a url-test proxy group in config.yaml with the\n"
        "filtered nodes, reloads mihomo, and lets the native url-test mechanism\n"
        "handle health checks and failover — no external polling needed.\n"
        "Use --watch-off to remove the url-test group and restore the original.",
        epilog="Examples:\n"
        '  mihomo-mgr.py best "节点" 日本 美国           # partial group match\n'
        '  mihomo-mgr.py best "节点" "IEPL.*港" --regex  # regex node filter\n'
        '  mihomo-mgr.py best "节点" 香港 --timeout 3000\n'
        '  mihomo-mgr.py best "节点" 日本 美国 --watch\n'
        "  mihomo-mgr.py best --list\n"
        '  mihomo-mgr.py best "节点" 日本 美国 --switch\n'
        '  mihomo-mgr.py best "节点" --watch-off\n'
        '  mihomo-mgr.py best "节点" 日本 --dry-run',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "group", nargs="?", help="Proxy group name (partial match supported)"
    )
    s.add_argument(
        "keywords", nargs="*", help="Region keywords or regex patterns (with --regex)"
    )
    s.add_argument(
        "--regex", action="store_true", help="Treat keywords as regular expressions"
    )
    s.add_argument(
        "--url", help="Test URL (default: http://www.gstatic.com/generate_204)"
    )
    s.add_argument(
        "--timeout", type=int, help="Delay test timeout in ms (default: 5000)"
    )
    s.add_argument(
        "--concurrency", type=int, help="Max concurrent requests (default: 10)"
    )
    s.add_argument(
        "--dry-run", action="store_true", help="Only show results, do not switch node"
    )
    s.add_argument(
        "--watch",
        action="store_true",
        help="Create a url-test group in config and let mihomo handle failover natively",
    )
    s.add_argument(
        "--watch-off",
        action="store_true",
        help="Remove the watch url-test group and restore original selection",
    )
    s.add_argument(
        "--list",
        action="store_true",
        help="List all active watch groups and their status",
    )
    s.add_argument(
        "--switch",
        action="store_true",
        help='Switch to an existing watch group (e.g. best "group" 日本 美国 --switch)',
    )
    s.add_argument(
        "--interval",
        type=int,
        metavar="SECS",
        help="Health check interval for url-test group in seconds (default: 15)",
    )
    s.add_argument(
        "--tolerance",
        type=int,
        metavar="MS",
        help="Latency tolerance in ms to prevent flapping (default: 50)",
    )
    s.add_argument(
        "--health-timeout",
        type=int,
        metavar="MS",
        help="Health check timeout per node in ms (default: 2000)",
    )

    s = sub.add_parser(
        "delay",
        help="Test latency of a node or group (auto-detect)",
        description="Test the latency of a single node or all nodes in a group.\n"
        "Auto-detects whether target is a node or group name.\n"
        "Group name supports partial match: '节点' matches '🚀 节点选择'.\n"
        "With --regex, target is treated as a regex pattern for group matching.",
        epilog="Examples:\n"
        '  mihomo-mgr.py delay "S-IEPL-香港7"     # single node\n'
        '  mihomo-mgr.py delay "节点"              # all nodes in group\n'
        '  mihomo-mgr.py delay "日本.*美国" --regex  # regex group match\n'
        "  mihomo-mgr.py delay DIRECT --timeout 2000",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("target", help="Node or group name (partial match for groups)")
    s.add_argument("--url", help="Test URL")
    s.add_argument("--timeout", type=int, help="Timeout in ms (default: 1000)")
    s.add_argument(
        "--concurrency",
        type=int,
        help="Max concurrent requests for group test (default: 10)",
    )
    s.add_argument(
        "--regex", action="store_true", help="Treat target as regex for group matching"
    )

    s = sub.add_parser(
        "delay-group",
        help="Test latency of all nodes in a group",
        description="Test the latency of all nodes in a proxy group, sorted fastest first.\n"
        "Group name supports partial match: '节点' matches '🚀 节点选择'.",
        epilog="Examples:\n"
        '  mihomo-mgr.py delay-group "节点"             # partial match\n'
        '  mihomo-mgr.py delay-group "节点" --regex      # regex match',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("group", help="Group name (partial match supported)")
    s.add_argument(
        "--regex", action="store_true", help="Treat group name as a regex pattern"
    )
    s.add_argument("--url", help="Test URL")
    s.add_argument("--timeout", type=int, help="Timeout in ms (default: 1000)")
    s.add_argument(
        "--concurrency", type=int, help="Max concurrent requests (default: 10)"
    )

    s = sub.add_parser(
        "conns",
        help="List active connections with traffic info",
        description="List active connections showing source, destination, rule, chain, and traffic statistics.",
        epilog="Examples:\n  mihomo-mgr.py conns\n  mihomo-mgr.py conns --limit 50",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--limit", type=int, help="Max connections to show (default: 20)")

    s = sub.add_parser(
        "conns-close",
        help="Close one or all connections",
        description="Close a single connection by ID, or all active connections if no ID is given.",
        epilog="Examples:\n  mihomo-mgr.py conns-close         # Close all\n  mihomo-mgr.py conns-close --id 42  # Close one",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--id", help="Connection ID (omit to close all)")

    s = sub.add_parser(
        "rules",
        help="List routing rules",
        description="List routing rules showing type, payload, and target proxy.\nThese rules determine how traffic is matched and routed.",
        epilog="Examples:\n  mihomo-mgr.py rules\n  mihomo-mgr.py rules --limit 100",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--limit", type=int, help="Max rules to show (default: 30)")

    s = sub.add_parser(
        "dns",
        help="Query DNS through mihomo",
        description="Query DNS resolution through mihomo's internal DNS resolver.",
        epilog="Examples:\n  mihomo-mgr.py dns google.com\n  mihomo-mgr.py dns google.com --type AAAA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("domain", help="Domain to query")
    s.add_argument("--type", default="A", help="Record type (default: A)")

    sub.add_parser(
        "flush-dns",
        help="Flush DNS cache",
        description="Clear mihomo's internal DNS cache. Useful after upstream DNS changes.",
        epilog="Examples:\n  mihomo-mgr.py flush-dns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub.add_parser(
        "api-restart",
        help="Restart mihomo core via API",
        description="Restart the mihomo core process via its external controller API.\nDoes not restart the OS-level process; use 'restart' for that.",
        epilog="Examples:\n  mihomo-mgr.py api-restart",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub.add_parser(
        "upgrade-geo",
        help="Update GeoIP/GeoSite databases",
        description="Trigger an update of GeoIP and GeoSite databases through the mihomo API.",
        epilog="Examples:\n  mihomo-mgr.py upgrade-geo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s = sub.add_parser(
        "db-check",
        help="Check required database files",
        description="Check if required database files (country.mmdb, geosite.dat) are present.\nUse --download to fetch missing ones, --geodata/--asn/--all to include optional files.",
        epilog="Examples:\n  mihomo-mgr.py db-check\n  mihomo-mgr.py db-check --download\n  mihomo-mgr.py db-check --geodata --download",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--download", action="store_true", help="Download missing DB files")
    s.add_argument(
        "--geodata",
        action="store_true",
        help="Also include geoip.dat for geodata-mode: true",
    )
    s.add_argument(
        "--asn",
        action="store_true",
        help="Also include GeoLite2-ASN.mmdb for ASN rules",
    )
    s.add_argument(
        "--all",
        action="store_true",
        help="Include all db/dat/mmdb files (including lite editions)",
    )

    s = sub.add_parser(
        "db-download",
        help="Download database files",
        description="Download missing or requested database files to the config directory.\nUse --force to re-download all, --geodata/--asn/--all for optional files.",
        epilog="Examples:\n  mihomo-mgr.py db-download\n  mihomo-mgr.py db-download --all --force",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "--force",
        action="store_true",
        help="Download selected DB files even if present",
    )
    s.add_argument(
        "--geodata",
        action="store_true",
        help="Also include geoip.dat for geodata-mode: true",
    )
    s.add_argument(
        "--asn",
        action="store_true",
        help="Also include GeoLite2-ASN.mmdb for ASN rules",
    )
    s.add_argument(
        "--all",
        action="store_true",
        help="Include all db/dat/mmdb files (including lite editions)",
    )

    s = sub.add_parser(
        "start",
        help="Start mihomo as background process",
        description="Start mihomo as a background process. Creates necessary directories,\ndownloads missing DB files (unless --skip-db-check),\npatches config.yaml with config-set values (unless --no-patch), and writes pid/log files.",
        epilog="Examples:\n  mihomo-mgr.py start\n  mihomo-mgr.py start --config /path/to/config.yaml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--config", help="config file path")
    s.add_argument(
        "--skip-db-check",
        action="store_true",
        help="Do not download missing DB files before start",
    )
    s.add_argument(
        "--no-patch", action="store_true", help="Skip config.yaml patching before start"
    )

    s = sub.add_parser(
        "stop",
        help="Stop mihomo process gracefully",
        description="Stop a mihomo process previously started by mihomo-mgr.\nSends SIGTERM, then SIGKILL on --force if graceful shutdown times out.",
        epilog="Examples:\n  mihomo-mgr.py stop\n  mihomo-mgr.py stop --timeout 10 --force",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "--timeout", type=float, default=5.0, help="Graceful stop timeout in seconds"
    )
    s.add_argument(
        "--force", action="store_true", help="Kill if graceful stop times out"
    )

    s = sub.add_parser(
        "restart",
        help="Restart mihomo process",
        description="Stop then start the mihomo process.\nSupports --config, --skip-db-check, --no-patch (from start)\nand --timeout, --force (from stop).\nBefore starting, patches config.yaml with config-set values.",
        epilog="Examples:\n  mihomo-mgr.py restart\n  mihomo-mgr.py restart --config /path/to/config.yaml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--config", help="config file path")
    s.add_argument(
        "--skip-db-check",
        action="store_true",
        help="Do not download missing DB files before start",
    )
    s.add_argument(
        "--no-patch", action="store_true", help="Skip config.yaml patching before start"
    )
    s.add_argument(
        "--timeout", type=float, default=5.0, help="Graceful stop timeout in seconds"
    )
    s.add_argument(
        "--force", action="store_true", help="Kill if graceful stop times out"
    )

    s = sub.add_parser(
        "logs",
        help="Show recent mihomo log lines",
        description="Show recent lines from the mihomo log file. Useful for debugging\nconnection failures, rule matching, and proxy errors.\n\nShows file metadata (path, size, line count) before the log content.",
        epilog="Examples:\n  mihomo-mgr.py logs\n  mihomo-mgr.py logs -n 200\n  mihomo-mgr.py logs -f           # Follow (tail -f)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "-n", "--lines", type=int, default=50, help="Number of lines to show"
    )
    s.add_argument(
        "-f", "--follow", action="store_true", help="Follow log output like tail -f"
    )

    s = sub.add_parser(
        "logs-clear",
        help="Clear or trim the mihomo log file",
        description="Truncate the mihomo log file, or keep only the last N lines with --keep.",
        epilog="Examples:\n  mihomo-mgr.py logs-clear           # Clear completely\n  mihomo-mgr.py logs-clear --keep 100 # Keep last 100 lines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s.add_argument("--keep", type=int, help="Keep last N lines instead of clearing all")

    s = sub.add_parser(
        "sub-pull",
        help="Pull subscription and generate config.yaml",
        description="Pull a subscription from the configured URL (or a one-off --url) and\ngenerate a normalized config.yaml with local runtime settings applied.",
        epilog="Examples:\n  mihomo-mgr.py sub-pull\n  mihomo-mgr.py sub-pull --url 'https://example.com/sub'",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--url", help="subscription URL for this pull only")
    s.add_argument(
        "--no-proxy",
        action="store_true",
        help="fetch subscription directly without local proxy",
    )

    sub.add_parser(
        "sub-show",
        help="Show subscription cache status",
        description="Show the subscription URL, raw cache file path, and generated config file with sizes and timestamps.",
        epilog="Examples:\n  mihomo-mgr.py sub-show",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s = sub.add_parser(
        "routing",
        help="Manage local direct/proxy routing policy",
        description="Edit an independent local routing draft. init/add/remove never change the running config; apply publishes the draft. Entry kinds are selected with --type.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_sub = s.add_subparsers(dest="routing_action", required=True)
    routing_sub.add_parser("show", help="Show the local routing policy and active snapshot")
    routing_init = routing_sub.add_parser("init", help="Initialize and enable a routing draft")
    routing_init.add_argument("--proxy-group", required=True, help="Exact proxy node or group name")
    routing_init.add_argument("--force", action="store_true", help="Replace the existing draft (active config is unchanged)")
    for routing_action in ("add", "remove"):
        routing_edit = routing_sub.add_parser(routing_action, help=f"{routing_action.title()} a draft entry")
        routing_edit.add_argument("list_name", choices=sorted(_ROUTING_LIST_ALIASES), help="direct/whitelist or proxy/blacklist")
        routing_edit.add_argument("value", help="Rule value")
        routing_edit.add_argument("--type", choices=sorted(_ROUTING_TYPES), default="domain-suffix", help="Rule type (default: domain-suffix)")
    routing_apply = routing_sub.add_parser("apply", help="Validate and publish the routing draft")
    routing_apply.add_argument("--dry-run", action="store_true", help="Print effective rules without writing or reloading")
    routing_apply.add_argument("--offline", action="store_true", help="Write validated config without calling the mihomo API")

    s = sub.add_parser(
        "gfwlist",
        help="Manage the GFWList base routing layer",
        description="Download and publish the fixed GFWList source beneath custom direct/proxy rules. Supports --interval-hours, --offline, --json, and --skipped on their respective actions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    gfw_sub = s.add_subparsers(dest="gfwlist_action", required=True)
    gfw_status = gfw_sub.add_parser("status", help="Show GFWList cache and update status")
    gfw_status.add_argument("--json", action="store_true", help="Print full cache metadata as JSON")
    gfw_status.add_argument("--skipped", action="store_true", help="Show skipped reasons and samples")
    gfw_enable = gfw_sub.add_parser("enable", help="Download, validate, and enable GFWList")
    gfw_enable.add_argument("--interval-hours", type=int, default=24, help="Automatic update interval; 0 disables scheduling")
    gfw_enable.add_argument("--offline", action="store_true", help="Publish without calling the mihomo API")
    gfw_disable = gfw_sub.add_parser("disable", help="Disable GFWList and retain custom routing")
    gfw_disable.add_argument("--offline", action="store_true", help="Publish without calling the mihomo API")
    gfw_update = gfw_sub.add_parser("update", help="Download and publish the latest GFWList")
    gfw_update.add_argument("--offline", action="store_true", help="Publish without calling the mihomo API")
    gfw_update.add_argument("--if-due", action="store_true", help=argparse.SUPPRESS)

    s = sub.add_parser(
        "sub-import",
        help="Import a local YAML file as subscription",
        description="Import a locally downloaded subscription YAML file and generate a normalized\nconfig.yaml with local runtime settings applied (mixed-port, bind-address, etc.).",
        epilog="Examples:\n  mihomo-mgr.py sub-import ~/Downloads/sub.yaml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("file", help="path to the YAML subscription file")

    sub.add_parser(
        "config",
        help="Show persisted and effective configuration",
        description="Display the persisted manager configuration (JSON) and the effective runtime paths.",
        epilog="Examples:\n  mihomo-mgr.py config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s = sub.add_parser(
        "config-init",
        help="Create editable default config file",
        description="Create an editable config template at ~/.config/mihomo-mgr/config.yaml.\nAdd --force to overwrite an existing file.",
        epilog="Examples:\n  mihomo-mgr.py config-init\n  mihomo-mgr.py config-init --force",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "--force", action="store_true", help="Overwrite existing configuration file"
    )

    s = sub.add_parser(
        "config-set",
        help="Persist configuration values",
        description="Persist configuration values to ~/.config/mihomo-mgr/config.yaml.\nOnly provided flags are saved; omitted values keep their existing settings.",
        epilog="Examples:\n  mihomo-mgr.py config-set --mixed-port 7890\n  mihomo-mgr.py config-set --sub-url 'https://...' --api http://127.0.0.1:9090\n  mihomo-mgr.py config-set --config-dir ~/.config/mihomo --bin-dir /usr/local/bin",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "--config-dir",
        dest="persist_config_dir",
        metavar="DIR",
        help="mihomo config directory",
    )
    s.add_argument(
        "--bin-dir",
        dest="persist_bin_dir",
        metavar="DIR",
        help="directory containing the mihomo binary",
    )
    s.add_argument(
        "--bin",
        dest="persist_bin",
        metavar="PATH",
        help="mihomo binary path or command",
    )
    s.add_argument(
        "--log-file", dest="persist_log_file", metavar="PATH", help="mihomo log file"
    )
    s.add_argument(
        "--pid-file", dest="persist_pid_file", metavar="PATH", help="mihomo pid file"
    )
    s.add_argument("--api", dest="persist_api", metavar="URL", help="HTTP API URL")
    s.add_argument(
        "--sock", dest="persist_sock", metavar="PATH", help="Unix socket path"
    )
    s.add_argument(
        "--secret", dest="persist_secret", metavar="SECRET", help="API secret"
    )
    s.add_argument(
        "--sub-url", dest="persist_sub_url", metavar="URL", help="subscription URL"
    )
    s.add_argument(
        "--proxy-host", dest="persist_proxy_host", metavar="HOST", help="proxy host"
    )
    s.add_argument(
        "--mixed-port",
        dest="persist_mixed_port",
        metavar="PORT",
        help="mihomo mixed-port (primary port for config.yaml and proxy-on)",
    )
    s.add_argument(
        "--proxy-http-port",
        dest="persist_proxy_http_port",
        metavar="PORT",
        help="HTTP proxy port (overrides mixed-port for HTTP)",
    )
    s.add_argument(
        "--proxy-socks-port",
        dest="persist_proxy_socks_port",
        metavar="PORT",
        help="SOCKS proxy port (overrides mixed-port for SOCKS)",
    )
    s.add_argument(
        "--proxy-http",
        dest="persist_proxy_http",
        metavar="URL",
        help="full HTTP proxy URL",
    )
    s.add_argument(
        "--proxy-socks",
        dest="persist_proxy_socks",
        metavar="URL",
        help="full SOCKS proxy URL",
    )
    s.add_argument(
        "--no-proxy", dest="persist_no_proxy", metavar="HOSTS", help="no_proxy value"
    )
    s.add_argument(
        "--health-check-url",
        dest="persist_health_check_url",
        metavar="URL",
        help="default health check URL for url-test groups (e.g. https://api.openai.com)",
    )
    s.add_argument(
        "--guard-enabled",
        dest="persist_guard_enabled",
        metavar="BOOL",
        help="流量熔断总开关 (true/false)",
    )
    s.add_argument(
        "--guard-wall",
        dest="persist_guard_wall",
        metavar="BOOL",
        help="guard 通知是否 wall 广播终端",
    )
    s.add_argument(
        "--guard-quota-gb",
        dest="persist_guard_quota_gb",
        metavar="GB",
        help="机场月配额（GB），熔断阈值基准",
    )
    s.add_argument(
        "--guard-trip-pct",
        dest="persist_guard_trip_pct",
        metavar="PCT",
        help="熔断阈值百分比（滚动1小时 = 配额×PCT%%）",
    )
    s.add_argument(
        "--guard-warn-pct",
        dest="persist_guard_warn_pct",
        metavar="PCT",
        help="预警阈值百分比（仅通知）；0 关闭",
    )
    s.add_argument(
        "--guard-monthly-warn-pct",
        dest="persist_guard_monthly_warn_pct",
        metavar="PCT",
        help="月累计预警百分比；0 关闭",
    )
    s.add_argument(
        "--guard-disable-hours",
        dest="persist_guard_disable_hours",
        metavar="HOURS",
        help="熔断持续小时数，到期自动恢复",
    )
    s.add_argument(
        "--direct-domain",
        dest="add_direct_domain",
        metavar="DOMAIN",
        action="append",
        help="append a domain to direct whitelist (repeatable, e.g. --direct-domain example.com --direct-domain foo.bar)",
    )
    s.add_argument(
        "--direct-domain-remove",
        dest="remove_direct_domain",
        metavar="DOMAIN",
        action="append",
        help="remove a domain from direct whitelist (repeatable)",
    )
    s.add_argument(
        "--direct-domain-clear",
        dest="clear_direct_domains",
        action="store_true",
        help="clear all domains from direct whitelist",
    )
    # Stats configuration
    s.add_argument(
        "--stats-enabled",
        dest="persist_stats_enabled",
        metavar="BOOL",
        help="enable/disable traffic stats collection (true/false)",
    )
    s.add_argument(
        "--stats-db",
        dest="persist_stats_db",
        metavar="PATH",
        help="SQLite database path for traffic stats",
    )
    s.add_argument(
        "--stats-retention-days",
        dest="persist_stats_retention_days",
        type=int,
        metavar="DAYS",
        help="data retention in days (default: 180)",
    )
    s.add_argument(
        "--stats-poll-interval",
        dest="persist_stats_poll_interval",
        type=int,
        metavar="SECS",
        help="polling interval in seconds (default: 5)",
    )
    # Idle detection configuration
    s.add_argument(
        "--idle-enabled",
        dest="persist_idle_enabled",
        metavar="BOOL",
        help="enable/disable idle detection (true/false)",
    )
    s.add_argument(
        "--idle-auto-block-level",
        dest="persist_idle_auto_block_level",
        choices=["notify", "block", "force_block"],
        help="auto-block level: notify | block | force_block",
    )
    s.add_argument(
        "--idle-block-after-notify-count",
        dest="persist_idle_block_after_notify_count",
        type=int,
        metavar="COUNT",
        help="number of notifications before auto-blocking (default: 3)",
    )
    s.add_argument(
        "--idle-cooldown-minutes",
        dest="persist_idle_cooldown_minutes",
        type=int,
        metavar="MINS",
        help="cooldown between notifications in minutes (default: 30)",
    )
    s.add_argument(
        "--idle-whitelist-add",
        dest="add_idle_whitelist",
        metavar="PROC",
        action="append",
        help="add process to idle whitelist (repeatable)",
    )
    s.add_argument(
        "--idle-whitelist-remove",
        dest="remove_idle_whitelist",
        metavar="PROC",
        action="append",
        help="remove process from idle whitelist (repeatable)",
    )
    s.add_argument(
        "--idle-blacklist-add",
        dest="add_idle_blacklist",
        metavar="PROC",
        action="append",
        help="add process to idle blacklist (repeatable)",
    )
    s.add_argument(
        "--idle-blacklist-remove",
        dest="remove_idle_blacklist",
        metavar="PROC",
        action="append",
        help="remove process from idle blacklist (repeatable)",
    )
    # Schedule configuration
    s.add_argument(
        "--schedule-enabled",
        dest="persist_schedule_enabled",
        metavar="BOOL",
        help="enable/disable scheduled start/stop (true/false)",
    )
    s.add_argument(
        "--schedule-work-hours",
        dest="persist_schedule_work_hours",
        metavar="RANGE",
        help="work hours range (e.g. 09:00-22:00)",
    )
    s.add_argument(
        "--schedule-work-days",
        dest="persist_schedule_work_days",
        metavar="DAYS",
        help="work days (e.g. mon-fri, mon-sun)",
    )
    # Notification configuration
    s.add_argument(
        "--notify-dingtalk-webhook",
        dest="persist_notify_dingtalk_webhook",
        metavar="URL",
        help="DingTalk webhook URL for notifications",
    )
    s.add_argument(
        "--notify-dingtalk-secret",
        dest="persist_notify_dingtalk_secret",
        metavar="SECRET",
        help="DingTalk webhook secret (optional)",
    )

    sub.add_parser(
        "config-clear",
        help="Remove persisted configuration",
        description="Delete the persisted config file at ~/.config/mihomo-mgr/config.yaml.",
        epilog="Examples:\n  mihomo-mgr.py config-clear",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    s = sub.add_parser(
        "proxy-status",
        help="Show current terminal proxy variables",
        description="Show which proxy environment variables are currently set, plus the\nvalues that proxy-on would export.",
        epilog="Examples:\n  mihomo-mgr.py proxy-status\n  mihomo-mgr.py proxy-status -v",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "-v", "--verbose", action="store_true", help="Show missing proxy variables"
    )

    s = sub.add_parser(
        "proxy-on",
        help="Print shell exports to enable proxy",
        description="Print shell export commands for temporary proxy environment variables.\nPipe through eval to apply to the current shell.\n\nProxy host/ports are derived from:\n  CLI args > mixed_port > proxy_http/socks_port > mihomo /configs > defaults",
        epilog='Examples:\n  eval "$(mihomo-mgr.py proxy-on)"\n  eval "$(mihomo-mgr.py proxy-on --host 127.0.0.1 --http-port 7890)"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("--host", help=f"proxy host (fallback: {DEFAULT_PROXY_HOST})")
    s.add_argument(
        "--http-port",
        help=f"HTTP proxy port (fallback: mixed_port > {DEFAULT_HTTP_PROXY_PORT})",
    )
    s.add_argument(
        "--socks-port",
        help=f"SOCKS proxy port (fallback: mixed_port > {DEFAULT_SOCKS_PROXY_PORT})",
    )
    s.add_argument("--http", help="full HTTP proxy URL")
    s.add_argument("--socks", help="full SOCKS proxy URL")
    s.add_argument("--no-proxy", help=f"no_proxy value (default: {DEFAULT_NO_PROXY})")
    s.add_argument(
        "--quiet", action="store_true", help="Do not print usage hint comments"
    )

    s = sub.add_parser(
        "proxy-off",
        help="Print shell commands to disable proxy",
        description="Print shell unset commands that clear all proxy environment variables.\nPipe through eval to apply to the current shell.",
        epilog='Examples:\n  eval "$(mihomo-mgr.py proxy-off)"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "--quiet", action="store_true", help="Do not print usage hint comments"
    )

    s = sub.add_parser(
        "completion",
        help="Generate shell completion script",
        description="Generate bash or zsh completion script for mihomo-mgr.\nSource the output to enable tab completion for commands, group names, and node names.",
        epilog="Examples:\n  source <(mihomo-mgr.py completion bash)  # Enable for current shell\n  mihomo-mgr.py completion zsh               # Print zsh script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("shell", choices=["bash", "zsh"], help="Target shell")

    # Stats large command
    s = sub.add_parser(
        "stats-large",
        help="Large download detection",
        description="View and manage large download detection (>30MB).",
        epilog="Examples:\n  mihomo-mgr.py stats-large list           # List large downloads\n  mihomo-mgr.py stats-large summary      # Show summary statistics\n  mihomo-mgr.py stats-large detail --id 1  # Show details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "large_action",
        nargs="?",
        choices=["list", "summary", "detail"],
        default="list",
        help="Action to perform",
    )
    s.add_argument(
        "--since", default="7d", help="Time range (e.g., 7d, 30d, default: 7d)"
    )
    s.add_argument("--id", type=int, help="Download ID for detail view")

    # Stats daemon command
    s = sub.add_parser(
        "stats-daemon",
        help="Manage traffic stats daemon",
        description="Start, stop, or check status of the traffic statistics collection daemon.",
        epilog="Examples:\n  mihomo-mgr.py stats-daemon start    # Start daemon\n  mihomo-mgr.py stats-daemon stop     # Stop daemon\n  mihomo-mgr.py stats-daemon status   # Check status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument("action", choices=["start", "stop", "status"], help="Daemon action")

    # Stats command
    s = sub.add_parser(
        "stats",
        help="Traffic statistics",
        description="View traffic statistics or manage stats data.",
        epilog="Examples:\n  mihomo-mgr.py stats                 # Show domain ranking\n  mihomo-mgr.py stats --node          # Show node ranking\n  mihomo-mgr.py stats --trend daily   # Show daily trend\n  mihomo-mgr.py stats --compare daily # Compare today vs yesterday\n  mihomo-mgr.py stats vacuum          # Clean up old data\n  mihomo-mgr.py stats reset           # Reset all stats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    s.add_argument(
        "stats_action",
        nargs="?",
        choices=["vacuum", "reset", "idle"],
        help="Stats action",
    )
    s.add_argument(
        "--top", type=int, default=20, help="Number of entries to show (default: 20)"
    )
    s.add_argument(
        "--since", default="7d", help="Time range (e.g., 7d, 30d, default: 7d)"
    )
    s.add_argument("--node", action="store_true", help="Show node ranking")
    s.add_argument("--rule", action="store_true", help="Show rule ranking")
    s.add_argument("--json", action="store_true", help="Output in JSON format")
    s.add_argument("--export-csv", action="store_true", help="Export as CSV")
    s.add_argument("--trend", choices=["hourly", "daily", "monthly"], help="Show trend")
    s.add_argument("--compare", choices=["daily", "monthly"], help="Compare periods")
    s.add_argument("--date", help="Date for hourly trend (YYYY-MM-DD)")

    # Idle detection subcommand arguments
    s.add_argument(
        "--idle-detail", action="store_true", help="Show detailed idle status"
    )
    s.add_argument("--idle-block", metavar="PROC", help="Block a process")
    s.add_argument("--idle-unblock", metavar="PROC", help="Unblock a process")
    s.add_argument("--idle-whitelist-add", metavar="PROC", help="Add to whitelist")
    s.add_argument(
        "--idle-whitelist-remove", metavar="PROC", help="Remove from whitelist"
    )
    s.add_argument("--idle-whitelist-list", action="store_true", help="List whitelist")
    s.add_argument("--idle-blacklist-add", metavar="PROC", help="Add to blacklist")
    s.add_argument(
        "--idle-blacklist-remove", metavar="PROC", help="Remove from blacklist"
    )
    s.add_argument("--idle-blacklist-list", action="store_true", help="List blacklist")

    args = p.parse_args()

    # Override env from CLI args
    if getattr(args, "persist_sock", None):
        args.sock = None
    if getattr(args, "persist_api", None):
        args.api = None
    if getattr(args, "persist_secret", None):
        args.secret = None
    if getattr(args, "persist_config_dir", None):
        args.config_dir = None
    if getattr(args, "persist_bin_dir", None):
        args.bin_dir = None
    if getattr(args, "persist_bin", None):
        args.bin = None
    if getattr(args, "persist_log_file", None):
        args.log_file = None
    if getattr(args, "persist_pid_file", None):
        args.pid_file = None

    if args.sock:
        os.environ["MIHOMO_SOCK"] = args.sock
    if args.api:
        os.environ["MIHOMO_API"] = args.api
    if args.secret:
        os.environ["MIHOMO_SECRET"] = args.secret
    if args.config_dir:
        os.environ["MIHOMO_CONFIG_DIR"] = args.config_dir
    if args.bin_dir:
        os.environ["MIHOMO_BIN_DIR"] = args.bin_dir
    if args.bin:
        os.environ["MIHOMO_BIN"] = args.bin
    if args.log_file:
        os.environ["MIHOMO_LOG_FILE"] = args.log_file
    if args.pid_file:
        os.environ["MIHOMO_PID_FILE"] = args.pid_file

    dispatch = {
        "pick": cmd_pick,
        "status": cmd_status,
        "mode": cmd_mode,
        "groups": cmd_groups,
        "nodes": cmd_nodes,
        "select": cmd_select,
        "best": cmd_best,
        "delay": cmd_delay,
        "delay-group": cmd_delay_group,
        "conns": cmd_conns,
        "conns-close": cmd_conns_close,
        "rules": cmd_rules,
        "dns": cmd_dns,
        "flush-dns": cmd_flush_dns,
        "api-restart": cmd_restart,
        "upgrade-geo": cmd_upgrade_geo,
        "db-check": cmd_db_check,
        "db-download": cmd_db_download,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart_proc,
        "logs": cmd_logs,
        "logs-clear": cmd_logs_clear,
        "sub-pull": cmd_sub_pull,
        "sub-import": cmd_sub_import,
        "sub-show": cmd_sub_show,
        "routing": cmd_routing,
        "gfwlist": cmd_gfwlist,
        "config": cmd_config,
        "config-init": cmd_config_init,
        "config-set": cmd_config_set,
        "config-clear": cmd_config_clear,
        "proxy-status": cmd_proxy_status,
        "proxy-on": cmd_proxy_on,
        "proxy-off": cmd_proxy_off,
        "completion": cmd_completion,
        "__complete": cmd_internal_complete,
        "stats-daemon": cmd_stats_daemon,
        "guard": cmd_guard,
        "stats": cmd_stats,
        "stats-large": cmd_stats_large,
    }
    # 旧管理器的进程/API/订阅命令不具备 termcfg 租约、明确进度和私密输出契约。
    # 迁移期只提供私人配置编辑与静态补全；服务操作使用 ./termcfg service。
    if args.cmd not in {"config-init", "config-set", "config-clear", "completion", "__complete"}:
        print("legacy_command_disabled: use ./termcfg service or ./termcfg status", file=sys.stderr)
        sys.exit(2)
    if args.cmd in dispatch:
        try:
            dispatch[args.cmd](args)
        except (RoutingError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        _print_help()


if __name__ == "__main__":
    main()
