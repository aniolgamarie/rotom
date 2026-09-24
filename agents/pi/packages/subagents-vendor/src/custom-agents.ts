// agentcfg 使用显式角色快照；项目或全局目录发现已由迁移方案替换。
import { parseFrontmatter } from "@earendil-works/pi-coding-agent";
import { loadControlledRoles } from "./agentcfg-config.js";
import type { AgentConfig } from "./types.js";

export function loadCustomAgents(_cwd: string, _strict = false): Map<string, AgentConfig> {
  return loadControlledRoles(parseAgentFrontmatter);
}

export function parseAgentFrontmatter<T extends Record<string, unknown>>(content: string): { frontmatter: T; body: string } {
  return parseFrontmatter<T>(content.startsWith("\uFEFF") ? content.slice(1) : content);
}
