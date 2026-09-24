import { webConfig as agentcfgWebConfig, webConfigurationIdentity } from "@agentcfg/pi-runtime/web-config";
import { webGitClone, webGitContent } from "@agentcfg/pi-runtime/web-cli";
import { activityMonitor } from "./activity.ts";
import type { ExtractedContent } from "./extract.ts";
import { checkRepoSize, fetchViaApi } from "./github-api.ts";
import { getWebSearchConfigPath } from "./utils.ts";

const CONFIG_PATH = getWebSearchConfigPath();

export interface GitHubUrlInfo {
	owner: string;
	repo: string;
	ref?: string;
	refIsFullSha: boolean;
	path?: string;
	type: "root" | "blob" | "tree";
}

interface CachedClone { clonePromise: Promise<string | null>; }
interface GitHubCloneConfig { enabled: boolean; maxRepoSizeMB: number; }
const cloneCache = new Map<string, CachedClone>();
let cloneIdentity: unknown;
function loadGitHubConfig(): GitHubCloneConfig {
  const raw = agentcfgWebConfig().githubClone as { enabled?: boolean; maxRepoSizeMB?: number } | undefined;
  return { enabled: raw?.enabled === true, maxRepoSizeMB: raw?.maxRepoSizeMB ?? 350 };
}

const NON_CODE_SEGMENTS = new Set([
	"issues", "pull", "pulls", "discussions", "releases", "wiki",
	"actions", "settings", "security", "projects", "graphs",
	"compare", "commits", "tags", "branches", "stargazers",
	"watchers", "network", "forks", "milestone", "labels",
	"packages", "codespaces", "contribute", "community",
	"sponsors", "invitations", "notifications", "insights",
]);

export function parseGitHubUrl(url: string): GitHubUrlInfo | null {
	let parsed: URL;
	try {
		parsed = new URL(url);
	} catch {
		return null;
	}

	const host = parsed.hostname.toLowerCase();
	if (host !== "github.com" && host !== "www.github.com") return null;

	const segments: string[] = [];
	for (const segment of parsed.pathname.split("/").filter(Boolean)) {
		try {
			segments.push(decodeURIComponent(segment));
		} catch {
			return null;
		}
	}
	if (segments.length < 2) return null;

	const owner = segments[0];
	const repo = segments[1].replace(/\.git$/, "");
	if (!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(owner)) return null;
	if (owner.includes("--")) return null;
	if (!/^[A-Za-z0-9._-]{1,100}$/.test(repo) || repo === "." || repo === "..") return null;

	if (NON_CODE_SEGMENTS.has(segments[2]?.toLowerCase())) return null;

	if (segments.length === 2) {
		return { owner, repo, refIsFullSha: false, type: "root" };
	}

	const action = segments[2];
	if (action !== "blob" && action !== "tree") return null;
	if (segments.length < 4) return null;

	const ref = segments[3];
	if (ref.length === 0 || ref.length > 1024 || /[\0-\x1f\x7f]/.test(ref)) return null;
	const refIsFullSha = /^[0-9a-f]{40}$/.test(ref);
	const pathParts = segments.slice(4);
	const path = pathParts.length > 0 ? pathParts.join("/") : "";

	return {
		owner,
		repo,
		ref,
		refIsFullSha,
		path,
		type: action as "blob" | "tree",
	};
}

function cacheKey(owner: string, repo: string, ref?: string): string {
	return ref ? `${owner}/${repo}@${ref}` : `${owner}/${repo}`;
}

async function awaitCachedClone(
	cached: CachedClone,
	url: string,
	owner: string,
	repo: string,
	info: GitHubUrlInfo,
	signal?: AbortSignal,
): Promise<ExtractedContent | null> {
	if (signal?.aborted) return null;
	const result = await cached.clonePromise;
	if (signal?.aborted) return null;
	if (result) {
		const content = await webGitContent(result, info.type, info.path);
		const title = info.path ? `${owner}/${repo} - ${info.path}` : `${owner}/${repo}`;
		return { url, title, content, error: null };
	}
	return fetchViaApi(url, owner, repo, info);
}

