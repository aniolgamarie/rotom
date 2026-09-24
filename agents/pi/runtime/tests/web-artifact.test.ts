import assert from "node:assert/strict";
import { test } from "node:test";
import { webPdfOutput } from "../web-artifact.ts";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
function fixture() {
  const calls = [], cleanups = [], validators = [], operation = { id: "web-pdf", controller: new AbortController() };
  const runtime = { instanceRoot: "/fixture/instance", cwd: "/project", owner: { role: "manager" },
    manifest: { plugins: ["pi-web"], options: { web: {}, paths: { roots: { documents: { path: "/project/documents", purpose: "write" } } } }, web_config: {} },
    web: { current: () => operation, cleanup: fn => cleanups.push(fn), verifyExternal: fn => validators.push(fn), track: value => value },
    supervisor: { async call(method, args) {
      calls.push({ method, args });
      if (method === "ordinary_prepare") return { operation_id: "pdf-write", lease_id: "pdf-lease", write: true };
      if (method === "reconcile") return { lease_id: "pdf-lease", protected: false, termination_evidence: { verified: true } };
      if (method === "ordinary_finish") return { finished: true };
      throw new Error("unexpected method");
    } },
    ordinaryOperations: { async write(ticket, content, expected, signal) { calls.push({ method: "write", content, expected, ticket, signal }); return { changed: true }; } },
  };
  globalThis[slot] = runtime; return { runtime, calls, validators, cleanups };
}
test("PDF extraction needs no implicit output directory; selected writes use ordinary permission and physical proof", async () => {
  const f = fixture();
  try {
    assert.equal(await webPdfOutput("document.md", "body"), null); assert.equal(f.calls.length, 0);
    await assert.rejects(webPdfOutput("document.md", "body", "/undeclared"), /UNBOUND/);
    f.runtime.manifest.options.web.pdf_output_root_ref = "documents";
    const path = await webPdfOutput("document.md", "body");
    assert.match(path, /^\/project\/documents\/document-[a-f0-9-]+\.md$/);
    assert.equal(f.calls[0].args.tool_name, "write"); assert.equal(f.calls[0].args.input.path, path);
    assert.equal(f.calls[1].expected, null); assert.equal(await f.validators[0](), true);
    for (const cleanup of f.cleanups) await cleanup();
    assert.equal(f.calls.at(-1).method, "ordinary_finish");
    await assert.rejects(webPdfOutput("../escape.md", "body"), /FILENAME/);
    await assert.rejects(webPdfOutput("document.md", "body", "/outside"), /UNBOUND/);
    await assert.rejects(webPdfOutput("document.md", "x".repeat(1024 * 1024 + 1)), /LIMIT/);
  } finally { delete globalThis[slot]; }
});
test("actual PDF renderer returns inline Markdown or the supervised artifact after selected fake Gemini extraction", async () => {
  const f = fixture(), variable = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
  try {
    f.runtime.manifest.web_config = { pdf: { provider: "gemini" }, geminiApiKey: "$" + variable };
    f.runtime.manifest.web_credential_variables = [variable]; f.runtime.manifest.web_services = { "gemini-api": {} };
    process.env[variable] = "synthetic-pdf-key";
    f.runtime.web.fetch = async service => {
      assert.equal(service, "gemini-api");
      return Response.json({ candidates: [{ finishReason: "STOP", content: { parts: [{ text: "<!-- Page 1 -->\nSynthetic PDF text" }] } }] });
    };
    const { extractPDFToMarkdown } = await import("../../packages/web-vendor/pdf-extract.ts");
    const result = await extractPDFToMarkdown(new ArrayBuffer(8), "https://example.invalid/fixture.pdf");
    assert.equal(result.outputPath, null); assert.match(result.content, /Synthetic PDF text/); assert.equal(result.pages, 1);
    assert.equal(f.calls.length, 0);
    f.runtime.manifest.options.web.pdf_output_root_ref = "documents";
    const saved = await extractPDFToMarkdown(new ArrayBuffer(8), "https://example.invalid/fixture.pdf");
    assert.match(saved.outputPath, /^\/project\/documents\//); assert.match(f.calls.find(row => row.method === "write").content, /Synthetic PDF text/);
    f.runtime.manifest.web_services = {};
    await assert.rejects(extractPDFToMarkdown(new ArrayBuffer(8), "https://example.invalid/fixture.pdf"), /PDF_PROVIDER_UNAVAILABLE/);
  } finally { delete globalThis[slot]; delete process.env[variable]; }
});

test("locked unpdf extracts a synthetic local PDF without a host, account, network, or implicit file output", async () => {
  const f = fixture();
  try {
    f.runtime.manifest.web_config = { pdf: { provider: "unpdf" } }; f.runtime.manifest.web_services = {};
    const stream = "BT /F1 12 Tf 72 720 Td (Synthetic local PDF text) Tj ET";
    const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
      "<< /Length " + stream.length + " >>\nstream\n" + stream + "\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"];
    let pdf = "%PDF-1.4\n"; const offsets = [0];
    for (const [index, object] of objects.entries()) { offsets.push(pdf.length); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; }
    const xref = pdf.length;
    pdf += "xref\n0 6\n0000000000 65535 f \n" + offsets.slice(1).map(value => String(value).padStart(10, "0") + " 00000 n \n").join("");
    pdf += "trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n";
    const { extractPDFToMarkdown } = await import("../../packages/web-vendor/pdf-extract.ts");
    const result = await extractPDFToMarkdown(new TextEncoder().encode(pdf).buffer, "https://example.invalid/local.pdf");
    assert.equal(result.pages, 1); assert.equal(result.outputPath, null); assert.match(result.content, /Synthetic local PDF text/);
    assert.equal(f.calls.length, 0);
  } finally { delete globalThis[slot]; }
});
