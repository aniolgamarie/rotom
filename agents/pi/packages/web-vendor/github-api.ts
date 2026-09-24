import { webServiceSelected, webFetchFor } from "@agentcfg/pi-runtime/web-binding";
import { webConfig, webCredential, webCredentialDeclared } from "@agentcfg/pi-runtime/web-config";
import type { ExtractedContent } from "./extract.ts";
import type { GitHubUrlInfo } from "./github-extract.ts";

const MAX_TREE_ENTRIES = 200;
const MAX_INLINE_FILE_CHARS = 100_000;

// API 数据读取独立于 gh CLI；所有请求都使用显式服务与秘密引用。
const githubFetch = webFetchFor("github");
export async function githubRequest(path: string, options: { signal?: AbortSignal; timeoutMs?: number; query?: string; variables?: Record<string, unknown> } = {}): Promise<Response> {
  if (!webServiceSelected("github")) throw new Error("WEB_GITHUB_NOT_SELECTED");
  if (path.startsWith("/") || path.includes("\\") || path.split(/[/?]/).some(part => part === ".." || part === ".")
      || !(path.startsWith("repos/") || path === "graphql")) throw new Error("WEB_GITHUB_PATH_INVALID");
  if (options.query !== undefined && (path !== "graphql" || !/^query\s/.test(options.query))) throw new Error("WEB_GITHUB_QUERY_INVALID");
  const headers = new Headers({ Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" });
  const configured = webConfig().githubToken;
  if (webCredentialDeclared(configured)) headers.set("Authorization", "Bearer " + webCredential(configured as string, options.signal));
  if (options.query) headers.set("Content-Type", "application/json");
  const signal = AbortSignal.any([AbortSignal.timeout(options.timeoutMs ?? 10000), ...(options.signal ? [options.signal] : [])]);
  return githubFetch("https://api.github.com/" + path, { headers, redirect: "error", signal,
    ...(options.query ? { method: "POST", body: JSON.stringify({ query: options.query, variables: options.variables ?? {} }) } : {}) });
}
async function githubJson(path: string, timeoutMs = 10000): Promise<Record<string, unknown> | null> {
  if (!webServiceSelected("github")) return null;
  const response = await githubRequest(path, { timeoutMs });
  if (!response.ok) return null;
  const raw: unknown = await response.json();
  return raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : null;
}
function repositoryPath(owner: string, repo: string): string {
  if (![owner, repo].every(value => /^[A-Za-z0-9_.-]+$/.test(value) && value !== "." && value !== "..")) throw new Error("WEB_GITHUB_REPOSITORY_INVALID");
  return `repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
}
function decodeContent(data: Record<string, unknown> | null): string | null {
  if (data?.encoding !== "base64" || typeof data.content !== "string") return null;
  const raw = data.content.replace(/\s/g, "");
  if (raw.length > 2 * 1024 * 1024 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(raw)) return null;
  try { return new TextDecoder("utf8", { fatal: true }).decode(Buffer.from(raw, "base64")); } catch { return null; }
}
export async function checkRepoSize(owner: string, repo: string): Promise<number | null> {
  const data = await githubJson(repositoryPath(owner, repo));
  return typeof data?.size === "number" && Number.isSafeInteger(data.size) && data.size >= 0 ? data.size : null;
}
async function getDefaultBranch(owner: string, repo: string): Promise<string | null> {
  const data = await githubJson(repositoryPath(owner, repo));
  return typeof data?.default_branch === "string" && data.default_branch ? data.default_branch : null;
}
async function fetchTreeViaApi(owner: string, repo: string, ref: string): Promise<string | null> {
  const data = await githubJson(`${repositoryPath(owner, repo)}/git/trees/${encodeURIComponent(ref)}?recursive=1`, 15000);
  if (!Array.isArray(data?.tree)) return null;
  const paths = data.tree.flatMap(row => row && typeof row === "object" && typeof row.path === "string" ? [row.path] : []);
  if (!paths.length) return null;
  const display = paths.slice(0, MAX_TREE_ENTRIES).join("\n");
  return data?.truncated === true || paths.length > MAX_TREE_ENTRIES ? display + `\n... (${paths.length} received entries; tree truncated)` : display;
}
async function fetchReadmeViaApi(owner: string, repo: string, ref: string): Promise<string | null> {
  const decoded = decodeContent(await githubJson(`${repositoryPath(owner, repo)}/readme?ref=${encodeURIComponent(ref)}`));
  return decoded && decoded.length > 8192 ? decoded.slice(0, 8192) + "\n\n[README truncated at 8K chars]" : decoded;
}
async function fetchFileViaApi(owner: string, repo: string, path: string, ref: string): Promise<string | null> {
  if (path.split("/").some(part => !part || part === "." || part === "..")) throw new Error("WEB_GITHUB_PATH_INVALID");
  return decodeContent(await githubJson(`${repositoryPath(owner, repo)}/contents/${path.split("/").map(encodeURIComponent).join("/")}?ref=${encodeURIComponent(ref)}`));
}

export async function fetchViaApi(
	url: string,
	owner: string,
	repo: string,
	info: GitHubUrlInfo,
	sizeNote?: string,
): Promise<ExtractedContent | null> {
	const ref = info.ref || (await getDefaultBranch(owner, repo));
	if (!ref) return null;

	const lines: string[] = [];
	if (sizeNote) {
		lines.push(sizeNote);
		lines.push("");
	}

	if (info.type === "blob" && info.path) {
		const content = await fetchFileViaApi(owner, repo, info.path, ref);
		if (!content) return null;

		lines.push(`## ${info.path}`);
		if (content.length > MAX_INLINE_FILE_CHARS) {
			lines.push(content.slice(0, MAX_INLINE_FILE_CHARS));
			lines.push(`\n[File truncated at 100K chars]`);
		} else {
			lines.push(content);
		}

		return {
			url,
			title: `${owner}/${repo} - ${info.path}`,
			content: lines.join("\n"),
			error: null,
		};
	}

	const [tree, readme] = await Promise.all([
		fetchTreeViaApi(owner, repo, ref),
		fetchReadmeViaApi(owner, repo, ref),
	]);

	if (!tree && !readme) return null;

	if (tree) {
		lines.push("## Structure");
		lines.push(tree);
		lines.push("");
	}

	if (readme) {
		lines.push("## README.md");
		lines.push(readme);
		lines.push("");
	}

	lines.push("This is an API-only view. Clone the repo or use `read`/`bash` for deeper exploration.");

	const title = info.path ? `${owner}/${repo} - ${info.path}` : `${owner}/${repo}`;
	return {
		url,
		title,
		content: lines.join("\n"),
		error: null,
	};
}