export async function extractGitHub(
	url: string,
	signal?: AbortSignal,
	forceClone?: boolean,
): Promise<ExtractedContent | null> {
	const info = parseGitHubUrl(url);
	if (!info) return null;

	if (signal?.aborted) return null;

	const config = loadGitHubConfig();
	if (!config.enabled) {
    if (forceClone) throw new Error("WEB_GITHUB_CLONE_NOT_SELECTED");
    return fetchViaApi(url, info.owner, info.repo, info);
  }
  const identity = webConfigurationIdentity();
  if (cloneIdentity !== identity) { cloneCache.clear(); cloneIdentity = identity; }

	const { owner, repo } = info;
	const key = cacheKey(owner, repo, info.ref);

	const cached = cloneCache.get(key);
	if (cached) return awaitCachedClone(cached, url, owner, repo, info, signal);

	if (info.refIsFullSha) {
		if (signal?.aborted) return null;
		const sizeNote = `Note: Commit SHA URLs use the GitHub API instead of cloning.`;
		return fetchViaApi(url, owner, repo, info, sizeNote);
	}

	const activityId = activityMonitor.logStart({ type: "fetch", url: `github.com/${owner}/${repo}` });

	if (!forceClone) {
		const sizeKB = await checkRepoSize(owner, repo);
		if (signal?.aborted) {
			activityMonitor.logComplete(activityId, 0);
			return null;
		}
		if (sizeKB !== null) {
			const sizeMB = sizeKB / 1024;
			if (sizeMB > config.maxRepoSizeMB) {
				if (signal?.aborted) {
					activityMonitor.logComplete(activityId, 0);
					return null;
				}
				const sizeNote =
					`Note: Repository is ${Math.round(sizeMB)}MB (threshold: ${config.maxRepoSizeMB}MB). ` +
					`Showing API-fetched content instead of full clone. Ask the user if they'd like to clone the full repo -- ` +
					`if yes, call fetch_content again with the same URL and add forceClone: true to the params.`;
				const apiView = await fetchViaApi(url, owner, repo, info, sizeNote);
				if (apiView) {
					activityMonitor.logComplete(activityId, 200);
					return apiView;
				}
				activityMonitor.logError(activityId, "api fallback unavailable for oversized repository");
				return null;
			}
		}
	}

	if (signal?.aborted) {
		activityMonitor.logComplete(activityId, 0);
		return null;
	}

	// Re-check: another concurrent caller may have started a clone while we awaited the size check
	const cachedAfterSizeCheck = cloneCache.get(key);
	if (cachedAfterSizeCheck) {
		const cachedResult = await awaitCachedClone(cachedAfterSizeCheck, url, owner, repo, info, signal);
		if (signal?.aborted) {
			activityMonitor.logComplete(activityId, 0);
		} else if (cachedResult) {
			activityMonitor.logComplete(activityId, 200);
		} else {
			activityMonitor.logError(activityId, "clone failed");
		}
		return cachedResult;
	}

	const clonePromise = webGitClone(owner, repo, info.ref).catch(error => {
    if (cloneCache.get(key)?.clonePromise === clonePromise) cloneCache.delete(key);
    throw error;
  });
	cloneCache.set(key, { clonePromise });

	const result = await clonePromise;
	if (signal?.aborted) {
		if (!result) cloneCache.delete(key);
		activityMonitor.logComplete(activityId, 0);
		return null;
	}

	if (!result) {
		cloneCache.delete(key);
		if (signal?.aborted) {
			activityMonitor.logComplete(activityId, 0);
			return null;
		}

		const apiFallback = await fetchViaApi(url, owner, repo, info);
		if (apiFallback) {
			activityMonitor.logComplete(activityId, 200);
			return apiFallback;
		}

		activityMonitor.logError(activityId, "clone and API fallback failed");
		return null;
	}

	activityMonitor.logComplete(activityId, 200);
	const content = await webGitContent(result, info.type, info.path);
	const title = info.path ? `${owner}/${repo} - ${info.path}` : `${owner}/${repo}`;
	return { url, title, content, error: null };
}

export function clearCloneCache(): void {
  // clone 是显式写根中的产物；切换会话只丢弃引用，不删除用户可能已修改的仓库。
  cloneCache.clear();
  cloneIdentity = undefined;
}
