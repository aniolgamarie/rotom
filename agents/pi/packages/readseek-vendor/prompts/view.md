Digest a document's structure or selected content. Start with the overview, then narrow by page, node, kind, or depth instead of reading the whole document. PDF is the first supported document format.

## Parameters

- `path` — document file (PDF first).
- `node` — node ID to use as the view root.
- `page` — one-based source page.
- `kind` — node kind filter.
- `depth` — maximum depth below selected roots.
- `outline` — return outline nodes only.
- `visionMode` — analyze selected assets: `all`, `ocr`, `caption`, or `objects`.
- `visionLevel` — vision inference level: `low` (default), `medium`, or `high`;
  requires `visionMode`.

The Pi integration creates and reuses its document cache automatically. The
first call builds a structural index. Output is a bounded text projection with
stable node IDs and source-page references. Optional vision analysis is appended
for selected assets.
