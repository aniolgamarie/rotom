// 独立、显式的无账号宿主 smoke。普通 pytest 不执行此脚本。
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import http from 'node:http';

const root = process.env.AGENTCFG_SMOKE_ROOT;
const output = process.env.AGENTCFG_SMOKE_RESULT;
if (!root || !output || !['HOME', 'DSH_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'].every(
  name => process.env[name]?.startsWith(root + '/')) || !output.startsWith(root + '/')) {
  throw new Error('An explicit isolated smoke environment is required');
}
const runtime = process.argv[2];
if (!runtime || !path.isAbsolute(runtime)) throw new Error('An installed locked runtime is required');
const moduleAt = relative => import(pathToFileURL(path.join(runtime, 'node_modules', relative)).href);
// 不触发任何基于 fetch 的模型、登录、版本查询；本地 proxy 仅验证可启动。
globalThis.fetch = async () => { throw new Error('Network fetch disabled during no-account smoke'); };
const bin = path.join(runtime, 'node_modules/@deepseek-ai/dsh/lib/bin.js');
const match = fs.readFileSync(bin, 'utf8').match(/import\("(\.\/profile-boot-[^"]+)"\)/);
if (!match) throw new Error('Locked CLI profile entry changed');
const { runProfile } = await import(pathToFileURL(path.resolve(path.dirname(bin), match[1])).href);
const { loadLayeredEnv } = await moduleAt('@deepseek-ai/dsh-app-boot/lib/index.js');
const { ctx, shutdown } = await runProfile({
  environment: loadLayeredEnv('agentcfg-smoke'), profile: 'agentcfg',
  patchFiles: [path.join(process.env.DSH_HOME, 'agentcfg.patch.yml')], args: [],
});
for (let i = 0; i < 50 && ctx.get('agents')?.list().length === 0; i++) {
  await new Promise(resolve => setTimeout(resolve, 100));
}
const agent = ctx.get('agents')?.list()[0];
if (!agent) throw new Error('TUI did not create a native agent');
const commands = ctx.get('commands').list(agent).map(command => command.name);
if (!commands.includes('auth') || !commands.includes('cursor-login')) {
  throw new Error('Subscription login commands did not register');
}
let proxyHealthy = false;
if (process.env.AGENTCFG_SMOKE_PORT) {
  for (let i = 0; i < 20 && !proxyHealthy; i++) {
    proxyHealthy = await new Promise(resolve => {
      const request = http.get({ host: '127.0.0.1', port: Number(process.env.AGENTCFG_SMOKE_PORT),
        path: '/health', agent: false, timeout: 1000 }, response => {
        let body = '';
        response.on('data', chunk => { body += chunk; });
        response.on('end', () => {
          try { const value = JSON.parse(body); resolve(value.ok === true && value.plugin === 'dsh-plugin-oauth-subs'); }
          catch { resolve(false); }
        });
      });
      request.on('timeout', () => request.destroy());
      request.on('error', () => resolve(false));
    });
    if (!proxyHealthy) await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!proxyHealthy) throw new Error('The isolated Cursor proxy did not become healthy');
}
const presets = await ctx.get('agentPresets').list();
if (!presets.some(preset => preset.id === 'standard' && !preset.broken)) {
  throw new Error('Standard preset is missing or broken');
}
const { FileSystemSkillProvider } = await moduleAt('@deepseek-ai/dsh-skill-filesystem/lib/index.js');
const cancellation = new AbortController();
const provider = new FileSystemSkillProvider(agent.ctx, { invalidate() {}, signal: cancellation.signal }, { watch: false });
const found = await provider.list({ cwd: process.cwd() });
const candidates = Array.isArray(found) ? found : found.candidates;
const names = candidates.map(candidate => candidate.name);
if (!names.includes('repo-navigation') || !names.includes('maintain-agent-config')) {
  throw new Error('DSH did not discover the generated skill packages');
}
if (fs.existsSync(path.join(process.cwd(), 'openspec/config.yaml')) && !names.includes('openspec-propose')) {
  const roots = await provider.roots(process.cwd());
  throw new Error('OpenSpec project skills were not discovered: ' + JSON.stringify({ cwd: process.cwd(), roots, names }));
}
cancellation.abort();
await provider.dispose();
fs.writeFileSync(output, JSON.stringify({
  host: 'active', tui: 'agent-created', preset: 'standard',
  authCommands: commands.filter(name => ['auth', 'cursor-login'].includes(name)),
  skills: names, cwd: process.cwd(), modelCalls: 'not-run', fetch: 'blocked',
  proxyHealthy, nonce: process.env.AGENTCFG_SMOKE_NONCE,
}, null, 2) + '\n', { mode: 0o600 });
await shutdown.shutdown(0);
