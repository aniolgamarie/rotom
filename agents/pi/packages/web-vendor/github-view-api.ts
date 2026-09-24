// 固定只读 GraphQL，字段依据 GitHub 官方 schema；不接受模型提供的查询文本。
// https://docs.github.com/en/graphql/reference/pulls
// https://docs.github.com/en/graphql/reference/issues
// https://docs.github.com/en/graphql/reference/commits
import { githubRequest } from "./github-api.ts";
const common = `title number state author { login } createdAt closedAt body url
  labels(first:100) { nodes { name } pageInfo { hasNextPage } }
  milestone { title }
  comments(first:100) { totalCount nodes { databaseId: fullDatabaseId body createdAt author { login } } pageInfo { hasNextPage } }`;
const fields = {
  pr: `${common} isDraft baseRefName headRefName headRepositoryOwner { login } mergedAt additions deletions changedFiles
    files(first:100) { nodes { path additions deletions } pageInfo { hasNextPage } }
    commits(first:100) { nodes { commit { oid messageHeadline } } pageInfo { hasNextPage } }
    reviews(last:100) { nodes { author { login } state body } pageInfo { hasPreviousPage } }
    statusCheckRollup { contexts(first:100) { nodes {
      ... on CheckRun { name status conclusion } ... on StatusContext { context state }
    } pageInfo { hasNextPage } } }
    closingIssuesReferences(first:100) { nodes { number title url } pageInfo { hasNextPage } }`,
  issue: `${common} stateReason
    assignees(first:100) { nodes { login } pageInfo { hasNextPage } }
    closedByPullRequestsReferences(first:100, includeClosedPrs:true) { nodes { number title url } pageInfo { hasNextPage } }`,
};
function object(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
export async function githubView(kind: "pr" | "issue", owner: string, repo: string, number: number, signal?: AbortSignal, timeoutMs = 10000): Promise<Record<string, unknown> | null> {
  if (!Object.hasOwn(fields, kind) || ![owner, repo].every(value => /^[A-Za-z0-9_.-]+$/.test(value) && value !== "." && value !== "..")
      || !Number.isSafeInteger(number) || number < 1) throw new Error("WEB_GITHUB_VIEW_INVALID");
  const target = kind === "pr" ? "pullRequest" : "issue";
  const query = `query AgentcfgGitHubView($owner:String!,$repo:String!,$number:Int!) {
    repository(owner:$owner,name:$repo) { item:${target}(number:$number) { ${fields[kind]} } }
  }`;
  const response = await githubRequest("graphql", { query, variables: { owner, repo, number }, signal, timeoutMs });
  if (!response.ok) return null;
  const document = object(await response.json());
  if (Array.isArray(document?.errors) && document.errors.length) throw new Error("WEB_GITHUB_VIEW_INCOMPLETE");
  const item = object(object(object(document?.data)?.repository)?.item);
  if (!item) return null;
  const view = { ...item }, bounded: string[] = [];
  for (const name of ["labels", "comments", "files", "commits", "reviews", "closingIssuesReferences", "assignees", "closedByPullRequestsReferences"]) {
    const connection = object(item[name]);
    if (!connection) continue;
    const nodes = Array.isArray(connection.nodes) ? connection.nodes.filter(row => object(row)) : [];
    view[name] = name === "commits" ? nodes.flatMap(row => object(object(row)?.commit) ?? []) : nodes;
    if (name === "comments") view.commentsCount = connection.totalCount;
    const page = object(connection.pageInfo);
    if (page?.hasNextPage || page?.hasPreviousPage) bounded.push(name);
  }
  const checks = object(object(item.statusCheckRollup)?.contexts);
  view.statusCheckRollup = Array.isArray(checks?.nodes) ? checks.nodes : [];
  if (object(checks?.pageInfo)?.hasNextPage) bounded.push("checks");
  view.agentcfgBoundedFields = bounded;
  return view;
}
