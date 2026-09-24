import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createCipheriv, createHash, pbkdf2Sync } from "node:crypto";
import { DatabaseSync } from "node:sqlite";
import { webBrowserSnapshot, webBrowserDeclared, webBrowserCookieHeader } from "../web-browser.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "web-browser-")), directory = join(root, "credential-cache/web-browser", "a".repeat(32));
  mkdirSync(join(directory, "Default"), { recursive: true, mode: 0o700 });
  const path = join(directory, "Default/Cookies"), db = new DatabaseSync(path);
  db.exec("CREATE TABLE meta (key TEXT,value TEXT); INSERT INTO meta VALUES ('version','24'); CREATE TABLE cookies (name TEXT,value TEXT,host_key TEXT,path TEXT,expires_utc INTEGER,encrypted_value BLOB)");
  const secret = "synthetic-browser-password", host = "private.example.invalid";
  const key = pbkdf2Sync(secret, "saltysalt", process.platform === "darwin" ? 1003 : 1, 16, "sha1");
  const cipher = createCipheriv("aes-128-cbc", key, Buffer.alloc(16, 0x20));
  const data = Buffer.concat([createHash("sha256").update(host).digest(), Buffer.from("synthetic-cookie")]);
  const encrypted = Buffer.concat([Buffer.from("v10"), cipher.update(data), cipher.final()]);
  db.prepare("INSERT INTO cookies VALUES (?,?,?,?,?,?)").run("session", "", host, "/", 0, encrypted);
  db.prepare("INSERT INTO cookies VALUES (?,?,?,?,?,?)").run("unselected", "must-not-leak", "other.example.invalid", "/", 0, Buffer.alloc(0));
  db.close(); const before = readFileSync(path), calls = [], controller = new AbortController();
  const runtime = { instanceRoot: root, owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {},
    web_config: { allowBrowserCookies: true, agentcfgBrowserProfile: "work" }, web_credential_variables: [variable],
    web_browser_profiles: { work: { browser: "chrome", profile: "Default", allowed_hosts: [host], password_reference: "$" + variable } } },
    web: { current: () => ({ controller }) }, supervisor: { options: { endpoint: join(root, "activity/control/control.json") }, async call(method, args) {
      calls.push({ method, args });
      if (method === "ordinary_web_browser_prepare") return { snapshot_id: "b".repeat(64), directory, profile: "Default", browser: "chrome", sidecars: [] };
      if (method === "ordinary_web_browser_finish") return { released: true };
      throw new Error("unexpected fixture RPC");
    } } };
  globalThis[slot] = runtime; process.env[variable] = secret;
  return { root, directory, path, before, calls, controller, runtime, host, cleanup() { delete globalThis[slot]; delete process.env[variable]; rmSync(root, { recursive: true, force: true }); } };
}
test("actual browser reader decrypts only the selected snapshot and never invokes keychain or external SQLite", async () => {
  const f = fixture();
  try {
    const { getBrowserCookiesForHosts, installWebCookieReader } = await import("../../packages/web-vendor/chrome-cookies.ts");
    assert.equal(webBrowserDeclared(), true);
    const result = await getBrowserCookiesForHosts({ binding: "work", hosts: [f.host], requestUrl: new URL("https://" + f.host + "/path") });
    assert.equal(result.cookieHeader, "session=synthetic-cookie");
    assert.deepEqual(result.cookies, { session: "synthetic-cookie" });
    assert.deepEqual(readFileSync(f.path), f.before);
    assert.deepEqual(f.calls.map(row => row.method), ["ordinary_web_browser_prepare", "ordinary_web_browser_finish"]);
    installWebCookieReader();
    assert.equal(await webBrowserCookieHeader("work", new URL("https://" + f.host)), "session=synthetic-cookie");
  } finally { f.cleanup(); }
});
test("unselected hosts, profile overrides and canceled requests fail before snapshot IO", async () => {
  const f = fixture();
  try {
    await assert.rejects(webBrowserSnapshot({ hosts: ["other.example.invalid"] }), /PROFILE_UNSELECTED/);
    await assert.rejects(webBrowserSnapshot({ hosts: [f.host], profile: "Unselected Profile" }), /PROFILE_UNSELECTED/);
    f.controller.abort(); await assert.rejects(webBrowserSnapshot({ hosts: [f.host] }), /abort/i);
    assert.equal(f.calls.length, 0);
  } finally { f.cleanup(); }
});
test("foreign snapshot locations are refused and released without opening their files", async () => {
  const f = fixture();
  try {
    const original = f.runtime.supervisor.call;
    f.runtime.supervisor.call = async (method, args) => {
      const result = await original(method, args);
      return method.endsWith("prepare") ? { ...result, directory: "/unselected/private" } : result;
    };
    await assert.rejects(webBrowserSnapshot({ hosts: [f.host] }), /SNAPSHOT_INVALID/);
    assert.deepEqual(f.calls.map(row => row.method), ["ordinary_web_browser_prepare", "ordinary_web_browser_finish"]);
  } finally { f.cleanup(); }
});

test("released snapshots cannot read the browser password again", async () => {
  const f = fixture();
  try {
    const snapshot = await webBrowserSnapshot({ hosts: [f.host] });
    assert.equal(snapshot.password(), "synthetic-browser-password");
    await snapshot.release(); await snapshot.release();
    assert.throws(() => snapshot.password(), /STALE/);
    assert.equal(f.calls.filter(row => row.method === "ordinary_web_browser_finish").length, 1);
  } finally { f.cleanup(); }
});

test("missing browser password refuses authentication before reading a database snapshot", async () => {
  const f = fixture();
  try {
    delete process.env[variable];
    await assert.rejects(webBrowserSnapshot({ hosts: [f.host] }), /CREDENTIAL_MISSING/);
    assert.equal(f.calls.length, 0);
  } finally { f.cleanup(); }
});

test("authenticated fetch can obtain its cookie only through the bound browser profile", async () => {
  const f = fixture(), sent = [];
  f.runtime.manifest.web_auth_fetch = { docs: { origins: ["https://" + f.host], browser_profile: "work" } };
  f.runtime.web.fetch = async (service, url, init) => { sent.push({ service, url, init }); return new Response("fixture authenticated page"); };
  try {
    const { installWebCookieReader } = await import("../../packages/web-vendor/chrome-cookies.ts");
    const { authenticatedWebFetch } = await import("../web-auth-fetch.ts");
    installWebCookieReader();
    const response = await authenticatedWebFetch(f.runtime, "docs", "https://" + f.host + "/path");
    assert.equal(await response.text(), "fixture authenticated page");
    assert.equal(sent[0].service, "authenticated"); assert.equal(sent[0].init.headers.get("cookie"), "session=synthetic-cookie");
    assert.equal(f.calls.at(-1).method, "ordinary_web_browser_finish");
  } finally { f.cleanup(); }
});
