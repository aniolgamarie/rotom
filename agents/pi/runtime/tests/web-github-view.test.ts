import assert from "node:assert/strict";
import { test } from "node:test";
import { githubView } from "../../packages/web-vendor/github-view-api.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1"), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
function fixture() {
  const calls = [];
  const connection = (nodes, bounded = false) => ({ nodes, pageInfo: { hasNextPage: bounded }, totalCount: nodes.length });
  const item = { title: "Fixture PR", number: 7, comments: connection([{ databaseId: "12", body: "comment" }], true),
    labels: connection([{ name: "fixture" }]), files: connection([{ path: "file.ts", additions: 1 }]),
    commits: connection([{ commit: { oid: "a".repeat(40), messageHeadline: "fixture commit" } }]),
    reviews: connection([{ state: "APPROVED", author: { login: "reviewer" } }]),
    statusCheckRollup: { contexts: connection([{ name: "fixture check", conclusion: "SUCCESS" }]) },
    closingIssuesReferences: connection([{ number: 8, title: "Fixture issue" }]),
    closedByPullRequestsReferences: connection([{ number: 9, title: "Fixture PR" }]) };
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {}, web_services: { github: {} },
    web_config: { githubToken: "$" + variable }, web_credential_variables: [variable] }, web: { async fetch(service, url, options) {
      calls.push({ service, url, options }); return Response.json({ data: { repository: { item } } });
    } } };
  globalThis[slot] = runtime; process.env[variable] = "synthetic-selected";
  return { runtime, calls, item, cleanup() { delete globalThis[slot]; delete process.env[variable]; } };
}
test("PR view keeps comments, reviews, commits, checks and references through fixed readonly queries", async () => {
  const f = fixture();
  try {
    const view = await githubView("pr", "fixture", "repo", 7);
    assert.equal(view.comments[0].body, "comment"); assert.equal(view.reviews[0].state, "APPROVED");
    assert.equal(view.commits[0].messageHeadline, "fixture commit"); assert.equal(view.statusCheckRollup[0].conclusion, "SUCCESS");
    assert.equal(view.closingIssuesReferences[0].number, 8); assert.deepEqual(view.agentcfgBoundedFields, ["comments"]);
    const request = f.calls[0], body = JSON.parse(request.options.body);
    assert.equal(request.service, "github"); assert.equal(request.options.method, "POST");
    assert.match(body.query, /^query /); assert.doesNotMatch(body.query, /mutation/);
    assert.deepEqual(body.variables, { owner: "fixture", repo: "repo", number: 7 });
    assert.equal(request.options.headers.get("Authorization"), "Bearer synthetic-selected");
    assert.equal(JSON.stringify(body).includes("synthetic-selected"), false);
    const issue = await githubView("issue", "fixture", "repo", 8);
    assert.equal(issue.closedByPullRequestsReferences[0].number, 9);
  } finally { f.cleanup(); }
});
test("GraphQL partial errors and invalid repository inputs cannot become a complete successful view", async () => {
  const f = fixture();
  try {
    f.runtime.web.fetch = async () => Response.json({ data: { repository: { item: f.item } }, errors: [{ message: "synthetic-private-server-error" }] });
    await assert.rejects(githubView("pr", "fixture", "repo", 7), error => error.message === "WEB_GITHUB_VIEW_INCOMPLETE");
    await assert.rejects(githubView("pr", "fixture/injected", "repo", 7), /VIEW_INVALID/);
    await assert.rejects(githubView("pr", "fixture", "repo", -1), /VIEW_INVALID/);
  } finally { f.cleanup(); }
});

test("actual PR and issue extraction uses owned API data without spawning gh", async () => {
  const f = fixture(); f.runtime.instanceRoot = "/fixture/instance";
  f.item.state = "OPEN"; f.item.body = "Fixture description";
  try {
    const nativeFetch = f.runtime.web.fetch;
    f.runtime.web.fetch = async (service, url, options) => url.endsWith("/graphql") ? nativeFetch(service, url, options) : Response.json([]);
    const { extractGitHubIssuePr } = await import("../../packages/web-vendor/github-issue-pr.ts");
    const result = await extractGitHubIssuePr("https://github.com/fixture/repo/pull/7");
    assert.equal(result.error, null); assert.match(result.content, /fixture check: SUCCESS/);
    assert.match(result.content, /reviewer: APPROVED/); assert.match(result.content, /Fixture issue/);
    assert.match(result.content, /bounded to 100 entries for: comments/);
    f.runtime.manifest.web_config.githubPrIssue = { enabled: false };
    assert.equal(await extractGitHubIssuePr("https://github.com/fixture/repo/issues/8"), null);
  } finally { f.cleanup(); }
});
