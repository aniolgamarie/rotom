import { readseekWorker, readseekSettings, readseekAvailability, wrapReadseekTool, recordReadseekAnchor } from "@agentcfg/pi-runtime/readseek-context";
// src/edit.ts
import { readFile as fsReadFile } from "node:fs/promises";
import { createPatch } from "diff";
import { withFileMutationQueue } from "@earendil-works/pi-coding-agent";
import { Type as Type2 } from "@sinclair/typebox";
import { Text as Text3 } from "@earendil-works/pi-tui";

// ../readseek-api/src/contract.ts
var DIGEST_FACETS = [
  "metadata",
  "content",
  "map",
  "diagnostics",
  "identity"
];
var VISION_MODES = ["none", "all", "ocr", "caption", "objects"];
var VISION_ANALYSIS_MODES = ["all", "ocr", "caption", "objects"];
var VISION_LEVELS = ["low", "medium", "high"];
var DOCUMENT_NODE_KINDS = [
  "artifact",
  "footer",
  "header",
  "heading",
  "marginal_label",
  "page",
  "page_number",
  "paragraph",
  "section",
  "structural_section"
];
var EDIT_VARIANTS = [
  "set_line",
  "replace_lines",
  "insert_after",
  "replace",
  "replace_symbol"
];
var TOOL_NAMES = [
  "digest",
  "edit",
  "write",
  "grep",
  "view",
  "search",
  "def",
  "refs",
  "rename"
];
var PARAM_DESCRIPTIONS = {
  path: "Absolute or relative file path",
  projectPath: "Path relative to the project directory",
  projectSearchPath: "File or directory to search; defaults to the project directory",
  searchPath: "File or directory to search; defaults to the current directory",
  language: "Language override when auto-detection is ambiguous",
  languageOverride: "Language override",
  languageSymbol: "Language override for symbol replacement",
  pattern: "AST pattern (ast-grep style), such as console.log($$$ARGS)",
  grepPattern: "Regex pattern; set literal for exact text",
  name: "Qualified or unqualified symbol name",
  refsName: "Identifier to find references for",
  scope: "Restrict results to the binding at the cursor",
  line: "One-based cursor line; required with scope",
  renameLine: "One-based cursor line of the symbol to rename",
  column: "One-based cursor byte column for disambiguation",
  cached: "In a Git repository, search tracked/indexed files",
  others: "In a Git repository, search untracked files",
  ignored: "With others=true, include ignored untracked files",
  select: "Facets: metadata, content, map, diagnostics, identity (default content)",
  selectComma: "Comma-separated facets: metadata, content, map, diagnostics, identity",
  at: "Location: line:N[:COLUMN], hash:HASH[:COLUMN], or symbol:NAME",
  end: "Last line to include",
  limit: "Maximum number of lines to include",
  digestDepth: "Maximum structural depth for map output; defaults to 1 in agent tools",
  offset: "One-based starting line",
  readLimit: "Maximum lines to return",
  symbolRead: "Symbol name to read",
  bundle: "Include related symbols from the same file; requires symbol",
  image: "Standalone image mode: none, all, ocr, caption, objects. Required for standalone images.",
  visionModeDigest: "Standalone image mode: none, all, caption, objects, or ocr",
  visionModeView: "Analyze selected assets: all, ocr, caption, or objects",
  visionLevel: "Vision inference level: low (default), medium, or high",
  node: "Node ID to use as the view root",
  page: "One-based source page",
  kind: "Node kind filter",
  depth: "Maximum depth below selected roots",
  outline: "Return outline nodes only",
  edits: "Use set_line, replace_lines, insert_after, replace_symbol, or replace",
  editVariant: "Exactly one nested edit variant",
  setLine: 'Replace one line: {"set_line":{"anchor":"LINE:HASH","new_text":"..."}}',
  replaceLines: 'Replace a range: {"replace_lines":{"start_anchor":"LINE:HASH","end_anchor":"LINE:HASH","new_text":"..."}}',
  insertAfter: 'Insert text: {"insert_after":{"anchor":"LINE:HASH","new_text":"..."}}',
  replace: 'Replace text: {"replace":{"old_text":"...","new_text":"..."}}',
  replaceSymbol: 'Replace a symbol: {"replace_symbol":{"symbol":"name","new_body":"..."}}',
  anchor: "Fresh LINE:HASH anchor for the line to replace",
  startAnchor: "Fresh LINE:HASH anchor for the first line in the range",
  endAnchor: "Fresh LINE:HASH anchor for the last line in the range",
  insertAnchor: "Fresh LINE:HASH anchor for the line after which to insert",
  newTextLine: "Replacement text; use an empty string to delete the line",
  newTextRange: "Replacement text; use an empty string to delete the range",
  newTextInsert: "Text to insert after the anchored line",
  oldText: "Exact text to find",
  newText: "Replacement text",
  all: "Replace every exact match",
  symbol: "Mapped symbol name",
  newBody: "Complete replacement body for the symbol",
  apply: "When supported by the host, apply the verified plan instead of previewing only",
  applyDefaultTrue: "Apply the verified edits; defaults to true",
  planHash: "Require the apply plan to match this dry-run plan hash",
  workspace: "Rename across the project",
  to: "New symbol name",
  postEditVerify: "Read back and verify persisted content",
  content: "Complete text file content",
  glob: "File-name glob, such as *.ts",
  ignoreCase: "Ignore case",
  literal: "Treat pattern literally",
  context: "Surrounding lines for each match",
  matchLimit: "Maximum matches to return",
  summary: "Return per-file counts",
  grepScope: "Group matches by enclosing symbol",
  scopeContext: "Context lines within each symbol"
};
var TOOL_DESCRIPTIONS = {
  digest: "Digest source content and images into the native CLI envelope. Returns metadata plus requested facets unchanged from `readseek digest`. Use it before edits to obtain fresh `LINE:HASH` anchors; use shallow maps for structural overviews, diagnostics for syntax checks, and identity for cursor context.",
  edit: 'Edit existing text files with fresh `LINE:HASH` anchors. Read or search first when no fresh anchors are available. Each `edits[]` item must use exactly one nested object: `{"set_line":{"anchor":"LINE:HASH","new_text":"..."}}`, `{"replace_lines":{"start_anchor":"LINE:HASH","end_anchor":"LINE:HASH","new_text":"..."}}`, `{"insert_after":{"anchor":"LINE:HASH","new_text":"..."}}`, `{"replace_symbol":{"symbol":"name","new_body":"..."}}`, or `{"replace":{"old_text":"...","new_text":"..."}}`.',
  write: "Create or replace a complete text file and return `LINE:HASH` anchors. Use `edit` for small changes to an existing file.",
  grep: "Search text or regex in files and return edit-ready `LINE:HASH` anchors. Use for identifiers, strings, configuration, errors, comments, and documentation.",
  view: "Digest a document's structure or selected content. Start with the overview, then narrow by page, node, kind, or depth instead of reading the whole document. PDF is the first supported document format.",
  search: "Search code by AST structure using ast-grep-style patterns. Results include line hashes usable as `LINE:HASH` anchors. Use `grep` for identifiers, strings, comments, configuration, documentation, or other plain text and regex.",
  def: "Go to a symbol definition or declaration by name. Accepts qualified or unqualified names; use this instead of text search for functions, methods, classes, types, and other declarations.",
  refs: "Find references or usages of an identifier by name or cursor binding. Results include enclosing symbols and line hashes usable as `LINE:HASH` anchors. Without cursor scope, results are identifier-name matches; with scope, they follow one binding and exclude shadows. Use text search for literals, and use this before renaming or deleting a symbol.",
  rename: "Rename a symbol at a source location. Resolvable same-named bindings are preserved; verified edits apply by default. Set `apply: false` to preview the plan before changing files."
};
function renderToolDescription(name, aliases = {}) {
  const desc = TOOL_DESCRIPTIONS[name];
  if (!desc)
    throw new Error(`Missing TOOL_DESCRIPTIONS for ${name}`);
  return TOOL_NAMES.reduce((description, toolName) => description.replaceAll(`\`${toolName}\``, `\`${aliases[toolName] ?? toolName}\``), desc);
}
var gitFlagsSchema = {
  cached: {
    type: "boolean",
    description: PARAM_DESCRIPTIONS.cached
  },
  others: {
    type: "boolean",
    description: PARAM_DESCRIPTIONS.others
  },
  ignored: {
    type: "boolean",
    description: PARAM_DESCRIPTIONS.ignored
  }
};
var editItemSchema = {
  type: "object",
  additionalProperties: false,
  minProperties: 1,
  maxProperties: 1,
  properties: {
    set_line: {
      type: "object",
      additionalProperties: false,
      required: ["anchor", "new_text"],
      properties: {
        anchor: { type: "string", description: PARAM_DESCRIPTIONS.anchor },
        new_text: { type: "string", description: PARAM_DESCRIPTIONS.newTextLine }
      },
      description: PARAM_DESCRIPTIONS.setLine
    },
    replace_lines: {
      type: "object",
      additionalProperties: false,
      required: ["start_anchor", "end_anchor", "new_text"],
      properties: {
        start_anchor: { type: "string", description: PARAM_DESCRIPTIONS.startAnchor },
        end_anchor: { type: "string", description: PARAM_DESCRIPTIONS.endAnchor },
        new_text: { type: "string", description: PARAM_DESCRIPTIONS.newTextRange }
      },
      description: PARAM_DESCRIPTIONS.replaceLines
    },
    insert_after: {
      type: "object",
      additionalProperties: false,
      required: ["anchor", "new_text"],
      properties: {
        anchor: { type: "string", description: PARAM_DESCRIPTIONS.insertAnchor },
        new_text: { type: "string", description: PARAM_DESCRIPTIONS.newTextInsert }
      },
      description: PARAM_DESCRIPTIONS.insertAfter
    },
    replace: {
      type: "object",
      additionalProperties: false,
      required: ["old_text", "new_text"],
      properties: {
        old_text: { type: "string", description: PARAM_DESCRIPTIONS.oldText },
        new_text: { type: "string", description: PARAM_DESCRIPTIONS.newText },
        all: { type: "boolean", description: PARAM_DESCRIPTIONS.all }
      },
      description: PARAM_DESCRIPTIONS.replace
    },
    replace_symbol: {
      type: "object",
      additionalProperties: false,
      required: ["symbol", "new_body"],
      properties: {
        symbol: { type: "string", description: PARAM_DESCRIPTIONS.symbol },
        new_body: { type: "string", description: PARAM_DESCRIPTIONS.newBody }
      },
      description: PARAM_DESCRIPTIONS.replaceSymbol
    }
  },
  description: PARAM_DESCRIPTIONS.editVariant
};
var TOOL_CONTRACTS = [
  {
    name: "digest",
    title: "Digest source",
    description: TOOL_DESCRIPTIONS.digest,
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: PARAM_DESCRIPTIONS.path },
        select: { type: "string", description: PARAM_DESCRIPTIONS.select },
        at: { type: "string", description: PARAM_DESCRIPTIONS.at },
        end: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.end },
        limit: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.limit },
        depth: { type: "integer", minimum: 0, description: PARAM_DESCRIPTIONS.digestDepth },
        language: { type: "string", description: PARAM_DESCRIPTIONS.languageOverride },
        visionMode: {
          type: "string",
          enum: [...VISION_MODES],
          description: PARAM_DESCRIPTIONS.visionModeDigest
        },
        visionLevel: {
          type: "string",
          enum: [...VISION_LEVELS],
          description: PARAM_DESCRIPTIONS.visionLevel
        }
      },
      required: ["path"],
      additionalProperties: false
    }
  },
  {
    name: "edit",
    title: "Hash-verified edit",
    description: TOOL_DESCRIPTIONS.edit,
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: PARAM_DESCRIPTIONS.path },
        edits: {
          type: "array",
          minItems: 1,
          description: PARAM_DESCRIPTIONS.edits,
          items: editItemSchema
        },
        language: { type: "string", description: PARAM_DESCRIPTIONS.languageSymbol },
        apply: { type: "boolean", description: PARAM_DESCRIPTIONS.apply },
        planHash: { type: "string", description: PARAM_DESCRIPTIONS.planHash },
        postEditVerify: { type: "boolean", description: PARAM_DESCRIPTIONS.postEditVerify }
      },
      required: ["path", "edits"],
      additionalProperties: false
    }
  },
  {
    name: "write",
    title: "Write file",
    description: TOOL_DESCRIPTIONS.write,
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: PARAM_DESCRIPTIONS.path },
        content: { type: "string", description: PARAM_DESCRIPTIONS.content }
      },
      required: ["path", "content"],
      additionalProperties: false
    }
  },
  {
    name: "grep",
    title: "Text search",
    description: TOOL_DESCRIPTIONS.grep,
    inputSchema: {
      type: "object",
      properties: {
        pattern: { type: "string", description: PARAM_DESCRIPTIONS.grepPattern },
        path: { type: "string", description: PARAM_DESCRIPTIONS.searchPath },
        glob: { type: "string", description: PARAM_DESCRIPTIONS.glob },
        ignoreCase: { type: "boolean", description: PARAM_DESCRIPTIONS.ignoreCase },
        literal: { type: "boolean", description: PARAM_DESCRIPTIONS.literal },
        context: { type: "integer", minimum: 0, description: PARAM_DESCRIPTIONS.context },
        limit: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.matchLimit },
        summary: { type: "boolean", description: PARAM_DESCRIPTIONS.summary },
        scope: {
          type: "string",
          enum: ["symbol"],
          description: PARAM_DESCRIPTIONS.grepScope
        },
        scopeContext: {
          type: "integer",
          minimum: 0,
          description: PARAM_DESCRIPTIONS.scopeContext
        }
      },
      required: ["pattern"],
      additionalProperties: false
    }
  },
  {
    name: "view",
    title: "View document",
    description: TOOL_DESCRIPTIONS.view,
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: PARAM_DESCRIPTIONS.path },
        node: { type: "string", description: PARAM_DESCRIPTIONS.node },
        page: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.page },
        kind: {
          type: "string",
          enum: [...DOCUMENT_NODE_KINDS],
          description: PARAM_DESCRIPTIONS.kind
        },
        depth: { type: "integer", minimum: 0, description: PARAM_DESCRIPTIONS.depth },
        outline: { type: "boolean", description: PARAM_DESCRIPTIONS.outline },
        visionMode: {
          type: "string",
          enum: [...VISION_ANALYSIS_MODES],
          description: PARAM_DESCRIPTIONS.visionModeView
        },
        visionLevel: {
          type: "string",
          enum: [...VISION_LEVELS],
          description: PARAM_DESCRIPTIONS.visionLevel
        }
      },
      required: ["path"],
      additionalProperties: false
    }
  },
  {
    name: "search",
    title: "AST search",
    description: TOOL_DESCRIPTIONS.search,
    inputSchema: {
      type: "object",
      properties: {
        pattern: { type: "string", description: PARAM_DESCRIPTIONS.pattern },
        path: { type: "string", description: PARAM_DESCRIPTIONS.searchPath },
        language: { type: "string", description: PARAM_DESCRIPTIONS.language },
        ...gitFlagsSchema
      },
      required: ["pattern"],
      additionalProperties: false
    }
  },
  {
    name: "def",
    title: "Find definition",
    description: TOOL_DESCRIPTIONS.def,
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: PARAM_DESCRIPTIONS.name },
        path: { type: "string", description: PARAM_DESCRIPTIONS.searchPath },
        language: { type: "string", description: PARAM_DESCRIPTIONS.language },
        ...gitFlagsSchema
      },
      required: ["name"],
      additionalProperties: false
    }
  },
  {
    name: "refs",
    title: "Find references",
    description: TOOL_DESCRIPTIONS.refs,
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: PARAM_DESCRIPTIONS.refsName },
        path: { type: "string", description: PARAM_DESCRIPTIONS.searchPath },
        language: { type: "string", description: PARAM_DESCRIPTIONS.language },
        scope: { type: "boolean", description: PARAM_DESCRIPTIONS.scope },
        line: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.line },
        column: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.column },
        ...gitFlagsSchema
      },
      additionalProperties: false
    }
  },
  {
    name: "rename",
    title: "Rename symbol",
    description: TOOL_DESCRIPTIONS.rename,
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: PARAM_DESCRIPTIONS.path },
        line: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.renameLine },
        column: { type: "integer", minimum: 1, description: PARAM_DESCRIPTIONS.column },
        to: { type: "string", description: PARAM_DESCRIPTIONS.to },
        workspace: { type: "boolean", description: PARAM_DESCRIPTIONS.workspace },
        apply: { type: "boolean", description: PARAM_DESCRIPTIONS.apply },
        planHash: { type: "string", description: PARAM_DESCRIPTIONS.planHash }
      },
      required: ["path", "line", "to"],
      additionalProperties: false
    }
  }
];
// ../readseek-api/src/policy.ts
var REPLACEABLE_TOOLS = [
  {
    tool: "digest",
    builtIn: "read",
    benefit: "it returns LINE:HASH anchors for safe edits."
  },
  {
    tool: "edit",
    builtIn: "edit",
    benefit: "it verifies fresh LINE:HASH anchors."
  },
  {
    tool: "grep",
    builtIn: "grep",
    benefit: "it returns LINE:HASH anchors."
  },
  {
    tool: "write",
    builtIn: "write",
    benefit: "it returns LINE:HASH anchors."
  }
];
var TOOL_COMPACT_GUIDELINES = {
  digest: [
    "Use `digest` for shallow maps, diagnostics, and identity; use `def`, `refs`, or `search` for targeted symbol questions."
  ],
  edit: [
    "Prefer set_line, replace_lines, and insert_after; use replace only when anchors are impractical."
  ],
  grep: [
    "Use `grep` with summary first for broad searches, then narrow by path, glob, or pattern."
  ],
  write: [
    "Use anchored edits rather than `write` for small changes or appends."
  ],
  search: [
    "Use `search` for AST patterns; use `grep` for plain text."
  ],
  refs: [
    "Use `refs` before changing a symbol; add scope plus line/column to follow one binding."
  ]
};
function resolveToolName(name, aliases = {}) {
  return aliases[name] ?? name;
}
function rewriteBacktickedToolNames(text, aliases = {}) {
  return TOOL_NAMES.reduce((rewritten, toolName) => rewritten.replaceAll(`\`${toolName}\``, `\`${resolveToolName(toolName, aliases)}\``), text);
}
function renderCompactGuidelines(name, aliases = {}) {
  return (TOOL_COMPACT_GUIDELINES[name] ?? []).map((guideline) => rewriteBacktickedToolNames(guideline, aliases));
}
function renderToolRoutingPolicy(options = {}) {
  const aliases = options.aliases ?? {};
  const digest = resolveToolName("digest", aliases);
  const edit = resolveToolName("edit", aliases);
  const write = resolveToolName("write", aliases);
  const grep = resolveToolName("grep", aliases);
  const search = resolveToolName("search", aliases);
  const def = resolveToolName("def", aliases);
  const refs = resolveToolName("refs", aliases);
  const rename = resolveToolName("rename", aliases);
  const view = resolveToolName("view", aliases);
  if (options.style === "server") {
    return [
      "Structural code navigation, document viewing, and hash-verified edits with readseek.",
      "For structural questions, prefer these tools to text Grep/Bash: targeted definitions, references, and AST search; shallow digest maps; diagnostics and identity; and document views.",
      `Use ${edit} for LINE:HASH-anchored mutations (preview with apply=false; apply defaults to true and re-checks plan_hash).`,
      "Paths resolve against CLAUDE_PROJECT_DIR. Native Read/Grep/Edit hooks provide passive context;",
      "call MCP tools for active navigation, document questions, or anchored edits."
    ].join(" ");
  }
  const title = options.title ?? "ReadSeek tool policy:";
  const bullets = [];
  if (options.preferOverBuiltIns) {
    bullets.push("- Prefer ReadSeek tools over built-ins when they can do the job.");
  }
  bullets.push(`- Read with ${digest} first; ${edit} needs fresh LINE:HASH anchors.`, `- Use ${grep} for text/regex, ${search} for AST patterns, ${def}/${refs} for targeted symbols, and shallow ${digest} maps only for file overviews.`, `- Use ${edit} for existing files, ${write} for whole-file creation or replacement, and ${rename} for symbol renames.`, `- Use ${view} for document structure; run ${digest} with select diagnostics after source edits for a quick syntax check.`);
  if (options.demoteBuiltIns && options.demoteBuiltIns.length > 0) {
    bullets.push(`- Do not use built-in ${options.demoteBuiltIns.join(", ")} when a ReadSeek tool can do the job.`);
  }
  return [title, ...bullets].join(`
`);
}
// ../readseek-api/src/hashline.ts
var HASH_LEN = 6;
var LINE_ANCHOR_RE = /^(\d+):([0-9a-fA-F]{6})$/;
function tryParseLineAnchor(anchor) {
  const match = LINE_ANCHOR_RE.exec(anchor.trim());
  if (!match) {
    return { ok: false, error: `invalid LINE:HASH anchor: ${anchor}` };
  }
  const digits = match[1];
  const line = Number.parseInt(digits, 10);
  if (!Number.isSafeInteger(line)) {
    return { ok: false, error: `Line number must be a safe integer, got ${digits} in "${anchor}".` };
  }
  if (line < 1) {
    return { ok: false, error: `Line number must be >= 1, got ${line} in "${anchor}".` };
  }
  return { ok: true, anchor: { line, hash: match[2].toLowerCase() } };
}

// ../readseek-api/src/validation.ts
function validateGitSelection(input) {
  if (input.ignored && !input.others) {
    return { ok: false, error: "ignored requires others=true" };
  }
  return { ok: true };
}
function validateRefsNameVsScope(input) {
  if (input.scope) {
    if (input.line === undefined) {
      return { ok: false, error: "scope requires line" };
    }
    return { ok: true };
  }
  if (input.line !== undefined || input.column !== undefined) {
    return { ok: false, error: "line/column require scope=true" };
  }
  if (typeof input.name !== "string" || input.name.length === 0) {
    return { ok: false, error: "name is required when scope is not set" };
  }
  return { ok: true };
}
function validateVisionLevelVsMode(input) {
  if (input.outline && (input.visionMode !== undefined || input.visionLevel !== undefined)) {
    return { ok: false, error: "Cannot combine outline with visionMode or visionLevel" };
  }
  if (input.visionLevel !== undefined && input.visionMode === undefined) {
    return { ok: false, error: "visionLevel requires visionMode" };
  }
  return { ok: true };
}
var VARIANT_FIELDS = {
  set_line: ["anchor", "new_text"],
  replace_lines: ["start_anchor", "end_anchor", "new_text"],
  insert_after: ["anchor", "new_text"],
  replace: ["old_text", "new_text"],
  replace_symbol: ["symbol", "new_body"]
};
function isEditVariant(value) {
  return EDIT_VARIANTS.includes(value);
}
function parseEditItem(item, index) {
  const keys = Object.keys(item);
  const variant = keys[0];
  if (keys.length !== 1 || variant === undefined || !isEditVariant(variant)) {
    return {
      ok: false,
      error: `edits[${index}] must contain exactly one of: ${EDIT_VARIANTS.join(", ")}. Got: [${keys.join(", ")}]`
    };
  }
  const payload = item[variant];
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { ok: false, error: `edits[${index}].${variant} must be an object` };
  }
  const expected = VARIANT_FIELDS[variant];
  const allowed = variant === "replace" ? [...expected, "all"] : [...expected];
  const actual = Object.keys(payload);
  if (actual.some((field) => !allowed.includes(field)) || expected.some((field) => !actual.includes(field))) {
    return { ok: false, error: `edits[${index}].${variant} contains invalid fields` };
  }
  const values = payload;
  for (const field of expected) {
    if (typeof values[field] !== "string") {
      return { ok: false, error: `edits[${index}].${variant}.${field} must be a string` };
    }
  }
  if (variant === "replace" && values.all !== undefined && typeof values.all !== "boolean") {
    return { ok: false, error: `edits[${index}].replace.all must be a boolean` };
  }
  for (const field of expected) {
    if (!field.endsWith("anchor"))
      continue;
    const parsed = tryParseLineAnchor(values[field]);
    if (!parsed.ok) {
      return { ok: false, error: `edits[${index}].${variant}.${field}: ${parsed.error}` };
    }
  }
  return { ok: true, edit: item };
}
function validateExactlyOneEditVariant(edits) {
  if (!Array.isArray(edits) || edits.length === 0) {
    return { ok: false, error: "edits must contain at least one edit" };
  }
  const normalized = [];
  for (let index = 0;index < edits.length; index++) {
    const item = edits[index];
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return { ok: false, error: `edits[${index}] must be an edit object` };
    }
    const parsed = parseEditItem(item, index);
    if (!parsed.ok)
      return parsed;
    normalized.push(parsed.edit);
  }
  return { ok: true, edits: normalized };
}
var MIN_SAFE_INTEGER = BigInt(Number.MIN_SAFE_INTEGER);
var MAX_SAFE_INTEGER = BigInt(Number.MAX_SAFE_INTEGER);
// ../readseek-api/src/argv.ts
var DEFAULT_DIGEST_MAP_DEPTH = 1;
function buildLineLocation(line, column) {
  return column === undefined ? `line:${line}` : `line:${line}:${column}`;
}
function appendGitSelectionArgs(args, input) {
  const validated = validateGitSelection(input);
  if (!validated.ok) {
    throw new Error(validated.error);
  }
  if (input.cached)
    args.push("--cached");
  if (input.others)
    args.push("--others");
  if (input.ignored)
    args.push("--ignored");
  return args;
}
function pushOptionalString(args, flag, value) {
  if (value !== undefined)
    args.push(flag, value);
}
function pushOptionalNumber(args, flag, value) {
  if (value !== undefined)
    args.push(flag, String(value));
}
function appendApplyAndPlanHash(args, input) {
  const order = input.flagOrder ?? "apply-first";
  if (order === "plan-hash-first") {
    pushOptionalString(args, "--plan-hash", input.planHash);
    if (input.apply)
      args.push("--apply");
    return args;
  }
  if (input.apply)
    args.push("--apply");
  pushOptionalString(args, "--plan-hash", input.planHash);
  return args;
}
function selectArg(select) {
  if (select === undefined)
    return;
  return Array.isArray(select) ? select.join(",") : select;
}
function selectsDigestMap(select) {
  const value = selectArg(select);
  return value?.split(",").some((facet) => facet.trim() === "map") ?? false;
}
function buildDigestArgs(input) {
  const vision = validateVisionLevelVsMode({
    visionMode: input.visionMode,
    visionLevel: input.visionLevel
  });
  if (!vision.ok)
    throw new Error(vision.error);
  const selectsMap = selectsDigestMap(input.select);
  if (input.depth !== undefined) {
    if (!Number.isInteger(input.depth) || input.depth < 0) {
      throw new Error("depth must be a non-negative integer");
    }
    if (!selectsMap)
      throw new Error("depth requires the map facet");
  }
  const args = [];
  if (input.readseekDir !== undefined)
    args.push("--readseek-dir", input.readseekDir);
  args.push("digest", input.path);
  const select = selectArg(input.select);
  if (select !== undefined)
    args.push("--select", select);
  pushOptionalString(args, "--at", input.at);
  pushOptionalNumber(args, "--end", input.end);
  pushOptionalNumber(args, "--limit", input.limit);
  pushOptionalNumber(args, "--depth", input.depth);
  pushOptionalString(args, "--language", input.language);
  pushOptionalString(args, "--vision-mode", input.visionMode);
  pushOptionalString(args, "--vision-level", input.visionLevel);
  pushOptionalString(args, "--stdin-name", input.stdinName);
  return args;
}
function buildViewArgs(input) {
  const vision = validateVisionLevelVsMode({
    visionMode: input.visionMode,
    visionLevel: input.visionLevel,
    outline: input.outline
  });
  if (!vision.ok)
    throw new Error(vision.error);
  const args = [];
  if (input.readseekDir !== undefined)
    args.push("--readseek-dir", input.readseekDir);
  args.push("view", input.path);
  if (input.format !== undefined)
    args.push("--format", input.format);
  pushOptionalString(args, "--node", input.node);
  pushOptionalNumber(args, "--page", input.page);
  pushOptionalString(args, "--kind", input.kind);
  pushOptionalNumber(args, "--depth", input.depth);
  if (input.outline)
    args.push("--outline");
  pushOptionalString(args, "--vision-mode", input.visionMode);
  pushOptionalString(args, "--vision-level", input.visionLevel);
  return args;
}
function buildSearchArgs(input) {
  const args = ["search", input.pattern];
  pushOptionalString(args, "--path", input.path);
  pushOptionalString(args, "--language", input.language);
  pushOptionalNumber(args, "--limit", input.limit);
  return appendGitSelectionArgs(args, input);
}
function buildDefArgs(input) {
  const args = ["def", input.name];
  pushOptionalString(args, "--path", input.path);
  if (input.format !== undefined)
    args.push("--format", input.format);
  pushOptionalString(args, "--language", input.language);
  return appendGitSelectionArgs(args, input);
}
function buildRefsArgs(input) {
  const validated = validateRefsNameVsScope(input);
  if (!validated.ok)
    throw new Error(validated.error);
  const args = ["refs"];
  if (input.name !== undefined)
    args.push(input.name);
  pushOptionalString(args, "--path", input.path);
  if (input.scope) {
    args.push("--scope");
    pushOptionalNumber(args, "--line", input.line);
    pushOptionalNumber(args, "--column", input.column);
  }
  if (input.format !== undefined)
    args.push("--format", input.format);
  pushOptionalString(args, "--language", input.language);
  return appendGitSelectionArgs(args, input);
}
function buildEditArgs(input) {
  const args = ["edit", input.path];
  appendApplyAndPlanHash(args, {
    apply: input.apply,
    planHash: input.planHash,
    flagOrder: input.flagOrder ?? "apply-first"
  });
  pushOptionalString(args, "--language", input.language);
  if (input.requestFromStdin)
    args.push("--edits", "-");
  return args;
}
function buildRenameArgs(input) {
  const args = ["rename", input.path, "--at", buildLineLocation(input.line, input.column), "--to", input.to];
  if (input.workspace !== undefined)
    args.push(`--workspace=${input.workspace}`);
  appendApplyAndPlanHash(args, {
    apply: input.apply,
    planHash: input.planHash,
    flagOrder: input.flagOrder ?? "plan-hash-first"
  });
  pushOptionalString(args, "--language", input.language);
  return appendGitSelectionArgs(args, input);
}
// ../readseek-api/src/platform.ts
import { accessSync, constants as fsConstants, existsSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
var READSEEK_BINARY_ENV = "READSEEK_BINARY";
var READSEEK_PLATFORM_PACKAGES = {
  "darwin-arm64": "@jarkkojs/readseek-darwin-arm64",
  "linux-arm64": "@jarkkojs/readseek-linux-arm64",
  "linux-x64": "@jarkkojs/readseek-linux-x64",
  "win32-x64": "@jarkkojs/readseek-win32-x64"
};
var resolveFromPackage = createRequire(import.meta.url).resolve;
function readSeekBinaryName(platform = process.platform) {
  return platform === "win32" ? "readseek.exe" : "readseek";
}
function readSeekPlatformKey(platform = process.platform, arch = process.arch) {
  return `${platform}-${arch}`;
}
function resolveReadSeekBinaryOverride(environment = process.env) {
  const binaryPath = environment[READSEEK_BINARY_ENV];
  if (binaryPath === undefined)
    return null;
  if (!path.isAbsolute(binaryPath)) {
    throw new Error(`${READSEEK_BINARY_ENV} must be an absolute path to the readseek executable`);
  }
  try {
    if (!statSync(binaryPath).isFile())
      throw new Error("not a regular file");
    accessSync(binaryPath, fsConstants.X_OK);
  } catch (error) {
    throw new Error(`${READSEEK_BINARY_ENV} does not point to an executable file: ${binaryPath}`, {
      cause: error
    });
  }
  return binaryPath;
}
function resolveReadSeekBinaryFromPackages(resolver = resolveFromPackage, options = {}) {
  const resolve = typeof resolver === "function" ? resolver : resolver.resolve.bind(resolver);
  const platform = options.platform ?? process.platform;
  const arch = options.arch ?? process.arch;
  const key = readSeekPlatformKey(platform, arch);
  const platformPackage = READSEEK_PLATFORM_PACKAGES[key];
  if (!platformPackage) {
    const supported = Object.keys(READSEEK_PLATFORM_PACKAGES).join(", ");
    throw new Error(`@jarkkojs/readseek-api ships no binary for ${key}; it supports ${supported}`);
  }
  const metaPackage = options.metaPackage ?? "@jarkkojs/readseek-api";
  const metaPackageJson = resolve(`${metaPackage}/package.json`);
  const metaPackageDir = path.dirname(metaPackageJson);
  let packageJsonPath;
  try {
    packageJsonPath = resolve(`${platformPackage}/package.json`);
  } catch {
    packageJsonPath = resolve(`${platformPackage}/package.json`, {
      paths: [metaPackageDir]
    });
  }
  const binaryPath = path.join(path.dirname(packageJsonPath), "bin", readSeekBinaryName(platform));
  accessSync(binaryPath, fsConstants.X_OK);
  return binaryPath;
}
// ../readseek-api/src/json.ts
var READSEEK_USAGE_HINT = /\n\s*Run readseek(?: [\w-]+)* --help for more information\.?\s*$/;
function cleanReadSeekErrorText(stderr) {
  return stderr.replace(READSEEK_USAGE_HINT, "").replace(/^error:\s*/i, "").replace(/\s*\n\s*/g, " ").trim();
}
function parseReadSeekJson(stdout) {
  try {
    return JSON.parse(stdout);
  } catch {
    const preview = stdout.trim().slice(0, 200);
    throw new Error(`readseek returned invalid JSON: ${preview}`);
  }
}
// ../readseek-api/src/process.ts
var DEFAULT_READSEEK_TIMEOUT_MS = 120000;
var DEFAULT_MAX_OUTPUT_BYTES = 32 * 1024 * 1024;
function resolveProcessLimits(options = {}) {
  return {
    timeoutMs: options.timeoutMs ?? DEFAULT_READSEEK_TIMEOUT_MS,
    maxOutputBytes: options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES,
    cancelable: options.cancelable !== false
  };
}
function readSeekCancellationError(signal) {
  const reason = signal?.reason;
  return reason instanceof Error && reason.name !== "AbortError" ? reason : new Error("readseek cancelled");
}
function failureFromProcessResult(result, options = {}) {
  if (options.overflow) {
    return new Error(`readseek ${options.overflow} exceeded the ${options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES}-byte output limit`);
  }
  if (options.timedOut) {
    return new Error(`readseek timed out after ${options.timeoutMs ?? DEFAULT_READSEEK_TIMEOUT_MS} ms`);
  }
  const cleaned = cleanReadSeekErrorText(result.stderr);
  if (cleaned)
    return new Error(cleaned);
  if (result.signal)
    return new Error(`readseek killed by signal ${result.signal}`);
  return new Error(`readseek exited with status ${result.exitCode}`);
}
function ensureSuccessfulStdout(result) {
  if (result.exitCode === 0)
    return result.stdout;
  throw failureFromProcessResult(result);
}
function parseSuccessfulJson(result) {
  return parseReadSeekJson(ensureSuccessfulStdout(result));
}
// ../readseek-api/src/process-node.ts
import { spawn } from "node:child_process";
import { StringDecoder } from "node:string_decoder";
function attachBoundedStream(stream, maxOutputBytes, onOverflow) {
  const decoder = new StringDecoder("utf8");
  let text = "";
  let bytes = 0;
  let overflowed = false;
  stream.on("data", (chunk) => {
    if (overflowed)
      return;
    const buffer = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
    bytes += buffer.length;
    if (bytes > maxOutputBytes) {
      overflowed = true;
      onOverflow();
      return;
    }
    text += decoder.write(buffer);
  });
  return {
    text: () => text + decoder.end()
  };
}
async function runReadSeekNode(binaryPath, args, options = {}) {
  const limits = resolveProcessLimits(options);
  if (limits.cancelable && options.signal?.aborted) {
    throw readSeekCancellationError(options.signal);
  }
  return await new Promise((resolve, reject) => {
    let settled = false;
    let child;
    let timer;
    const finish = (result) => {
      if (settled)
        return;
      settled = true;
      if (timer !== undefined)
        clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      resolve(result);
    };
    const fail = (error) => {
      if (settled)
        return;
      settled = true;
      if (timer !== undefined)
        clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
      reject(error instanceof Error ? error : new Error(String(error)));
    };
    const terminate = (error) => {
      if (settled)
        return;
      fail(error);
      try {
        child.kill("SIGKILL");
      } catch {}
    };
    const onAbort = () => {
      terminate(readSeekCancellationError(options.signal));
    };
    try {
      child = spawn(binaryPath, [...args], {
        cwd: options.cwd,
        env: process.env,
        shell: false,
        stdio: [options.stdin === undefined ? "ignore" : "pipe", "pipe", "pipe"],
        windowsHide: true
      });
    } catch (error) {
      fail(error);
      return;
    }
    const stdout = attachBoundedStream(child.stdout, limits.maxOutputBytes, () => {
      terminate(failureFromProcessResult({ stdout: "", stderr: "", exitCode: null, signal: null }, { overflow: "stdout", maxOutputBytes: limits.maxOutputBytes }));
    });
    const stderr = attachBoundedStream(child.stderr, limits.maxOutputBytes, () => {
      terminate(failureFromProcessResult({ stdout: "", stderr: "", exitCode: null, signal: null }, { overflow: "stderr", maxOutputBytes: limits.maxOutputBytes }));
    });
    timer = setTimeout(() => {
      terminate(failureFromProcessResult({ stdout: "", stderr: "", exitCode: null, signal: null }, { timedOut: true, timeoutMs: limits.timeoutMs }));
    }, limits.timeoutMs);
    timer.unref?.();
    if (limits.cancelable && options.signal) {
      options.signal.addEventListener("abort", onAbort, { once: true });
    }
    if (options.stdin !== undefined) {
      child.stdin.on("error", (error) => {
        if (error.code !== "EPIPE")
          fail(error);
      });
      child.stdin.end(options.stdin, "utf8");
    }
    child.on("error", fail);
    child.on("close", (code, signal) => {
      finish({
        stdout: stdout.text(),
        stderr: stderr.text(),
        exitCode: code,
        signal
      });
    });
  });
}
async function runReadSeekNodeText(binaryPath, args, options = {}) {
  return ensureSuccessfulStdout(await runReadSeekNode(binaryPath, args, options));
}
async function runReadSeekNodeJson(binaryPath, args, options = {}) {
  return parseSuccessfulJson(await runReadSeekNode(binaryPath, args, options));
}
// ../readseek-api/src/client.ts
function classifyReadSeekFailure(err) {
  const failure = err;
  const message = String(failure?.message ?? err);
  const missing = failure?.code === "ENOENT" || /Cannot find package|Cannot find module|no such file/i.test(message);
  if (missing) {
    return { code: "readseek-not-installed", message, hint: "Run npm install to install @jarkkojs/readseek." };
  }
  return { code: "readseek-execution-error", message };
}
function requireNumber(value, field) {
  if (typeof value !== "number" || !Number.isSafeInteger(value))
    throw new Error(`invalid readseek ${field}: expected safe integer`);
  return value;
}
function requireString(value, field) {
  if (typeof value !== "string")
    throw new Error(`invalid readseek ${field}`);
  return value;
}
function requireBoolean(value, field) {
  if (typeof value !== "boolean")
    throw new Error(`invalid readseek ${field}: expected boolean`);
  return value;
}
function optionalString(value, field) {
  if (value === undefined || value === null)
    return;
  return requireString(value, field);
}
function parseHashline(value, field) {
  if (!value || typeof value !== "object")
    throw new Error(`invalid readseek ${field}`);
  const item = value;
  return {
    line: requireNumber(item.line, `${field}.line`),
    hash: requireString(item.hash, `${field}.hash`),
    text: requireString(item.text, `${field}.text`)
  };
}
function parseSearchHashlines(value, field) {
  if (!Array.isArray(value))
    throw new Error(`invalid readseek ${field}`);
  return value.map((line) => parseHashline(line, field));
}
function parseReadOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek read output");
  const output = value;
  const hashlines = output.hashlines;
  if (!Array.isArray(hashlines))
    throw new Error("invalid readseek hashlines");
  return {
    file: requireString(output.file, "file"),
    language: requireString(output.language, "language"),
    line_count: requireNumber(output.line_count, "line_count"),
    file_hash: requireString(output.file_hash, "file_hash"),
    start_line: requireNumber(output.start_line, "start_line"),
    end_line: requireNumber(output.end_line, "end_line"),
    hashlines: hashlines.map((line) => parseHashline(line, "hashline"))
  };
}
function parseMapNode(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek map node");
  const node = value;
  if (!Array.isArray(node.children))
    throw new Error("invalid readseek map node children");
  return {
    kind: requireString(node.kind, "map node.kind"),
    name: requireString(node.name, "map node.name"),
    start_line: requireNumber(node.start_line, "map node.start_line"),
    end_line: requireNumber(node.end_line, "map node.end_line"),
    start_anchor: requireString(node.start_anchor, "map node.start_anchor"),
    end_anchor: requireString(node.end_anchor, "map node.end_anchor"),
    children: node.children.map(parseMapNode)
  };
}
function parseMapOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek map output");
  const output = value;
  const symbols = output.symbols;
  if (!Array.isArray(symbols))
    throw new Error("invalid readseek symbols");
  return {
    file: requireString(output.file, "file"),
    language: requireString(output.language, "language"),
    line_count: requireNumber(output.line_count, "line_count"),
    file_hash: requireString(output.file_hash, "file_hash"),
    root: parseMapNode(output.root),
    symbols: symbols.map((symbol) => {
      if (!symbol || typeof symbol !== "object")
        throw new Error("invalid readseek symbol");
      const item = symbol;
      return {
        kind: requireString(item.kind, "symbol.kind"),
        name: requireString(item.name, "symbol.name"),
        qualified_name: requireString(item.qualified_name, "symbol.qualified_name"),
        start_line: requireNumber(item.start_line, "symbol.start_line"),
        end_line: requireNumber(item.end_line, "symbol.end_line"),
        start_hash: requireString(item.start_hash, "symbol.start_hash"),
        end_hash: requireString(item.end_hash, "symbol.end_hash")
      };
    })
  };
}
function parseSearchOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek search output");
  const output = value;
  if (!Array.isArray(output.results))
    throw new Error("invalid readseek search results");
  return output.results.map((result) => {
    if (!result || typeof result !== "object")
      throw new Error("invalid readseek search result");
    const file = result;
    if (!Array.isArray(file.matches))
      throw new Error("invalid readseek search matches");
    return {
      file: requireString(file.file, "search.file"),
      language: requireString(file.language, "search.language"),
      file_hash: requireString(file.file_hash, "search.file_hash"),
      matches: file.matches.map((match) => {
        if (!match || typeof match !== "object")
          throw new Error("invalid readseek search match");
        const item = match;
        if (!Array.isArray(item.captures))
          throw new Error("invalid readseek search captures");
        return {
          pattern_index: item.pattern_index === undefined ? 0 : requireNumber(item.pattern_index, "search.match.pattern_index"),
          start_line: requireNumber(item.start_line, "search.match.start_line"),
          end_line: requireNumber(item.end_line, "search.match.end_line"),
          start_hash: requireString(item.start_hash, "search.match.start_hash"),
          end_hash: requireString(item.end_hash, "search.match.end_hash"),
          hashlines: parseSearchHashlines(item.hashlines, "search.match.hashlines"),
          captures: item.captures.map((capture) => {
            if (!capture || typeof capture !== "object")
              throw new Error("invalid readseek search capture");
            const captureItem = capture;
            return {
              name: requireString(captureItem.name, "search.capture.name"),
              start_line: requireNumber(captureItem.start_line, "search.capture.start_line"),
              end_line: requireNumber(captureItem.end_line, "search.capture.end_line"),
              start_hash: requireString(captureItem.start_hash, "search.capture.start_hash"),
              end_hash: requireString(captureItem.end_hash, "search.capture.end_hash"),
              hashlines: parseSearchHashlines(captureItem.hashlines, "search.capture.hashlines")
            };
          })
        };
      })
    };
  });
}
function parseRefsOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek refs output");
  const output = value;
  if (!Array.isArray(output.references))
    throw new Error("invalid readseek references");
  return output.references.map((reference) => {
    if (!reference || typeof reference !== "object")
      throw new Error("invalid readseek reference");
    const item = reference;
    const symbol = item.symbol;
    const enclosing = symbol && typeof symbol === "object" ? optionalString(symbol.qualified_name, "reference.symbol.qualified_name") : undefined;
    return {
      file: requireString(item.file, "reference.file"),
      line: requireNumber(item.line, "reference.line"),
      column: requireNumber(item.column, "reference.column"),
      line_hash: requireString(item.line_hash, "reference.line_hash"),
      text: requireString(item.text, "reference.text"),
      enclosingSymbol: enclosing
    };
  });
}
function parseDiagnosticKind(value) {
  if (value === "error" || value === "missing")
    return value;
  throw new Error("invalid readseek diagnostic.kind");
}
function parseCheckOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek check output");
  const output = value;
  if (!Array.isArray(output.diagnostics))
    throw new Error("invalid readseek diagnostics");
  return {
    file_hash: optionalString(output.file_hash, "file_hash"),
    errorCount: requireNumber(output.error_count, "error_count"),
    missingCount: requireNumber(output.missing_count, "missing_count"),
    diagnostics: output.diagnostics.map((diagnostic) => {
      if (!diagnostic || typeof diagnostic !== "object")
        throw new Error("invalid readseek diagnostic");
      const item = diagnostic;
      return {
        kind: parseDiagnosticKind(item.kind),
        start_line: requireNumber(item.start_line, "diagnostic.start_line"),
        end_line: requireNumber(item.end_line, "diagnostic.end_line")
      };
    })
  };
}
function parseDetectedObjects(value) {
  if (value === undefined || value === null)
    return;
  if (!Array.isArray(value))
    throw new Error("invalid readseek detect objects");
  return value.map((object) => {
    if (!object || typeof object !== "object")
      throw new Error("invalid readseek detect object");
    const item = object;
    const bbox = item.bbox;
    if (!Array.isArray(bbox) || bbox.length !== 4)
      throw new Error("invalid readseek detect object.bbox");
    return {
      label: requireString(item.label, "object.label"),
      bbox: bbox.map((n, i) => requireNumber(n, `object.bbox[${i}]`))
    };
  });
}
function parseImageEncoding(value) {
  if (value === "base64")
    return value;
  throw new Error("invalid image encoding");
}
function parseDetectOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek detect output");
  const output = value;
  const type = requireString(output.type, "type");
  const file = requireString(output.file, "file");
  const mime = optionalString(output.mime, "mime");
  if (type === "application/pdf") {
    if (output.format !== "pdf")
      throw new Error("invalid readseek PDF format");
    return {
      kind: "pdf",
      type,
      file,
      mime,
      format: output.format,
      pages: requireNumber(output.pages, "pages")
    };
  }
  if (output.width !== undefined || output.height !== undefined) {
    return {
      kind: "image",
      type,
      file,
      mime,
      format: requireString(output.format, "format"),
      width: requireNumber(output.width, "width"),
      height: requireNumber(output.height, "height"),
      animated: requireBoolean(output.animated, "animated"),
      encoding: output.encoding === undefined ? undefined : parseImageEncoding(output.encoding),
      data: output.data === undefined ? undefined : requireString(output.data, "data"),
      ocr: optionalString(output.ocr, "ocr"),
      caption: optionalString(output.caption, "caption"),
      objects: parseDetectedObjects(output.objects)
    };
  }
  if (output.language !== undefined) {
    return {
      kind: "source",
      type,
      file,
      language: requireString(output.language, "language"),
      engine: optionalString(output.engine, "engine"),
      supported: requireBoolean(output.supported, "supported"),
      mime,
      syntax: optionalString(output.syntax, "syntax")
    };
  }
  return { kind: "text", type, file, mime };
}
function parseDocumentCache(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek document cache");
  const cache = value;
  const state = requireString(cache.state, "cache.state");
  if (state !== "built" && state !== "reused")
    throw new Error("invalid readseek cache.state");
  return {
    content_hash: requireString(cache.content_hash, "cache.content_hash"),
    state
  };
}
function parseIdentifyOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek identify output");
  const output = value;
  const identifier = output.identifier;
  const symbol = output.symbol;
  return {
    file: requireString(output.file, "file"),
    language: requireString(output.language, "language"),
    engine: optionalString(output.engine, "engine"),
    line_count: requireNumber(output.line_count, "line_count"),
    file_hash: requireString(output.file_hash, "file_hash"),
    line: requireNumber(output.line, "line"),
    column: requireNumber(output.column, "column"),
    line_hash: requireString(output.line_hash, "line_hash"),
    identifier: identifier && typeof identifier === "object" ? {
      text: requireString(identifier.text, "identifier.text"),
      start_column: requireNumber(identifier.start_column, "identifier.start_column"),
      end_column: requireNumber(identifier.end_column, "identifier.end_column"),
      start_byte: requireNumber(identifier.start_byte, "identifier.start_byte"),
      end_byte: requireNumber(identifier.end_byte, "identifier.end_byte")
    } : undefined,
    symbol: symbol && typeof symbol === "object" ? {
      name: requireString(symbol.name, "symbol.name"),
      kind: requireString(symbol.kind, "symbol.kind"),
      qualified_name: requireString(symbol.qualified_name, "symbol.qualified_name"),
      start_line: requireNumber(symbol.start_line, "symbol.start_line"),
      end_line: requireNumber(symbol.end_line, "symbol.end_line")
    } : undefined
  };
}
function parseImageContent(value) {
  const detection = parseDetectOutput(value);
  if (detection.kind !== "image")
    throw new Error("invalid readseek image content");
  return detection;
}
function parseTextContent(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek content");
  const output = value;
  if (output.hashlines !== undefined && output.start_line === undefined) {
    const hashlines = parseSearchHashlines(output.hashlines, "content.hashlines");
    const first = hashlines[0];
    const last = hashlines[hashlines.length - 1];
    return {
      file: requireString(output.file, "file"),
      language: requireString(output.language, "language"),
      line_count: requireNumber(output.line_count, "line_count"),
      file_hash: requireString(output.file_hash, "file_hash"),
      start_line: first?.line ?? 1,
      end_line: last?.line ?? 0,
      hashlines
    };
  }
  return parseReadOutput(value);
}
function parseDigestEnvelope(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek digest output");
  const output = value;
  if (output.metadata === undefined)
    throw new Error("invalid readseek digest metadata");
  const result = {
    metadata: parseDetectOutput(output.metadata)
  };
  if (output.cache !== undefined)
    result.cache = parseDocumentCache(output.cache);
  if (output.content !== undefined)
    result.content = output.content;
  if (output.map !== undefined)
    result.map = parseMapOutput(output.map);
  if (output.diagnostics !== undefined)
    result.diagnostics = parseCheckOutput(output.diagnostics);
  if (output.identity !== undefined)
    result.identity = parseIdentifyOutput(output.identity);
  return result;
}
function parseEditOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek edit output");
  const output = value;
  return {
    file: requireString(output.file, "file"),
    before_hash: requireString(output.before_hash, "before_hash"),
    file_hash: requireString(output.file_hash, "file_hash"),
    plan_hash: requireString(output.plan_hash, "plan_hash"),
    applied: requireBoolean(output.applied, "applied"),
    changed: requireBoolean(output.changed, "changed"),
    edit_count: requireNumber(output.edit_count, "edit_count"),
    before_content: optionalString(output.before_content, "before_content"),
    content: optionalString(output.content, "content")
  };
}
function parseRenameConflicts(value, field) {
  if (value === undefined)
    return [];
  if (!Array.isArray(value))
    throw new Error(`invalid readseek ${field}`);
  return value.map((item) => {
    if (!item || typeof item !== "object")
      throw new Error(`invalid readseek ${field} entry`);
    const c = item;
    return {
      line: requireNumber(c.line, `${field}.line`),
      column: requireNumber(c.column, `${field}.column`),
      reason: requireString(c.reason, `${field}.reason`)
    };
  });
}
function parseRenameEdits(value, field) {
  if (value === undefined)
    return [];
  if (!Array.isArray(value))
    throw new Error(`invalid readseek ${field} entry`);
  return value.map((item) => {
    if (!item || typeof item !== "object")
      throw new Error(`invalid readseek ${field} entry`);
    const e = item;
    return {
      line: requireNumber(e.line, `${field}.line`),
      start_column: requireNumber(e.start_column, `${field}.start_column`),
      end_column: requireNumber(e.end_column, `${field}.end_column`),
      start_byte: requireNumber(e.start_byte, `${field}.start_byte`),
      end_byte: requireNumber(e.end_byte, `${field}.end_byte`),
      occurrence: requireString(e.occurrence, `${field}.occurrence`),
      line_hash: requireString(e.line_hash, `${field}.line_hash`),
      text: requireString(e.text, `${field}.text`)
    };
  });
}
function parseRenameOutput(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek rename output");
  const output = value;
  const others = output.others;
  if (others !== undefined && !Array.isArray(others))
    throw new Error("invalid readseek others");
  return {
    file: requireString(output.file, "file"),
    language: requireString(output.language, "language"),
    engine: optionalString(output.engine, "engine"),
    file_hash: requireString(output.file_hash, "file_hash"),
    old_name: requireString(output.old_name, "old_name"),
    new_name: requireString(output.new_name, "new_name"),
    applied: requireBoolean(output.applied, "applied"),
    conflicts: parseRenameConflicts(output.conflicts, "conflicts"),
    edits: parseRenameEdits(output.edits, "edits"),
    others: others?.map((entry) => {
      if (!entry || typeof entry !== "object")
        throw new Error("invalid readseek other");
      const o = entry;
      return {
        file: requireString(o.file, "other.file"),
        language: requireString(o.language, "other.language"),
        engine: optionalString(o.engine, "other.engine"),
        file_hash: requireString(o.file_hash, "other.file_hash"),
        conflicts: parseRenameConflicts(o.conflicts, "other.conflicts"),
        edits: parseRenameEdits(o.edits, "other.edits")
      };
    }) ?? []
  };
}
function parseDefCompact(value) {
  if (!value || typeof value !== "object")
    throw new Error("invalid readseek def output");
  const output = value;
  const locations = output.locations;
  if (!Array.isArray(locations))
    throw new Error("invalid readseek def locations");
  return locations.map((loc) => {
    if (!loc || typeof loc !== "object")
      throw new Error("invalid readseek def location");
    const item = loc;
    return {
      file: requireString(item.file, "location.file"),
      line: requireNumber(item.line, "location.line"),
      column: requireNumber(item.column, "location.column"),
      line_hash: requireString(item.line_hash, "location.line_hash"),
      text: requireString(item.text, "location.text"),
      kind: optionalString(item.kind, "location.kind"),
      name: optionalString(item.name, "location.name"),
      qualified_name: optionalString(item.qualified_name, "location.qualified_name")
    };
  });
}
function createReadSeekClient(runner) {
  function digestArgs(target, options) {
    return buildDigestArgs({
      path: target,
      select: options.select ?? "content",
      at: options.at,
      end: options.end,
      limit: options.limit,
      depth: options.depth,
      language: options.language,
      visionMode: options.visionMode,
      visionLevel: options.visionLevel,
      stdinName: options.stdin !== undefined && target === "-" ? options.stdinName ?? target : undefined
    });
  }
  async function runDigestRaw(target, options = {}) {
    const args = digestArgs(target, options);
    const runOptions = {
      signal: options.signal,
      stdin: options.stdin,
      timeoutMs: options.timeoutMs,
      vision: options.vision
    };
    return runner.json(args, runOptions);
  }
  async function digest(target, options = {}) {
    return parseDigestEnvelope(await runDigestRaw(target, options));
  }
  function requireDigestContent(envelope, field) {
    if (envelope.content === undefined)
      throw new Error(`invalid readseek ${field}: missing content`);
    return envelope.content;
  }
  async function digestContent(filePath, options = {}) {
    const envelope = await digest(filePath, {
      select: "content",
      at: options.startLine !== undefined ? buildLineLocation(options.startLine) : undefined,
      end: options.endLine,
      visionMode: options.visionMode,
      signal: options.signal,
      vision: options.vision
    });
    if (envelope.metadata.kind === "pdf") {
      return { metadata: envelope.metadata, cache: envelope.cache };
    }
    const content = requireDigestContent(envelope, "content");
    if (envelope.metadata.kind === "image") {
      return { metadata: envelope.metadata, image: parseImageContent(content) };
    }
    return { metadata: envelope.metadata, text: parseTextContent(content) };
  }
  return {
    async view(filePath, options = {}) {
      const args = buildViewArgs({
        path: filePath,
        node: options.node,
        page: options.page,
        kind: options.kind,
        depth: options.depth,
        outline: options.outline,
        visionMode: options.visionMode,
        visionLevel: options.visionLevel
      });
      return runner.text(args, {
        signal: options.signal,
        vision: options.visionMode !== undefined
      });
    },
    digestRaw(target, options = {}) {
      return runDigestRaw(target, options);
    },
    digest,
    digestContent,
    async image(filePath, modes, options = {}) {
      const requestedModes = modes.length > 1 ? ["all"] : modes;
      const results = await Promise.allSettled(requestedModes.map(async (mode) => {
        const digested = await digestContent(filePath, {
          visionMode: mode,
          signal: options.signal,
          vision: true
        });
        if (!digested.image)
          throw new Error(`readseek returned no image analysis for ${filePath}`);
        return digested.image;
      }));
      let merged;
      for (const result of results) {
        if (result.status !== "fulfilled")
          continue;
        const detection = result.value;
        merged = merged === undefined ? detection : {
          ...merged,
          ocr: detection.ocr ?? merged.ocr,
          caption: detection.caption ?? merged.caption,
          objects: detection.objects ?? merged.objects
        };
      }
      if (merged !== undefined)
        return merged;
      const failure = results.find((result) => result.status === "rejected");
      if (failure?.status === "rejected")
        throw failure.reason;
      throw new Error(`readseek returned no image analysis for ${filePath}`);
    },
    async preparedImage(filePath, options = {}) {
      const digested = await digestContent(filePath, {
        visionMode: "none",
        signal: options.signal
      });
      const output = digested.image;
      if (!output || output.encoding !== "base64" || output.data === undefined || output.mime === undefined) {
        throw new Error(`readseek returned no prepared image for ${filePath}`);
      }
      return { mime: output.mime, encoding: output.encoding, data: output.data };
    },
    async search(target, pattern, options = {}) {
      const args = buildSearchArgs({
        path: target,
        pattern,
        language: options.language,
        limit: options.limit,
        cached: options.cached,
        others: options.others,
        ignored: options.ignored
      });
      return parseSearchOutput(await runner.json(args, { signal: options.signal }));
    },
    async refs(target, options = {}) {
      const args = buildRefsArgs({
        path: target,
        name: options.name,
        scope: options.scope,
        line: options.line,
        column: options.column,
        language: options.language,
        cached: options.cached,
        others: options.others,
        ignored: options.ignored
      });
      return parseRefsOutput(await runner.json(args, { signal: options.signal }));
    },
    async def(target, options) {
      const args = buildDefArgs({
        path: target,
        name: options.name,
        format: "plain",
        language: options.language,
        cached: options.cached,
        others: options.others,
        ignored: options.ignored
      });
      return parseDefCompact(await runner.json(args, { signal: options.signal }));
    },
    async check(filePath, content, options = {}) {
      const envelope = await digest("-", {
        select: "diagnostics",
        stdin: content,
        stdinName: filePath,
        signal: options.signal
      });
      if (!envelope.diagnostics)
        throw new Error("invalid readseek diagnostics: missing diagnostics facet");
      return envelope.diagnostics;
    },
    async identify(filePath, content, options = {}) {
      const envelope = await digest("-", {
        select: "identity",
        stdin: content,
        stdinName: filePath,
        at: options.line !== undefined ? buildLineLocation(options.line, options.column) : undefined,
        language: options.language,
        signal: options.signal
      });
      if (!envelope.identity)
        throw new Error("invalid readseek identity: missing identity facet");
      return envelope.identity;
    },
    async detect(filePath, options = {}) {
      const envelope = await digest(filePath, { select: "metadata", signal: options.signal });
      return envelope.metadata;
    },
    async edit(filePath, edits, options = {}) {
      const args = buildEditArgs({
        path: filePath,
        apply: options.apply,
        planHash: options.planHash,
        language: options.language,
        requestFromStdin: true
      });
      return parseEditOutput(await runner.json(args, {
        signal: options.signal,
        stdin: JSON.stringify({ edits }),
        timeoutMs: options.timeoutMs,
        cancelable: options.cancelable
      }));
    },
    async rename(filePath, options) {
      const args = buildRenameArgs({
        path: filePath,
        to: options.to,
        line: options.line,
        column: options.column,
        workspace: options.workspace,
        apply: options.apply,
        language: options.language,
        cached: options.cached,
        others: options.others,
        ignored: options.ignored
      });
      return parseRenameOutput(await runner.json(args, { signal: options.signal }));
    }
  };
}
// src/tool-prompt-metadata.ts
var REPLACEABLE_BY_TOOL = new Map(REPLACEABLE_TOOLS.map((entry) => [entry.tool, entry]));
function toolNameFromPrompt(fileName) {
  const name = fileName.replace(/\.md$/, "");
  if (!TOOL_NAMES.includes(name))
    throw new Error(`unknown ReadSeek tool prompt: ${fileName}`);
  return name;
}
function promptFileName(promptUrl) {
  return promptUrl.pathname.split("/").pop() ?? "";
}
function rewriteRegisteredToolNames(value, toolAliases) {
  if (!toolAliases)
    return value;
  return Object.entries(toolAliases).reduce((rewritten, [canonicalName, registeredName]) => rewritten.replaceAll(canonicalName, registeredName), value);
}
function descriptionAliases(toolName, registeredName, toolAliases) {
  return Object.fromEntries(TOOL_NAMES.map((name) => {
    const readSeekName = `readSeek_${name}`;
    const alias = name === toolName && registeredName ? registeredName : toolAliases?.[readSeekName] ?? readSeekName;
    return [name, alias];
  }));
}
function defineToolPromptMetadata(options) {
  const fileName = promptFileName(options.promptUrl);
  const toolName = toolNameFromPrompt(fileName);
  const replaceable = REPLACEABLE_BY_TOOL.get(toolName);
  const defaultReadSeekName = `readSeek_${toolName}`;
  const registeredName = options.registeredName ?? (replaceable ? defaultReadSeekName : undefined);
  const preferenceGuideline = replaceable && registeredName ? registeredName === defaultReadSeekName ? `Prefer ${registeredName} over ${replaceable.builtIn} when both are available; ${replaceable.benefit}` : `Use ${registeredName}; ${replaceable.benefit}` : undefined;
  const aliases = descriptionAliases(toolName, registeredName, options.toolAliases);
  return {
    description: renderToolDescription(toolName, aliases),
    promptSnippet: rewriteRegisteredToolNames(options.promptSnippet, options.toolAliases),
    promptGuidelines: [
      ...preferenceGuideline ? [preferenceGuideline] : [],
      ...renderCompactGuidelines(toolName, aliases)
    ]
  };
}

// src/edit-diff.ts
import * as Diff from "diff";

// src/hashline.ts
import xxhashWasm from "xxhash-wasm";
var ANCHOR_MASK = 16777215;
var HASHLINE_STATE_KEY = Symbol.for("pi-readseek.hashlineState.v1");
function getHashlineState() {
  const globalObject = globalThis;
  const state = globalObject[HASHLINE_STATE_KEY] ?? {
    h32Fn: null,
    initPromise: null
  };
  globalObject[HASHLINE_STATE_KEY] = state;
  return state;
}
async function ensureHashInit() {
  const state = getHashlineState();
  if (state.h32Fn)
    return;
  if (!state.initPromise) {
    state.initPromise = xxhashWasm().then((hasher) => {
      state.h32Fn = hasher.h32;
    }).catch((error) => {
      state.initPromise = null;
      throw error;
    });
  }
  await state.initPromise;
}
function xxh32(input) {
  const state = getHashlineState();
  if (!state.h32Fn)
    throw new Error("Hash not initialized — call ensureHashInit() first");
  return state.h32Fn(input, 0) >>> 0;
}
function canonicalizeLine(line) {
  return line.match(/[^\t\r\n ]+/g)?.join(" ") ?? "";
}
function computeLineHash(line) {
  return (xxh32(canonicalizeLine(line)) & ANCHOR_MASK).toString(16).padStart(HASH_LEN, "0");
}
var DISPLAY_CONTROL_CHAR_RE = /[\x00-\x08\x0b\x0c\x0e-\x1f]/g;
function escapeControlCharsForDisplay(text) {
  return text.replace(DISPLAY_CONTROL_CHAR_RE, (ch) => {
    return `\\u${ch.charCodeAt(0).toString(16).padStart(4, "0")}`;
  });
}
function formatHashlineDisplay(lineNumber, content) {
  return `${lineNumber}:${computeLineHash(content)}|${escapeControlCharsForDisplay(content)}`;
}

// src/edit-diff.ts
function normalizeToLF(text) {
  return text.replace(/\r\n/g, `
`).replace(/\r/g, `
`);
}
function stripBom(content) {
  return content.startsWith("\uFEFF") ? { bom: "\uFEFF", text: content.slice(1) } : { bom: "", text: content };
}
function hasBareCarriageReturn(content) {
  return content.replace(/\r\n/g, "").includes("\r");
}
function generateDiffString(oldContent, newContent, contextLines = 4) {
  const parts = Diff.diffLines(oldContent, newContent);
  const output = [];
  const maxLineNum = Math.max(oldContent.split(`
`).length, newContent.split(`
`).length);
  const lineNumWidth = String(maxLineNum).length;
  let oldLineNum = 1;
  let newLineNum = 1;
  let lastWasChange = false;
  let firstChangedLine;
  for (let i = 0;i < parts.length; i++) {
    const part = parts[i];
    const raw = part.value.split(`
`);
    if (raw[raw.length - 1] === "")
      raw.pop();
    if (part.added || part.removed) {
      if (firstChangedLine === undefined)
        firstChangedLine = newLineNum;
      for (const line of raw) {
        if (part.added) {
          output.push(`+${String(newLineNum).padStart(lineNumWidth, " ")} ${line}`);
          newLineNum++;
        } else {
          output.push(`-${String(oldLineNum).padStart(lineNumWidth, " ")} ${line}`);
          oldLineNum++;
        }
      }
      lastWasChange = true;
      continue;
    }
    const nextPartIsChange = i < parts.length - 1 && (parts[i + 1].added || parts[i + 1].removed);
    if (lastWasChange || nextPartIsChange) {
      let linesToShow = raw;
      let skipStart = 0;
      let skipEnd = 0;
      if (!lastWasChange) {
        skipStart = Math.max(0, raw.length - contextLines);
        linesToShow = raw.slice(skipStart);
      }
      if (!nextPartIsChange && linesToShow.length > contextLines) {
        skipEnd = linesToShow.length - contextLines;
        linesToShow = linesToShow.slice(0, contextLines);
      }
      if (skipStart > 0) {
        output.push(` ${"".padStart(lineNumWidth, " ")} ...`);
        oldLineNum += skipStart;
        newLineNum += skipStart;
      }
      for (const line of linesToShow) {
        output.push(` ${String(oldLineNum).padStart(lineNumWidth, " ")} ${line}`);
        oldLineNum++;
        newLineNum++;
      }
      if (skipEnd > 0) {
        output.push(` ${"".padStart(lineNumWidth, " ")} ...`);
        oldLineNum += skipEnd;
        newLineNum += skipEnd;
      }
    } else {
      oldLineNum += raw.length;
      newLineNum += raw.length;
    }
    lastWasChange = false;
  }
  return { diff: output.join(`
`), firstChangedLine };
}
function generateCompactOrFullDiff(oldContent, newContent, contextLines = 4) {
  if (oldContent === newContent)
    return { diff: "", firstChangedLine: undefined };
  const oldLines = oldContent.split(`
`);
  const newLines = newContent.split(`
`);
  if (oldLines.length === newLines.length) {
    let changedIndex = -1;
    let changeCount = 0;
    for (let i = 0;i < oldLines.length; i++) {
      if (oldLines[i] !== newLines[i]) {
        changedIndex = i;
        changeCount++;
        if (changeCount > 1)
          break;
      }
    }
    if (changeCount === 1 && changedIndex >= 0) {
      const lineNum = changedIndex + 1;
      const oldLine = oldLines[changedIndex] ?? "";
      const newLine = newLines[changedIndex] ?? "";
      const oldHash = computeLineHash(oldLine);
      const newHash = computeLineHash(newLine);
      return {
        diff: `${lineNum}:${oldHash}|${oldLine} → ${lineNum}:${newHash}|${newLine}`,
        firstChangedLine: lineNum
      };
    }
  }
  if (oldLines.length === newLines.length + 1) {
    let deletedIndex = -1;
    let j = 0;
    let failed = false;
    for (let i = 0;i < oldLines.length; i++) {
      if (j < newLines.length && oldLines[i] === newLines[j]) {
        j++;
        continue;
      }
      if (deletedIndex === -1) {
        deletedIndex = i;
        continue;
      }
      failed = true;
      break;
    }
    if (!failed && deletedIndex !== -1 && j === newLines.length) {
      const lineNum = deletedIndex + 1;
      const oldLine = oldLines[deletedIndex] ?? "";
      const oldHash = computeLineHash(oldLine);
      return {
        diff: `${lineNum}:${oldHash}|${oldLine} → [deleted]`,
        firstChangedLine: lineNum
      };
    }
  }
  return generateDiffString(oldContent, newContent, contextLines);
}

// src/path-utils.ts
import {
  expandUserPath as expandUserPath2,
  resolveToCwd as resolveToCwd2
} from "@jarkkojs/readseek-api";

// src/runtime.ts
function throwIfAborted(signal) {
  if (signal?.aborted)
    throw new Error("Operation aborted");
}

// src/fs-error.ts
var SYSLOG_PATH_SUFFIX = /,\s+[a-z]+(\s+'.*')?$/;
function strerror(err) {
  const raw = String(err?.message ?? String(err));
  return raw.replace(SYSLOG_PATH_SUFFIX, "");
}
function formatFsError(err, domain) {
  const errno = typeof err.code === "string" ? err.code : "EIO";
  return {
    code: errno,
    message: `${domain}: ${errno}: ${strerror(err)}`
  };
}

// src/edit-render-helpers.ts
var VARIANT_KEYS = ["set_line", "replace_lines", "insert_after", "replace"];
function countEditTypes(edits) {
  const counts = {
    set_line: 0,
    replace_lines: 0,
    insert_after: 0,
    replace: 0,
    total: 0
  };
  if (!edits)
    return counts;
  for (const edit of edits) {
    counts.total++;
    if (edit && typeof edit === "object") {
      for (const key of VARIANT_KEYS) {
        if (key in edit) {
          counts[key]++;
          break;
        }
      }
    }
  }
  return counts;
}
function parseDiffStats(diff) {
  if (!diff)
    return { added: 0, removed: 0 };
  let added = 0;
  let removed = 0;
  for (const line of diff.split(`
`)) {
    if (line.startsWith("+++") || line.startsWith("---"))
      continue;
    if (line.startsWith("+"))
      added++;
    else if (line.startsWith("-"))
      removed++;
  }
  return { added, removed };
}
function formatEditCallText(args, argsComplete) {
  const rawPath = typeof args?.path === "string" ? args.path : null;
  if (!argsComplete) {
    return { path: rawPath, suffix: undefined };
  }
  const edits = args?.edits;
  if (!Array.isArray(edits) || edits.length === 0) {
    return { path: rawPath, suffix: undefined };
  }
  const counts = countEditTypes(edits);
  const parts = [];
  for (const key of VARIANT_KEYS) {
    if (counts[key] > 0) {
      parts.push(`${counts[key]} ${key}`);
    }
  }
  const word = counts.total === 1 ? "edit" : "edits";
  const suffix = `${counts.total} ${word} (${parts.join(", ")})`;
  return { path: rawPath, suffix };
}
function formatEditResultText(input) {
  const { isError, diff, warnings, noopEdits, errorText } = input;
  const isNoOp = isError && (Array.isArray(noopEdits) && noopEdits.length > 0 || errorText.includes("No changes made"));
  const stats = parseDiffStats(diff);
  const hasDiffStats = stats.added > 0 || stats.removed > 0;
  const diffStats = hasDiffStats ? `+${stats.added} / -${stats.removed}` : undefined;
  let warningsBadge;
  if (warnings.length === 1) {
    warningsBadge = "⚠ 1 warning";
  } else if (warnings.length > 1) {
    warningsBadge = `⚠ ${warnings.length} warnings`;
  }
  const showErrorText = isError ? errorText : undefined;
  let semanticBadge;
  if (!isError && !isNoOp && input.semanticClassification) {
    switch (input.semanticClassification) {
      case "whitespace-only":
        semanticBadge = "ws-only";
        break;
      case "semantic":
        semanticBadge = "✓ semantic";
        break;
      case "mixed":
        semanticBadge = "mixed";
        break;
    }
  }
  return {
    diffStats,
    noOp: isNoOp,
    warningsBadge,
    errorText: showErrorText,
    semanticBadge
  };
}

// src/readseek-value.ts
function buildReadSeekLineWithHash(line, hash, raw) {
  return {
    line,
    hash,
    anchor: `${line}:${hash}`,
    raw,
    display: escapeControlCharsForDisplay(raw)
  };
}
function buildReadSeekLine(line, raw) {
  return buildReadSeekLineWithHash(line, computeLineHash(raw), raw);
}
function formatAnchoredFileBlocks(files, lineSuffix) {
  const blocks = [];
  for (const file of files) {
    blocks.push(`--- ${file.displayPath} ---`);
    for (const line of file.lines) {
      blocks.push(`>>${line.anchor}|${line.display}${lineSuffix?.(line) ?? ""}`);
    }
  }
  return blocks.join(`
`);
}
function buildReadSeekWarning(code, message, metadata = {}) {
  return { code, message, ...metadata };
}
function buildReadSeekError(code, message, hint, details) {
  return {
    code,
    message,
    ...hint !== undefined ? { hint } : {},
    ...details !== undefined ? { details } : {}
  };
}
function buildToolErrorResult(tool, code, message, opts = {}) {
  return {
    content: [{ type: "text", text: message }],
    isError: true,
    details: {
      readSeekValue: {
        tool,
        ...opts.extra ?? {},
        ok: false,
        ...opts.path !== undefined ? { path: opts.path } : {},
        error: buildReadSeekError(code, message, opts.hint, opts.details)
      }
    }
  };
}
function buildReadSeekEditResult(input) {
  return {
    tool: "edit",
    ok: input.ok ?? true,
    path: input.path,
    summary: input.summary,
    diff: input.diff,
    ...input.diffData ? { diffData: input.diffData } : {},
    firstChangedLine: input.firstChangedLine,
    warnings: [...input.warnings],
    noopEdits: [...input.noopEdits],
    ...input.semanticSummary ? { semanticSummary: input.semanticSummary } : {}
  };
}

// src/edit-output.ts
var EDIT_OPERATION_NAMES = ["set_line", "replace_lines", "insert_after", "replace"];
function hasNewText(value) {
  return typeof value === "object" && value !== null && typeof value.new_text === "string";
}
function getVisibleDiffStats(diff) {
  const stats = parseDiffStats(diff);
  if (stats.added > 0 || stats.removed > 0)
    return stats;
  if (!diff.includes("→"))
    return stats;
  if (diff.includes("→ [deleted]"))
    return { added: 0, removed: 1 };
  return { added: 1, removed: 1 };
}
function buildVisibleSummary(displayPath, diff, edits) {
  let stats = getVisibleDiffStats(diff);
  const counts = countEditTypes(edits);
  const editCount = counts.total || 1;
  if (counts.total > 0 && counts.insert_after === counts.total && stats.removed > 0 && stats.added === stats.removed + counts.insert_after) {
    stats = { added: counts.insert_after, removed: 0 };
  }
  const changeWord = editCount === 1 ? "change" : "changes";
  const changedLineCount = Math.max(stats.added, stats.removed);
  const lineWord = changedLineCount === 1 ? "line" : "lines";
  return `Edited ${displayPath} (${editCount} ${changeWord}, +${stats.added} -${stats.removed} ${lineWord})`;
}
function extractNewTextValues(edits) {
  const values = [];
  for (const edit of edits ?? []) {
    if (!edit || typeof edit !== "object")
      continue;
    const operations = edit;
    for (const operationName of EDIT_OPERATION_NAMES) {
      const operation = operations[operationName];
      if (hasNewText(operation))
        values.push(operation.new_text);
    }
  }
  return values;
}
function formatWhitespaceOnlyWarning(semanticSummary, edits) {
  if (semanticSummary?.classification !== "whitespace-only")
    return;
  if (!extractNewTextValues(edits).some((text) => /\S/.test(text)))
    return;
  return "⚠ Edit classified as whitespace-only — if you intended a behavior change, re-read to verify.";
}
function formatReplaceHint(edits, noopEdits) {
  if ((noopEdits ?? []).length > 0)
    return;
  const counts = countEditTypes(edits);
  if (counts.replace === 0)
    return;
  if (counts.replace !== counts.total)
    return;
  return "[info: this edit used replace (unverified). For safer future edits, prefer set_line/replace_lines with an anchor from readSeek_digest/readSeek_grep/readSeek_search.]";
}
function buildEditOutput(input) {
  const summary = `Updated ${input.displayPath}`;
  const visibleSummary = buildVisibleSummary(input.displayPath, input.diff, input.edits);
  const semanticWarning = formatWhitespaceOnlyWarning(input.semanticSummary, input.edits);
  const warningText = input.warnings.length ? `

Warnings:
${input.warnings.join(`
`)}` : "";
  const replaceHint = formatReplaceHint(input.edits, input.noopEdits);
  let text = visibleSummary;
  if (semanticWarning)
    text += `
${semanticWarning}`;
  text += warningText;
  if (replaceHint)
    text += `
${replaceHint}`;
  return {
    text,
    patch: input.patch ?? "",
    readSeekValue: buildReadSeekEditResult({
      path: input.path,
      summary,
      diff: input.diff,
      ...input.diffData ? { diffData: input.diffData } : {},
      firstChangedLine: input.firstChangedLine,
      warnings: input.warnings,
      noopEdits: input.noopEdits,
      ...input.semanticSummary ? { semanticSummary: input.semanticSummary } : {}
    })
  };
}

// src/edit-classify.ts
import * as Diff2 from "diff";
function classifyEdit(oldContent, newContent) {
  if (oldContent === newContent) {
    return { classification: "no-op" };
  }
  const oldLines = oldContent.split(`
`);
  const newLines = newContent.split(`
`);
  if (oldLines.length === newLines.length) {
    let hasWhitespaceChange2 = false;
    let hasSemanticChange2 = false;
    for (let i = 0;i < oldLines.length; i++) {
      if (oldLines[i] === newLines[i])
        continue;
      if (oldLines[i].trim() === newLines[i].trim()) {
        hasWhitespaceChange2 = true;
      } else {
        hasSemanticChange2 = true;
      }
    }
    if (hasSemanticChange2 && hasWhitespaceChange2)
      return { classification: "mixed" };
    if (hasWhitespaceChange2)
      return { classification: "whitespace-only" };
    return { classification: "semantic" };
  }
  const parts = Diff2.diffLines(oldContent, newContent);
  let hasWhitespaceChange = false;
  let hasSemanticChange = false;
  for (const part of parts) {
    if (!part.added && !part.removed)
      continue;
    const lines = part.value.split(`
`);
    if (lines[lines.length - 1] === "")
      lines.pop();
    for (const line of lines) {
      if (line.trim() === "") {
        hasWhitespaceChange = true;
      } else {
        hasSemanticChange = true;
      }
    }
  }
  if (hasSemanticChange && hasWhitespaceChange)
    return { classification: "mixed" };
  if (hasWhitespaceChange)
    return { classification: "whitespace-only" };
  return { classification: "semantic" };
}

// src/readseek-client.ts
import { existsSync as existsSync2, statSync as statSync3 } from "node:fs";
import { createRequire as createRequire2 } from "node:module";
import { homedir as homedir2 } from "node:os";
import path2 from "node:path";

// src/readseek-settings.ts
import { readFileSync, statSync as statSync2 } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
var READSEEK_TOOL_REPLACEMENTS = {
  read: "readSeek_digest",
  edit: "readSeek_edit",
  grep: "readSeek_grep",
  write: "readSeek_write"
};
var READSEEK_KEYS = ["overrideTools", "imageMode", "syntaxValidation", "timeoutMs", "grep", "display"];
var READSEEK_GREP_KEYS = ["maxLines", "maxBytes"];
var READSEEK_DISPLAY_KEYS = ["grep", "edit", "write"];
var DEFAULT_DISPLAY_MODES = {
  grep: "compact",
  edit: "expanded",
  write: "expanded"
};
function globalSettingsPath() {
  return join(homedir(), ".pi/agent/settings.json");
}
function projectSettingsPath() {
  return join(process.cwd(), ".pi/settings.json");
}
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function invalid(source, path2) {
  return { source, path: path2, message: `Invalid readseek setting at ${path2}` };
}
function warnUnknownKeys(raw, known, prefix, source, warnings) {
  for (const key of Object.keys(raw)) {
    if (known.includes(key))
      continue;
    const path2 = `${prefix}.${key}`;
    warnings.push({ source, path: path2, message: `Unknown readseek setting at ${path2}` });
  }
}
function readPositive(raw, key, path2, source, warnings) {
  if (!(key in raw))
    return;
  const val = raw[key];
  if (typeof val === "number" && Number.isSafeInteger(val) && val > 0)
    return val;
  warnings.push(invalid(source, path2));
  return;
}
function readEnum(raw, key, values, path2, source, warnings) {
  if (!(key in raw))
    return;
  const val = raw[key];
  if (typeof val === "string" && values.includes(val))
    return val;
  warnings.push(invalid(source, path2));
  return;
}
function readImageMode(raw, source, warnings) {
  if (!("imageMode" in raw))
    return;
  const val = raw.imageMode;
  if (val === "on" || val === "off" || val === "auto")
    return val;
  warnings.push(invalid(source, "readseek.imageMode"));
  return;
}
function readOverrideTools(raw, source, warnings) {
  if (!("overrideTools" in raw))
    return;
  const value = raw.overrideTools;
  if (!Array.isArray(value)) {
    warnings.push(invalid(source, "readseek.overrideTools"));
    return;
  }
  const tools = [];
  value.forEach((tool, index) => {
    if (typeof tool === "string" && Object.hasOwn(READSEEK_TOOL_REPLACEMENTS, tool)) {
      tools.push(tool);
    } else {
      warnings.push(invalid(source, `readseek.overrideTools[${index}]`));
    }
  });
  return tools;
}
function readDisplaySettings(raw, source, warnings) {
  if (!("display" in raw))
    return;
  if (!isRecord(raw.display)) {
    warnings.push(invalid(source, "readseek.display"));
    return;
  }
  warnUnknownKeys(raw.display, READSEEK_DISPLAY_KEYS, "readseek.display", source, warnings);
  const display = {};
  for (const tool of READSEEK_DISPLAY_KEYS) {
    const mode = readEnum(raw.display, tool, ["compact", "expanded"], `readseek.display.${tool}`, source, warnings);
    if (mode !== undefined)
      display[tool] = mode;
  }
  return Object.keys(display).length > 0 ? display : undefined;
}
function validateSettings(raw, source) {
  const settings = {};
  const warnings = [];
  if (!isRecord(raw)) {
    warnings.push({ source, message: "Invalid readseek settings: expected a JSON object" });
    return { settings, warnings };
  }
  if (!("readseek" in raw)) {
    const misplaced = READSEEK_KEYS.filter((key) => (key in raw));
    if (misplaced.length > 0) {
      warnings.push({
        source,
        path: misplaced[0],
        message: `Readseek setting at top level: move ${misplaced.join(", ")} under "readseek"`
      });
    }
    return { settings, warnings };
  }
  if (!isRecord(raw.readseek)) {
    warnings.push(invalid(source, "readseek"));
    return { settings, warnings };
  }
  const section = raw.readseek;
  warnUnknownKeys(section, READSEEK_KEYS, "readseek", source, warnings);
  const overrideTools = readOverrideTools(section, source, warnings);
  if (overrideTools !== undefined)
    settings.overrideTools = overrideTools;
  const imageMode = readImageMode(section, source, warnings);
  if (imageMode !== undefined)
    settings.imageMode = imageMode;
  const syntaxValidation = readEnum(section, "syntaxValidation", ["warn", "block", "off"], "readseek.syntaxValidation", source, warnings);
  if (syntaxValidation !== undefined)
    settings.syntaxValidation = syntaxValidation;
  const timeoutMs = readPositive(section, "timeoutMs", "readseek.timeoutMs", source, warnings);
  if (timeoutMs !== undefined)
    settings.timeoutMs = timeoutMs;
  if ("grep" in section) {
    if (isRecord(section.grep)) {
      warnUnknownKeys(section.grep, READSEEK_GREP_KEYS, "readseek.grep", source, warnings);
      const grep = {};
      const maxLines = readPositive(section.grep, "maxLines", "readseek.grep.maxLines", source, warnings);
      if (maxLines !== undefined)
        grep.maxLines = maxLines;
      const maxBytes = readPositive(section.grep, "maxBytes", "readseek.grep.maxBytes", source, warnings);
      if (maxBytes !== undefined)
        grep.maxBytes = maxBytes;
      if (Object.keys(grep).length > 0)
        settings.grep = grep;
    } else {
      warnings.push(invalid(source, "readseek.grep"));
    }
  }
  const display = readDisplaySettings(section, source, warnings);
  if (display !== undefined)
    settings.display = display;
  return { settings, warnings };
}
var settingsFileCache = new Map;
function statFileOrNull(path2) {
  try {
    return statSync2(path2);
  } catch {
    return null;
  }
}
function readSettingsFile(path2) {
  const stats = statFileOrNull(path2);
  if (!stats) {
    settingsFileCache.delete(path2);
    return { settings: {}, warnings: [] };
  }
  const cached = settingsFileCache.get(path2);
  if (cached && cached.mtimeMs === stats.mtimeMs && cached.size === stats.size)
    return cached.result;
  let result;
  try {
    const text = readFileSync(path2, "utf8");
    result = validateSettings(JSON.parse(text), path2);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    result = { settings: {}, warnings: [{ source: path2, message: `Invalid JSON: ${message}` }] };
  }
  settingsFileCache.set(path2, { mtimeMs: stats.mtimeMs, size: stats.size, result });
  return result;
}
function mergeSettings(base, override) {
  const settings = { ...base, ...override };
  const grep = { ...base.grep ?? {}, ...override.grep ?? {} };
  if (Object.keys(grep).length > 0)
    settings.grep = grep;
  const display = { ...base.display ?? {}, ...override.display ?? {} };
  if (Object.keys(display).length > 0)
    settings.display = display;
  return settings;
}
function resolveReadSeekJsonSettings() {
  const result = validateSettings({ readseek: { ...readseekSettings(), overrideTools: [] } }, "agentcfg");
  if (result.warnings.length) throw new Error("READSEEK_SETTINGS_INVALID");
  return result;
}

function resolveReadSeekImageMode() {
  return resolveReadSeekJsonSettings().settings.imageMode ?? "auto";
}
function resolveReadSeekSyntaxValidation() {
  return resolveReadSeekJsonSettings().settings.syntaxValidation;
}
function resolveReadSeekTimeoutMs() {
  return resolveReadSeekJsonSettings().settings.timeoutMs;
}
function resolveReadSeekToolDisplayMode(tool) {
  return resolveReadSeekJsonSettings().settings.display?.[tool] ?? DEFAULT_DISPLAY_MODES[tool];
}

// src/readseek-client.ts
var resolveFromHost = createRequire2(import.meta.url).resolve;
function readSeekBinaryPath() {
  const worker = readseekWorker();
  if (!worker || !readseekAvailability().available) throw new Error("READSEEK_WORKER_REQUIRED");
  return worker.native_binary;
}
function readSeekBinaryAvailability() { return readseekAvailability(); }

var defaultReadSeekDirInit;
function defaultReadSeekDir() {
  const home = homedir2();
  return home ? path2.join(home, ".pi", "readseek") : null;
}
function directoryExists(dir) {
  try {
    return statSync3(dir).isDirectory();
  } catch {
    return false;
  }
}
var DEFAULT_READSEEK_VISION_TIMEOUT_MS = 30 * 60000;
function readSeekTimeoutMs() {
  return resolveReadSeekTimeoutMs() ?? DEFAULT_READSEEK_TIMEOUT_MS;
}
async function spawnReadSeekRaw(args, options = {}) {
  return runReadSeekNodeText(readSeekBinaryPath(), args, {
    signal: options.signal,
    stdin: options.stdin,
    timeoutMs: options.timeoutMs ?? readSeekTimeoutMs(),
    cancelable: options.cancelable
  });
}
async function ensureDefaultReadSeekDir() {
  const dir = defaultReadSeekDir();
  if (!dir)
    return null;
  if (directoryExists(dir))
    return dir;
  defaultReadSeekDirInit ??= spawnReadSeekRaw(["--readseek-dir", dir, "init"]).then(() => directoryExists(dir) ? dir : null).catch(() => null).finally(() => {
    defaultReadSeekDirInit = undefined;
  });
  return defaultReadSeekDirInit;
}
function hasProjectReadSeekDir(cwd = process.cwd()) {
  let dir = path2.resolve(cwd);
  while (true) {
    if (existsSync2(path2.join(dir, ".readseek")))
      return true;
    const parent = path2.dirname(dir);
    if (parent === dir)
      return false;
    dir = parent;
  }
}
async function readSeekInvocationArgs(args) {
  const worker = readseekWorker();
  if (!worker?.cache_root) throw new Error("READSEEK_WORKER_REQUIRED");
  return ["--readseek-dir", worker.cache_root, ...args];
}

async function runReadSeekRaw(args, options = {}) {
  return spawnReadSeekRaw(await readSeekInvocationArgs(args), options);
}
async function runReadSeek(args, options = {}) {
  return runReadSeekNodeJson(readSeekBinaryPath(), await readSeekInvocationArgs(args), {
    signal: options.signal,
    stdin: options.stdin,
    timeoutMs: options.timeoutMs ?? readSeekTimeoutMs(),
    cancelable: options.cancelable
  });
}
var visionInvocationTail = Promise.resolve();
async function runReadSeekVisionRaw(args, options = {}) {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const predecessor = visionInvocationTail;
  visionInvocationTail = predecessor.then(() => gate);
  const signal = options.signal;
  try {
    if (signal) {
      signal.throwIfAborted();
      await new Promise((resolve, reject) => {
        const onAbort = () => {
          signal.removeEventListener("abort", onAbort);
          reject(signal.reason);
        };
        signal.addEventListener("abort", onAbort, { once: true });
        predecessor.then(() => {
          signal.removeEventListener("abort", onAbort);
          resolve();
        }, (error) => {
          signal.removeEventListener("abort", onAbort);
          reject(error);
        });
      });
    } else {
      await predecessor;
    }
    signal?.throwIfAborted();
    return await runReadSeekRaw(args, {
      ...options,
      timeoutMs: options.timeoutMs ?? resolveReadSeekTimeoutMs() ?? DEFAULT_READSEEK_VISION_TIMEOUT_MS
    });
  } finally {
    release();
  }
}
async function runReadSeekVision(args, options = {}) {
  return parseReadSeekJson(await runReadSeekVisionRaw(args, options));
}
var runner = {
  text: (args, options = {}) => options.vision ? runReadSeekVisionRaw(args, options) : runReadSeekRaw(args, options),
  json: (args, options = {}) => options.vision ? runReadSeekVision(args, options) : runReadSeek(args, options)
};
var client = createReadSeekClient(runner);
var readSeekView = client.view;
var readSeekDigestNative = client.digestRaw;
var readSeekDigest = client.digest;
var readSeekDigestContent = client.digestContent;
var readSeekImage = client.image;
var readSeekPreparedImage = client.preparedImage;
var readSeekSearch = client.search;
var readSeekRefs = client.refs;
var readSeekDef = client.def;
var readSeekCheck = client.check;
var readSeekIdentify = client.identify;
var readSeekDetect = client.detect;
var readSeekEdit = client.edit;
var readSeekRename = client.rename;
async function readSeekMap(filePath, options = {}) {
  const envelope = await client.digest(filePath, {
    select: "map",
    depth: DEFAULT_DIGEST_MAP_DEPTH,
    signal: options.signal
  });
  const map = envelope.map;
  if (!map || map.language === "unknown" && map.symbols.length === 0)
    return null;
  return map;
}

// src/edit-syntax-validate.ts
function dedupeSortLines(diagnostics) {
  const seen = new Set;
  const out = [];
  for (const diagnostic of diagnostics) {
    const key = diagnostic.start_line === diagnostic.end_line ? String(diagnostic.start_line) : `${diagnostic.start_line}-${diagnostic.end_line}`;
    if (!seen.has(key)) {
      seen.add(key);
      out.push({ key, start: diagnostic.start_line });
    }
  }
  out.sort((a, b) => a.start - b.start);
  return out.map((o) => o.key);
}
var EMPTY = { errorCount: 0, missingCount: 0, diagnostics: [] };
async function validateSyntaxRegression(input, options = {}) {
  let before;
  let after;
  try {
    before = input.before === undefined ? EMPTY : await readSeekCheck(input.filePath, input.before, { signal: options.signal });
    after = await readSeekCheck(input.filePath, input.after, { signal: options.signal });
  } catch {
    return null;
  }
  const newErrorCount = Math.max(0, after.errorCount - before.errorCount);
  const newMissingCount = Math.max(0, after.missingCount - before.missingCount);
  if (newErrorCount === 0 && newMissingCount === 0)
    return null;
  return {
    errorLines: dedupeSortLines(after.diagnostics),
    newErrorCount,
    newMissingCount
  };
}

// src/syntax-validate-mode.ts
var DEFAULT = "warn";
function resolveSyntaxValidateMode(opts) {
  return opts.syntaxValidate ?? resolveReadSeekSyntaxValidation() ?? DEFAULT;
}

// src/diff-data.ts
var MAX_INLINE_DIFF_LINE_LENGTH = 4096;
var MAX_INLINE_DIFF_TOKENS = 512;
var MAX_INLINE_DIFF_CELLS = 200000;
var MAX_INLINE_DIFF_PAIRS = 200;
var INLINE_SIMILARITY_THRESHOLD = 0.35;
var INLINE_TOKEN_PATTERN = /([A-Za-z_$][\w$]*|\d+|\s+|[^A-Za-z_$\w\s]+)/gu;
var LANGUAGE_BY_EXTENSION = new Map([
  [".ts", "typescript"],
  [".tsx", "typescript"],
  [".js", "javascript"],
  [".jsx", "javascript"],
  [".py", "python"],
  [".rs", "rust"],
  [".java", "java"]
]);
function inferLanguage(path3) {
  const extensionMatch = path3.match(/\.[^.\/\\]+$/);
  if (!extensionMatch)
    return;
  return LANGUAGE_BY_EXTENSION.get(extensionMatch[0].toLowerCase());
}
function parseFullDiffEntries(diff) {
  const entries = [];
  let nextOldLine = 1;
  let nextNewLine = 1;
  for (const line of diff ? diff.split(`
`) : []) {
    const removeMatch = line.match(/^-\s*(\d+) (.*)$/);
    if (removeMatch) {
      const oldLine = Number(removeMatch[1]);
      entries.push({ kind: "remove", oldLine, text: removeMatch[2] ?? "" });
      nextOldLine = oldLine + 1;
      continue;
    }
    const addMatch = line.match(/^\+\s*(\d+) (.*)$/);
    if (addMatch) {
      const newLine = Number(addMatch[1]);
      entries.push({ kind: "add", newLine, text: addMatch[2] ?? "" });
      nextNewLine = newLine + 1;
      continue;
    }
    const contextMatch = line.match(/^ \s*(\d+) (.*)$/);
    if (contextMatch) {
      const oldLine = Number(contextMatch[1]);
      const lineDelta = nextNewLine - nextOldLine;
      const newLine = oldLine + lineDelta;
      entries.push({ kind: "context", oldLine, newLine, text: contextMatch[2] ?? "" });
      nextOldLine = oldLine + 1;
      nextNewLine = newLine + 1;
      continue;
    }
    entries.push({ kind: "meta", text: line });
  }
  return entries;
}
function parseCompactDiffEntries(diff, oldContent, newContent) {
  const oldLines = oldContent.split(`
`);
  const newLines = newContent.split(`
`);
  const compactDelete = diff.match(/^(\d+):[0-9a-f]{6}\|(.*) → \[deleted\]$/);
  if (compactDelete) {
    const oldLine2 = Number(compactDelete[1]);
    const text = compactDelete[2] ?? "";
    if (oldLines[oldLine2 - 1] === text)
      return [{ kind: "remove", oldLine: oldLine2, text }];
  }
  const compactPrefix = diff.match(/^(\d+):[0-9a-f]{6}\|/);
  if (!compactPrefix)
    return;
  const oldLine = Number(compactPrefix[1]);
  const oldTextStart = compactPrefix[0].length;
  const separatorPattern = / → (\d+):[0-9a-f]{6}\|/g;
  let separator;
  while ((separator = separatorPattern.exec(diff)) !== null) {
    const newLine = Number(separator[1]);
    const oldText = diff.slice(oldTextStart, separator.index);
    const newText = diff.slice(separator.index + separator[0].length);
    if (oldLines[oldLine - 1] === oldText && newLines[newLine - 1] === newText) {
      return [
        { kind: "remove", oldLine, text: oldText },
        { kind: "add", newLine, text: newText }
      ];
    }
  }
  return;
}
function buildStats(entries) {
  return entries.reduce((stats, entry) => {
    if (entry.kind === "add")
      stats.added++;
    else if (entry.kind === "remove")
      stats.removed++;
    else if (entry.kind === "context")
      stats.context++;
    return stats;
  }, { added: 0, removed: 0, context: 0 });
}
function tokenizeInlineDiff(text) {
  return text.match(INLINE_TOKEN_PATTERN) ?? (text ? [text] : []);
}
function longestCommonSubsequence(a, b) {
  const rows = a.length + 1;
  const cols = b.length + 1;
  const table = Array.from({ length: rows }, () => Array(cols).fill(0));
  for (let i2 = a.length - 1;i2 >= 0; i2--) {
    for (let j2 = b.length - 1;j2 >= 0; j2--) {
      table[i2][j2] = a[i2] === b[j2] ? table[i2 + 1][j2 + 1] + 1 : Math.max(table[i2 + 1][j2], table[i2][j2 + 1]);
    }
  }
  const pairs = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      pairs.push([i, j]);
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      i++;
    } else {
      j++;
    }
  }
  return pairs;
}
function pushMergedSpan(spans, span) {
  if (!span.text)
    return;
  const previous = spans[spans.length - 1];
  if (previous?.kind === span.kind) {
    previous.text += span.text;
    return;
  }
  spans.push({ ...span });
}
function buildInlineSpans(removeText, addText) {
  if (removeText.length > MAX_INLINE_DIFF_LINE_LENGTH || addText.length > MAX_INLINE_DIFF_LINE_LENGTH)
    return;
  const removeTokens = tokenizeInlineDiff(removeText);
  const addTokens = tokenizeInlineDiff(addText);
  if (!removeTokens.length || !addTokens.length)
    return;
  if (removeTokens.length > MAX_INLINE_DIFF_TOKENS || addTokens.length > MAX_INLINE_DIFF_TOKENS)
    return;
  if ((removeTokens.length + 1) * (addTokens.length + 1) > MAX_INLINE_DIFF_CELLS)
    return;
  const pairs = longestCommonSubsequence(removeTokens, addTokens);
  const meaningfulRemoveTokenCount = removeTokens.filter((token) => token.trim().length > 0).length;
  const meaningfulAddTokenCount = addTokens.filter((token) => token.trim().length > 0).length;
  const meaningfulEqualTokenCount = pairs.filter(([removeIndex, addIndex]) => {
    const removeToken = removeTokens[removeIndex] ?? "";
    const addToken = addTokens[addIndex] ?? "";
    return removeToken === addToken && removeToken.trim().length > 0 && addToken.trim().length > 0;
  }).length;
  const similarity = meaningfulEqualTokenCount / Math.max(meaningfulRemoveTokenCount, meaningfulAddTokenCount);
  if (similarity < INLINE_SIMILARITY_THRESHOLD)
    return;
  const removeSpans = [];
  const addSpans = [];
  let removeCursor = 0;
  let addCursor = 0;
  for (const [removeIndex, addIndex] of pairs) {
    if (removeCursor < removeIndex) {
      pushMergedSpan(removeSpans, { kind: "remove", text: removeTokens.slice(removeCursor, removeIndex).join("") });
    }
    if (addCursor < addIndex) {
      pushMergedSpan(addSpans, { kind: "add", text: addTokens.slice(addCursor, addIndex).join("") });
    }
    pushMergedSpan(removeSpans, { kind: "equal", text: removeTokens[removeIndex] });
    pushMergedSpan(addSpans, { kind: "equal", text: addTokens[addIndex] });
    removeCursor = removeIndex + 1;
    addCursor = addIndex + 1;
  }
  if (removeCursor < removeTokens.length) {
    pushMergedSpan(removeSpans, { kind: "remove", text: removeTokens.slice(removeCursor).join("") });
  }
  if (addCursor < addTokens.length) {
    pushMergedSpan(addSpans, { kind: "add", text: addTokens.slice(addCursor).join("") });
  }
  if (!removeSpans.some((span) => span.kind === "remove") || !addSpans.some((span) => span.kind === "add"))
    return;
  return { removeSpans, addSpans };
}
function buildInlineDiffs(entries) {
  const inlineDiffs = [];
  let remainingPairs = MAX_INLINE_DIFF_PAIRS;
  for (let index = 0;index < entries.length; ) {
    if (entries[index]?.kind !== "remove") {
      index++;
      continue;
    }
    const removeStart = index;
    while (entries[index]?.kind === "remove")
      index++;
    const addStart = index;
    while (entries[index]?.kind === "add")
      index++;
    const removeCount = addStart - removeStart;
    const addCount = index - addStart;
    if (removeCount === 0 || addCount === 0 || removeCount !== addCount)
      continue;
    for (let offset = 0;offset < removeCount; offset++) {
      if (remainingPairs <= 0)
        break;
      remainingPairs--;
      const removeIndex = removeStart + offset;
      const addIndex = addStart + offset;
      const removeEntry = entries[removeIndex];
      const addEntry = entries[addIndex];
      if (removeEntry?.kind !== "remove" || addEntry?.kind !== "add")
        continue;
      const spans = buildInlineSpans(removeEntry.text, addEntry.text);
      if (!spans)
        continue;
      inlineDiffs.push({
        removeLineIndex: removeIndex,
        addLineIndex: addIndex,
        removeSpans: spans.removeSpans,
        addSpans: spans.addSpans
      });
    }
  }
  return inlineDiffs.length ? inlineDiffs : undefined;
}
function finalizeDiffData(path3, entries, blockRanges) {
  const language = inferLanguage(path3);
  const inlineDiffs = buildInlineDiffs(entries);
  return {
    version: 1,
    entries,
    stats: buildStats(entries),
    ...language ? { language } : {},
    ...blockRanges?.length ? { blockRanges: [...blockRanges] } : {},
    ...inlineDiffs ? { inlineDiffs } : {}
  };
}
function buildDiffData(input) {
  const entries = parseCompactDiffEntries(input.diff, input.oldContent, input.newContent) ?? parseFullDiffEntries(input.diff);
  return finalizeDiffData(input.path, entries, input.blockRanges);
}

// src/tui-render-utils.ts
import { relative } from "node:path";
import { pathToFileURL } from "node:url";
import { getCapabilities, hyperlink, Text, truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
var SUMMARY_PREFIX = "↳";
var EXPAND_HINT = " • Ctrl+O to expand";
function renderToolLabel(theme, label) {
  const boldFn = typeof theme.bold === "function" ? theme.bold.bind(theme) : (text) => text;
  return theme.fg("toolTitle", boldFn(label));
}
function linkToolPath(styledText, rawPath, cwd) {
  try {
    if (!getCapabilities().hyperlinks)
      return styledText;
    const absolutePath = resolveToCwd2(rawPath, cwd);
    return hyperlink(styledText, pathToFileURL(absolutePath).href);
  } catch {
    return styledText;
  }
}
function linkedPathLine(theme, rawPath, displayPath, cwd, suffix, width) {
  const pathWidth = width === undefined ? undefined : Math.max(1, width - 2 - visibleWidth(suffix));
  const visiblePath = pathWidth === undefined ? displayPath : truncateToWidth(displayPath, pathWidth);
  const linkedPath = linkToolPath(theme.fg("dim", visiblePath), rawPath, cwd);
  return `  ${linkedPath}${theme.fg("dim", suffix)}`;
}
function appendExpandHint(text, hidden) {
  return hidden ? `${text}${EXPAND_HINT}` : text;
}
function summaryLine(summary, options = {}) {
  const prefix = options.theme ? options.theme.fg(options.style ?? "dim", SUMMARY_PREFIX) : SUMMARY_PREFIX;
  return appendExpandHint(`${prefix} ${summary}`, !!options.hidden);
}
function isRendererExpanded(options, context, defaultExpanded = false) {
  return context?.expanded ?? options?.expanded ?? defaultExpanded;
}
function resolveRenderResultContext(options, rest, defaultExpanded = false) {
  const context = rest[0] ?? options ?? {};
  return {
    isPartial: context.isPartial ?? options?.isPartial ?? false,
    isError: context.isError ?? false,
    expanded: isRendererExpanded(options, context, defaultExpanded),
    width: context.width ?? options?.width,
    cwd: context.cwd ?? process.cwd(),
    context
  };
}
function normalizeWidth(width, fallback = 80) {
  return typeof width === "number" && Number.isFinite(width) && width > 0 ? Math.floor(width) : fallback;
}
function clampLineToWidth(line, width) {
  if (width === undefined || width === null)
    return line;
  const normalized = normalizeWidth(width);
  return visibleWidth(line) <= normalized ? line : truncateToWidth(line, normalized);
}
function clampLinesToWidth(lines, width) {
  if (width === undefined || width === null)
    return lines;
  return lines.map((line) => clampLineToWidth(line, width));
}
function wrapWithHangingIndent(prefix, content, width, options = {}) {
  const tint = options.tint ?? ((text) => text);
  if (width === undefined || width === null)
    return [tint(prefix + content)];
  const normalized = normalizeWidth(width);
  const combined = prefix + content;
  if (visibleWidth(combined) <= normalized)
    return [tint(combined)];
  const prefixWidth = visibleWidth(prefix);
  const contentWidth = Math.max(1, normalized - prefixWidth);
  const wrapped = wrapTextWithAnsi(content, contentWidth);
  if (wrapped.length === 0)
    return [tint(clampLineToWidth(prefix, normalized))];
  const indent = " ".repeat(prefixWidth);
  return wrapped.map((line, index) => tint(clampLineToWidth(index === 0 ? prefix + line : indent + line, normalized)));
}
var wrappedHashlinesCache = new WeakMap;
function renderPendingResult(pendingLabel, width, theme) {
  return new Text(clampLinesToWidth([summaryLine(pendingLabel, { theme, style: "muted" })], width).join(`
`), 0, 0);
}
function renderErrorResult(textContent, options) {
  const firstLine = textContent.split(`
`)[0] || (options.fallback ?? "Error");
  const body = options.expanded && textContent ? textContent : firstLine;
  return new Text(clampLinesToWidth(summaryLine(body, { theme: options.theme, style: "error" }).split(`
`), options.width).join(`
`), 0, 0);
}
function renderReadSeekSearchCall(args, theme, rest, opts) {
  const context = rest[0] ?? {};
  let text = `${renderToolLabel(theme, opts.label)} ${theme.fg("accent", opts.accent)}`;
  text += theme.fg("dim", ` in ${args.path ?? "."}`);
  const language = args.language ?? args.lang;
  if (language)
    text += theme.fg("dim", ` (${language})`);
  const flags = opts.flags.filter(Boolean);
  if (flags.length > 0)
    text += theme.fg("dim", ` [${flags.join(",")}]`);
  return new Text(clampLineToWidth(text, context.width), 0, 0);
}
function renderAnchoredFilesResult(result, options, theme, rest, labels) {
  const { isPartial, isError, expanded, cwd, width } = resolveRenderResultContext(options, rest);
  if (isPartial)
    return renderPendingResult(labels.pendingLabel, width, theme);
  const content = result.content?.[0];
  const textContent = content?.type === "text" ? content.text : "";
  if (isError || result.isError)
    return renderErrorResult(textContent, { expanded, width, theme });
  const readSeekValue = result.details?.readSeekValue;
  const files = readSeekValue?.files ?? [];
  if (files.length === 0)
    return new Text(summaryLine(labels.emptyLabel, { theme, style: "dim" }), 0, 0);
  const fileCount = files.length;
  const total = files.reduce((sum, f) => sum + f.lines.length, 0);
  const unitWord = total === 1 ? labels.unitSingular : labels.unitPlural;
  const fileWord = fileCount === 1 ? "file" : "files";
  let text = summaryLine(`${total} ${unitWord} in ${fileCount} ${fileWord}`, {
    hidden: !expanded,
    theme,
    style: "success"
  });
  if (expanded) {
    for (const file of files.slice(0, 20)) {
      const display = relative(cwd, file.path) || file.path;
      text += `
${linkedPathLine(theme, file.path, display, cwd, ` (${file.lines.length})`, width)}`;
    }
    if (files.length > 20)
      text += `
` + theme.fg("muted", `  … and ${files.length - 20} more files`);
  }
  return new Text(clampLinesToWidth(text.split(`
`), width).join(`
`), 0, 0);
}

// src/tui-diff-component.ts
import { Text as Text2, visibleWidth as visibleWidth3 } from "@earendil-works/pi-tui";

// src/tui-diff-renderer.ts
import { visibleWidth as visibleWidth2 } from "@earendil-works/pi-tui";
function isDiffEntry(value) {
  if (typeof value !== "object" || value === null)
    return false;
  const entry = value;
  if (typeof entry.text !== "string")
    return false;
  if (entry.kind === "meta")
    return true;
  if (entry.kind === "add")
    return Number.isInteger(entry.newLine) && Number(entry.newLine) > 0;
  if (entry.kind === "remove")
    return Number.isInteger(entry.oldLine) && Number(entry.oldLine) > 0;
  return entry.kind === "context" && Number.isInteger(entry.oldLine) && Number(entry.oldLine) > 0 && Number.isInteger(entry.newLine) && Number(entry.newLine) > 0;
}
function indexedDiffEntries(data) {
  if (!Array.isArray(data.entries))
    return [];
  const entries = [];
  for (const [index, entry] of data.entries.entries()) {
    if (isDiffEntry(entry))
      entries.push([index, entry]);
  }
  return entries;
}
function hasOldSide(entries) {
  return entries.some(([, entry]) => entry.kind === "remove" || entry.kind === "context");
}
function chooseMode(width, entries) {
  if (width < 24)
    return "summary";
  if (width < 50)
    return "compact";
  if (width >= 100 && hasOldSide(entries))
    return "split";
  return "unified";
}
function hunkCount(data, entries) {
  const blockRangeCount = Array.isArray(data.blockRanges) ? data.blockRanges.length : undefined;
  return Math.max(1, blockRangeCount ?? (entries.some(([, entry]) => entry.kind === "add" || entry.kind === "remove") ? 1 : 0));
}
function compactHeader(data) {
  return `↳ diff +${data.stats.added} -${data.stats.removed}`;
}
function header(data, mode, width, entries) {
  if (mode === "summary" && width <= 10)
    return `↳ diff +${data.stats.added}`;
  const full = `${compactHeader(data)} • ${hunkCount(data, entries)} hunk • 1 file • ${mode === "split" ? "split" : "unified"}`;
  return visibleWidth2(full) <= width ? full : clampLineToWidth(compactHeader(data), width);
}
function lineNo(entry) {
  return String(entry.kind === "add" ? entry.newLine : entry.kind === "remove" ? entry.oldLine : entry.kind === "context" ? entry.newLine : "");
}
function gutterMarker(entry) {
  return entry.kind === "add" ? "+" : entry.kind === "remove" ? "-" : " ";
}
function textOf(entry) {
  return "text" in entry ? entry.text : "";
}
function padRightVisual(line, width) {
  const visible = visibleWidth2(line);
  return visible >= width ? line : line + " ".repeat(width - visible);
}
function tint(theme, entry, text) {
  return entry.kind === "add" ? theme.fg("success", text) : entry.kind === "remove" ? theme.fg("error", text) : theme.fg("toolOutput", text);
}
function spans(theme, spans2, fallback) {
  return spans2?.map((s) => s.kind === "add" ? theme.fg("success", s.text) : s.kind === "remove" ? theme.fg("error", s.text) : s.text).join("") ?? fallback;
}
function inlineText(input, index, entry) {
  const pair = Array.isArray(input.diffData.inlineDiffs) ? input.diffData.inlineDiffs.find((d) => entry.kind === "remove" ? d.removeLineIndex === index : entry.kind === "add" ? d.addLineIndex === index : false) : undefined;
  if (!pair)
    return textOf(entry);
  return entry.kind === "remove" ? spans(input.theme, pair.removeSpans, textOf(entry)) : entry.kind === "add" ? spans(input.theme, pair.addSpans, textOf(entry)) : textOf(entry);
}
function unifiedRows(input, width, entries) {
  const rows = [];
  for (const [i, e] of entries) {
    if (e.kind === "meta")
      continue;
    const prefix = `▌${gutterMarker(e)} ${lineNo(e)} │ `;
    const tinted = wrapWithHangingIndent(prefix, inlineText(input, i, e), width, { tint: (text) => tint(input.theme, e, text) });
    rows.push(...tinted);
  }
  return rows;
}
function compactRows(input, width, entries) {
  const rows = [];
  for (const [i, e] of entries) {
    if (e.kind !== "add" && e.kind !== "remove")
      continue;
    const prefix = `▌${gutterMarker(e)} ${lineNo(e)} `;
    const tinted = wrapWithHangingIndent(prefix, inlineText(input, i, e), width, { tint: (text) => tint(input.theme, e, text) });
    rows.push(...tinted);
  }
  return rows;
}
function splitRows(input, width, entries) {
  const pane = Math.max(10, Math.floor((width - 3) / 2));
  const rows = [`${padRightVisual("old", pane)} │ new`];
  const blankPane = " ".repeat(pane);
  for (const [i, e] of entries) {
    if (e.kind === "remove") {
      const left = wrapWithHangingIndent(`▌- ${e.oldLine} │ `, inlineText(input, i, e), pane, { tint: (text) => tint(input.theme, e, text) });
      for (const line of left)
        rows.push(`${padRightVisual(line, pane)} │ ${blankPane}`);
    } else if (e.kind === "add") {
      const right = wrapWithHangingIndent(`▌+ ${e.newLine} │ `, inlineText(input, i, e), pane, { tint: (text) => tint(input.theme, e, text) });
      for (const line of right)
        rows.push(`${blankPane} │ ${line}`);
    } else if (e.kind === "context") {
      const left = wrapWithHangingIndent(`▌  ${e.oldLine} │ `, e.text, pane, { tint: (text) => tint(input.theme, e, text) });
      const right = wrapWithHangingIndent(`▌  ${e.newLine} │ `, e.text, pane, { tint: (text) => tint(input.theme, e, text) });
      const maxLen = Math.max(left.length, right.length);
      for (let k = 0;k < maxLen; k++) {
        const l = left[k] ?? blankPane;
        const r = right[k] ?? blankPane;
        rows.push(`${padRightVisual(l, pane)} │ ${r}`);
      }
    }
  }
  return rows;
}
function hiddenHint(hiddenLines, hiddenHunks, width) {
  const forms = [`… (${hiddenLines} more diff lines • ${hiddenHunks} more hunk${hiddenHunks === 1 ? "" : "s"} • Ctrl+O to expand)`, `… (${hiddenLines} more lines • ${hiddenHunks} hunks)`, `… (+${hiddenLines} • +${hiddenHunks}h)`, "…"];
  return forms.find((f) => visibleWidth2(f) <= width) ?? "…";
}
function renderTuiDiff(input) {
  const width = normalizeWidth(input.width);
  const entries = indexedDiffEntries(input.diffData);
  const rawEntryCount = Array.isArray(input.diffData.entries) ? input.diffData.entries.length : input.diffData.stats.added + input.diffData.stats.removed + input.diffData.stats.context;
  const truncated = !Array.isArray(input.diffData.entries) || entries.length !== rawEntryCount;
  const mode = chooseMode(width, entries);
  const lines = [header(input.diffData, mode, width, entries)];
  if (!input.expanded)
    return { mode, width, lines: clampLinesToWidth([...lines, hiddenHint(rawEntryCount, hunkCount(input.diffData, entries), width)], width) };
  if (mode === "summary")
    return { mode, width, lines: clampLinesToWidth(lines, width) };
  const rows = mode === "split" ? splitRows(input, width, entries) : mode === "compact" ? compactRows(input, width, entries) : unifiedRows(input, width, entries);
  if (truncated)
    rows.push(clampLineToWidth("… diff preview truncated", width));
  return { mode, width, lines: [...lines, ...rows] };
}

// src/tui-diff-component.ts
class DiffPreviewComponent {
  options;
  cachedWidth;
  cachedLines;
  constructor(options) {
    this.options = options;
  }
  update(options) {
    this.options = options;
    this.invalidate();
  }
  invalidate() {
    this.cachedWidth = undefined;
    this.cachedLines = undefined;
  }
  render(width) {
    const normalized = normalizeWidth(width, this.options.fallbackWidth ?? 80);
    if (this.cachedLines && this.cachedWidth === normalized)
      return this.cachedLines;
    const lines = [];
    for (const prefix of this.options.prefixLines ?? []) {
      for (const line of prefix.split(`
`))
        lines.push(clampLineToWidth(line, normalized));
    }
    const body = renderTuiDiff({
      diffData: this.options.diffData,
      width: normalized,
      theme: this.options.theme,
      expanded: this.options.expanded
    });
    for (const line of body.lines)
      lines.push(line);
    const clamped = lines.map((line) => visibleWidth3(line) <= normalized ? line : clampLineToWidth(line, normalized));
    this.cachedLines = clamped;
    this.cachedWidth = normalized;
    return clamped;
  }
}
function upsertDiffComponent(lastComponent, options) {
  const component = lastComponent instanceof DiffPreviewComponent ? lastComponent : new DiffPreviewComponent(options);
  component.update(options);
  return component;
}
function upsertTextComponent(lastComponent, text) {
  const component = lastComponent && !(lastComponent instanceof DiffPreviewComponent) ? lastComponent : new Text2("", 0, 0);
  component.setText(text);
  return component;
}

// src/register-tool.ts
import { Type } from "@sinclair/typebox";
function optionalIntOrString(description) {
  return Type.Optional(Type.Union([Type.Number({ description }), Type.String({ description })]));
}
function filePathParam() {
  return Type.String({ description: PARAM_DESCRIPTIONS.path });
}
function registerReadSeekTool(pi, tool) {
  const selected = wrapReadseekTool(tool);
  pi.registerTool(selected);
  return selected;
}

// src/edit.ts
var hashlineEditItemSchema = Type2.Object({
  set_line: Type2.Optional(Type2.Object({
    anchor: Type2.String({ description: PARAM_DESCRIPTIONS.anchor }),
    new_text: Type2.String({ description: PARAM_DESCRIPTIONS.newTextLine })
  }, { additionalProperties: false, description: PARAM_DESCRIPTIONS.setLine })),
  replace_lines: Type2.Optional(Type2.Object({
    start_anchor: Type2.String({ description: PARAM_DESCRIPTIONS.startAnchor }),
    end_anchor: Type2.String({ description: PARAM_DESCRIPTIONS.endAnchor }),
    new_text: Type2.String({ description: PARAM_DESCRIPTIONS.newTextRange })
  }, { additionalProperties: false, description: PARAM_DESCRIPTIONS.replaceLines })),
  insert_after: Type2.Optional(Type2.Object({
    anchor: Type2.String({ description: PARAM_DESCRIPTIONS.insertAnchor }),
    new_text: Type2.String({ description: PARAM_DESCRIPTIONS.newTextInsert })
  }, { additionalProperties: false, description: PARAM_DESCRIPTIONS.insertAfter })),
  replace: Type2.Optional(Type2.Object({
    old_text: Type2.String({ description: PARAM_DESCRIPTIONS.oldText }),
    new_text: Type2.String({ description: PARAM_DESCRIPTIONS.newText }),
    all: Type2.Optional(Type2.Boolean({ description: PARAM_DESCRIPTIONS.all }))
  }, { additionalProperties: false, description: PARAM_DESCRIPTIONS.replace })),
  replace_symbol: Type2.Optional(Type2.Object({
    symbol: Type2.String({ description: PARAM_DESCRIPTIONS.symbol }),
    new_body: Type2.String({ description: PARAM_DESCRIPTIONS.newBody })
  }, { additionalProperties: false, description: PARAM_DESCRIPTIONS.replaceSymbol }))
}, {
  additionalProperties: false,
  minProperties: 1,
  maxProperties: 1,
  description: PARAM_DESCRIPTIONS.editVariant
});
var hashlineEditSchema = Type2.Object({
  path: filePathParam(),
  language: Type2.Optional(Type2.String({ description: PARAM_DESCRIPTIONS.languageSymbol })),
  edits: Type2.Array(hashlineEditItemSchema, {
    minItems: 1,
    description: PARAM_DESCRIPTIONS.edits
  }),
  postEditVerify: Type2.Optional(Type2.Boolean({
    description: PARAM_DESCRIPTIONS.postEditVerify
  }))
}, { additionalProperties: false });
function buildEditError(path3, code, message, hint, errorDetails) {
  return {
    content: [{ type: "text", text: message }],
    isError: true,
    details: {
      diff: "",
      patch: "",
      firstChangedLine: undefined,
      readSeekValue: {
        tool: "edit",
        ok: false,
        path: path3,
        error: buildReadSeekError(code, message, hint, errorDetails)
      }
    }
  };
}
function mapEditFileError(err, filePath, _displayPath, _phase) {
  const { code, message } = formatFsError(err, "edit-error");
  return buildEditError(filePath, code, message);
}
async function executeEdit(opts) {
  await ensureHashInit();
  const { params, signal, cwd, wasReadInSession, onFileMutated, syntaxValidate } = opts;
  const parsed = params;
  const rawPath = parsed.path;
  const path3 = rawPath.replace(/^@/, "");
  const absolutePath = resolveToCwd2(path3, cwd);
  throwIfAborted(signal);
  try {
    return await withFileMutationQueue(absolutePath, async () => {
      throwIfAborted(signal);
      if (wasReadInSession && !wasReadInSession(absolutePath)) {
        const hint = `Call readSeek_digest(${JSON.stringify(rawPath)}) first, or use readSeek_grep, readSeek_search, or readSeek_write to produce fresh anchors for this file.`;
        return buildEditError(absolutePath, "file-not-read", `You must get fresh anchors for ${absolutePath} before editing it. ${hint}`, hint);
      }
      const parsedEdits = validateExactlyOneEditVariant(parsed.edits ?? []);
      if (!parsedEdits.ok) {
        return buildEditError(absolutePath, "invalid-edit-variant", parsedEdits.error);
      }
      const edits = parsedEdits.edits;
      let plan;
      try {
        plan = await readSeekEdit(absolutePath, edits, { signal, language: parsed.language });
      } catch (err) {
        throwIfAborted(signal);
        const failure = classifyReadSeekFailure(err);
        const code = failure.message.includes("stale anchor") ? "hash-mismatch" : failure.code;
        return buildEditError(absolutePath, code, failure.message, failure.hint);
      }
      if (typeof plan.before_content !== "string" || typeof plan.content !== "string") {
        return buildEditError(absolutePath, "invalid-output", "readseek edit plan did not include before_content and content");
      }
      const original = plan.before_content;
      const result = plan.content;
      const originalForSyntax = normalizeToLF(stripBom(original).text);
      const resultForSyntax = normalizeToLF(stripBom(result).text);
      if (!plan.changed) {
        return buildEditError(absolutePath, "no-op", `No changes made to ${path3}. The edits produced identical content.`);
      }
      const syntaxMode = resolveSyntaxValidateMode({ syntaxValidate });
      let syntaxWarning;
      if (syntaxMode !== "off") {
        const regression = await validateSyntaxRegression({
          filePath: absolutePath,
          before: originalForSyntax,
          after: resultForSyntax
        }, { signal });
        if (regression) {
          const message = `syntax-regression: lines ${regression.errorLines.join(", ")}`;
          if (syntaxMode === "block") {
            return buildEditError(absolutePath, "syntax-regression", message);
          }
          syntaxWarning = message;
        }
      }
      throwIfAborted(signal);
      let applied;
      try {
        applied = await readSeekEdit(absolutePath, edits, {
          apply: true,
          planHash: plan.plan_hash,
          language: parsed.language,
          cancelable: false
        });
      } catch (err) {
        throwIfAborted(signal);
        const failure = classifyReadSeekFailure(err);
        return buildEditError(absolutePath, failure.code, failure.message, failure.hint);
      }
      if (!applied.applied) {
        return buildEditError(absolutePath, "invalid-output", "readseek did not confirm that the edit was applied");
      }
      onFileMutated?.(absolutePath);
      if (parsed.postEditVerify === true) {
        let verifiedContent;
        try {
          verifiedContent = await fsReadFile(absolutePath, "utf-8");
        } catch (err) {
          return buildEditError(absolutePath, "post-edit-verification-read-failed", `Edit write completed but post-edit verification failed: could not read ${path3} after writing.`, undefined, { fsCode: err?.code, fsMessage: err?.message });
        }
        if (verifiedContent !== plan.content) {
          return buildEditError(absolutePath, "post-edit-verification-mismatch", `Edit write completed but post-edit verification did not confirm the intended content for ${path3}. Re-read the file before making follow-up edits.`, undefined, { expectedLength: plan.content.length, actualLength: verifiedContent.length });
        }
      }
      const diffResult = generateCompactOrFullDiff(original, result);
      const patch = createPatch(path3, original, result);
      const diffData = buildDiffData({
        path: absolutePath,
        oldContent: original,
        newContent: result,
        diff: diffResult.diff
      });
      const warnings = syntaxWarning ? [syntaxWarning] : [];
      const classification = classifyEdit(original, result);
      const semanticSummary = { classification: classification.classification };
      const builtOutput = buildEditOutput({
        path: absolutePath,
        displayPath: path3,
        diff: diffResult.diff,
        patch,
        diffData,
        firstChangedLine: diffResult.firstChangedLine,
        warnings,
        noopEdits: [],
        edits,
        semanticSummary
      });
      return {
        content: [{ type: "text", text: builtOutput.text }],
        details: {
          diff: diffResult.diff,
          patch: builtOutput.patch,
          diffData,
          firstChangedLine: diffResult.firstChangedLine,
          readSeekValue: builtOutput.readSeekValue
        }
      };
    });
  } catch (err) {
    if (typeof err?.code === "string") {
      return mapEditFileError(err, absolutePath, path3, "read");
    }
    throw err;
  }
}
function registerEditTool(pi, options = {}) {
  const name = options.name ?? "readSeek_edit";
  const promptMetadata = defineToolPromptMetadata({
    promptUrl: new URL("../prompts/edit.md", import.meta.url),
    promptSnippet: "Edit existing files with fresh LINE:HASH anchors",
    registeredName: name,
    toolAliases: options.toolAliases
  });
  const tool = registerReadSeekTool(pi, {
    name,
    label: "Edit",
    description: promptMetadata.description,
    promptSnippet: promptMetadata.promptSnippet,
    promptGuidelines: promptMetadata.promptGuidelines,
    parameters: hashlineEditSchema,
    renderShell: "default",
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeEdit({
        params,
        signal,
        cwd: ctx.cwd,
        wasReadInSession: options.wasReadInSession,
        onFileMutated: options.onFileMutated,
        syntaxValidate: options.syntaxValidate
      });
    },
    renderCall(args, theme, ...rest) {
      const context = rest[0] ?? {};
      const cwd = context.cwd ?? process.cwd();
      const argsComplete = context.argsComplete ?? false;
      const { path: filePath, suffix } = formatEditCallText(args, argsComplete);
      let text = theme.fg("toolTitle", theme.bold("edit"));
      if (filePath)
        text += ` ${linkToolPath(theme.fg("accent", filePath), filePath, cwd)}`;
      else
        text += ` ${theme.fg("toolOutput", "...")}`;
      const counts = Array.isArray(args?.edits) ? countEditTypes(args.edits) : undefined;
      if (counts && counts.total > 0) {
        text += ` ${theme.fg("dim", `(${counts.total} ${counts.total === 1 ? "edit" : "edits"})`)}`;
      } else if (suffix) {
        text += ` ${theme.fg("dim", suffix)}`;
      }
      text = clampLineToWidth(text, context.width);
      return upsertTextComponent(context.lastComponent, text);
    },
    renderResult(result, options2, theme, ...rest) {
      const { isPartial, isError, expanded, width, context } = resolveRenderResultContext(options2, rest, resolveReadSeekToolDisplayMode("edit") === "expanded");
      if (isPartial) {
        return renderPendingResult("pending edit", width, theme);
      }
      const textContent = result.content?.filter((c) => c.type === "text").map((c) => c.text || "").join(`
`) ?? "";
      const details = result.details ?? {};
      const diff = details.diff ?? "";
      const readSeekValue = details.readSeekValue;
      const warnings = readSeekValue?.warnings ?? [];
      const noopEdits = readSeekValue?.noopEdits ?? [];
      const semanticClassification = readSeekValue?.semanticSummary?.classification;
      const info = formatEditResultText({
        isError: isError || !!result.isError,
        diff,
        warnings,
        noopEdits,
        errorText: textContent,
        semanticClassification
      });
      const diffData = details.diffData;
      const stats = diffData?.stats ?? { added: 0, removed: 0 };
      let text = "";
      if (info.noOp) {
        text = summaryLine("no-op", { theme, style: "dim" });
        if (expanded && info.errorText)
          text += `
${theme.fg("error", info.errorText)}`;
      } else if (info.errorText) {
        const firstLine = info.errorText.split(`
`)[0] || "Error";
        text = summaryLine(expanded ? info.errorText : firstLine, { theme, style: "error" });
      } else {
        const badges = [`edited +${stats.added} -${stats.removed}`];
        if (info.semanticBadge)
          badges.push(info.semanticBadge.replace(/^✓\s*/, ""));
        if (info.warningsBadge)
          badges.push(info.warningsBadge);
        text = summaryLine(badges.join(" • "), { hidden: !!diffData && !expanded, theme, style: "success" });
        if (expanded && diffData) {
          return upsertDiffComponent(context.lastComponent, { prefixLines: text.split(`
`), diffData, theme, expanded: true });
        }
      }
      return new Text3(clampLinesToWidth(text.split(`
`), width).join(`
`), 0, 0);
    }
  });
  return tool;
}

// src/grep.ts
import { readFile as fsReadFile2, stat as fsStat } from "node:fs/promises";
import path3 from "node:path";
import { createGrepTool } from "@earendil-works/pi-coding-agent";
import { Type as Type4 } from "@sinclair/typebox";
import { Text as Text4 } from "@earendil-works/pi-tui";

// src/binary-detect.ts
function looksLikeBinary(buf) {
  if (buf.length === 0)
    return false;
  if (buf.includes(0))
    return true;
  const decoded = buf.toString("utf8");
  if (!decoded.includes("�"))
    return false;
  return !Buffer.from(decoded, "utf8").equals(buf);
}

// src/grep-output.ts
import {
  formatSize,
  truncateHead
} from "@earendil-works/pi-coding-agent";

// src/grep-budget.ts
import { DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES } from "@earendil-works/pi-coding-agent";
var GREP_OUTPUT_DEFAULT_MAX_LINES = DEFAULT_MAX_LINES;
var GREP_OUTPUT_DEFAULT_MAX_BYTES = Math.min(DEFAULT_MAX_BYTES, 50 * 1024);
function resolveDimension(jsonValue, ceiling) {
  if (jsonValue !== undefined)
    return Math.min(jsonValue, ceiling);
  return ceiling;
}
function resolveGrepOutputBudget() {
  const settings = resolveReadSeekJsonSettings().settings.grep;
  return {
    maxLines: resolveDimension(settings?.maxLines, GREP_OUTPUT_DEFAULT_MAX_LINES),
    maxBytes: resolveDimension(settings?.maxBytes, GREP_OUTPUT_DEFAULT_MAX_BYTES)
  };
}

// src/grep-output.ts
function hasScope(group) {
  return group.scope !== undefined;
}
function renderEntry(displayPath, entry) {
  if (entry.kind === "separator")
    return entry.text;
  const marker = entry.kind === "match" ? ">>" : "  ";
  return `${displayPath}:${marker}${entry.line.anchor}|${entry.line.display}`;
}
function renderGroupHeader(group) {
  if (!group.scope) {
    return `--- ${group.displayPath} (${group.matchCount} matches) ---`;
  }
  const parent = group.scope.symbol.parentName ? ` in ${group.scope.symbol.parentName}` : "";
  const suffix = group.scope.contextLines !== undefined ? `, scoped to ±${group.scope.contextLines} lines` : "";
  return `--- ${group.displayPath} :: ${group.scope.symbol.kind} ${group.scope.symbol.name}${parent} (${group.scope.symbol.startLine}-${group.scope.symbol.endLine}, ${group.matchCount} matches${suffix}) ---`;
}
function buildScopeMetadata(groups, warnings) {
  return {
    mode: "symbol",
    groups: groups.filter(hasScope).map((group) => ({
      path: group.absolutePath,
      displayPath: group.displayPath,
      symbol: group.scope.symbol,
      matchCount: group.matchCount,
      matchLines: [...group.scope.matchLines],
      lineAnchors: group.entries.flatMap((entry) => entry.kind === "separator" ? [] : [entry.line.anchor])
    })),
    warnings: [...warnings]
  };
}
function buildGrepOutput(input) {
  const fileCount = new Set(input.groups.map((group) => group.absolutePath)).size;
  const header2 = `[${input.totalMatches} matches in ${fileCount} files]`;
  let text;
  if (input.summary) {
    const fileLines = [...input.groups].sort((a, b) => b.matchCount - a.matchCount).map((group) => `${group.absolutePath}: ${group.matchCount} matches`);
    text = [header2, ...fileLines].join(`
`);
  } else {
    const blocks = [header2];
    for (const group of input.groups) {
      blocks.push(renderGroupHeader(group));
      for (const entry of group.entries) {
        blocks.push(renderEntry(group.displayPath, entry));
      }
    }
    text = blocks.join(`
`);
  }
  const passthroughLines = input.passthroughLines ?? [];
  if (passthroughLines.length > 0) {
    text += `

${passthroughLines.join(`
`)}`;
  }
  if (input.limit !== undefined && input.totalMatches === input.limit) {
    text += `

[Results truncated at ${input.limit} matches — refine pattern or increase limit]`;
  }
  const scopeWarnings = input.scopeWarnings ?? [];
  if (!input.summary && input.scopeMode === "symbol" && scopeWarnings.length > 0) {
    text = `${scopeWarnings.map((warning) => warning.message).join(`

`)}

${text}`;
  }
  const budget = resolveGrepOutputBudget();
  const truncated = truncateHead(text, {
    maxLines: budget.maxLines,
    maxBytes: budget.maxBytes
  });
  if (truncated.truncated) {
    text = `${truncated.content}

[Output truncated: showing ${truncated.outputLines} of ${truncated.totalLines} lines (${formatSize(truncated.outputBytes)} of ${formatSize(truncated.totalBytes)}). Refine pattern or increase limit.]`;
  }
  const readSeekValue = {
    tool: "grep",
    summary: input.summary,
    totalMatches: input.totalMatches,
    records: input.records.map((record) => ({
      path: record.path,
      line: record.line,
      anchor: record.anchor,
      kind: record.kind
    }))
  };
  if (!input.summary && input.scopeMode === "symbol") {
    readSeekValue.scopes = buildScopeMetadata(input.groups, scopeWarnings);
  }
  return {
    text,
    readSeekValue
  };
}

// src/file-map.ts
async function getOrGenerateMap(absPath) {
  try {
    return await readSeekMap(absPath);
  } catch {
    return null;
  }
}

// src/grep-symbol-scope.ts
function findEnclosingSymbol(map, lineNumber) {
  const byQualifiedName = new Map;
  for (const symbol of map.symbols) {
    const qname = symbol.qualified_name ?? symbol.name;
    if (!byQualifiedName.has(qname))
      byQualifiedName.set(qname, symbol);
  }
  const candidates = map.symbols.filter((symbol) => lineNumber >= symbol.start_line && lineNumber <= symbol.end_line).map((symbol) => {
    const qname = symbol.qualified_name ?? symbol.name;
    const dot = qname.lastIndexOf(".");
    const parent = dot === -1 ? undefined : byQualifiedName.get(qname.slice(0, dot));
    return {
      name: symbol.name,
      kind: symbol.kind === "constructor" ? "method" : symbol.kind,
      startLine: symbol.start_line,
      endLine: symbol.end_line,
      parentName: parent?.name
    };
  }).sort((a, b) => {
    const rangeA = a.endLine - a.startLine;
    const rangeB = b.endLine - b.startLine;
    if (rangeA !== rangeB)
      return rangeA - rangeB;
    if (a.startLine !== b.startLine)
      return a.startLine - b.startLine;
    return a.name.localeCompare(b.name);
  });
  return candidates[0] ?? null;
}
function firstLineNumber(group) {
  const first = group.entries.find((e) => e.kind !== "separator");
  return first ? first.line.line : Number.MAX_SAFE_INTEGER;
}
function buildSymbolEntries(fileLines, symbol, matchLines, scopeContext) {
  if (scopeContext === undefined) {
    const entries2 = [];
    for (let lineNumber = symbol.startLine;lineNumber <= symbol.endLine; lineNumber++) {
      const built = buildReadSeekLine(lineNumber, fileLines[lineNumber - 1] ?? "");
      entries2.push({ kind: matchLines.has(lineNumber) ? "match" : "context", line: built });
    }
    return entries2;
  }
  const ranges = [...matchLines].sort((a, b) => a - b).map((ln) => ({
    startLine: Math.max(symbol.startLine, ln - scopeContext),
    endLine: Math.min(symbol.endLine, ln + scopeContext)
  }));
  const merged = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r.startLine <= last.endLine + 1) {
      last.endLine = Math.max(last.endLine, r.endLine);
    } else {
      merged.push({ ...r });
    }
  }
  const entries = [];
  for (let i = 0;i < merged.length; i++) {
    if (i > 0)
      entries.push({ kind: "separator", text: "--" });
    const range = merged[i];
    for (let ln = range.startLine;ln <= range.endLine; ln++) {
      const built = buildReadSeekLine(ln, fileLines[ln - 1] ?? "");
      entries.push({ kind: matchLines.has(ln) ? "match" : "context", line: built });
    }
  }
  return entries;
}
function buildFallbackEntries(fileLines, matchLines, contextLines) {
  const lineMap = new Map;
  for (const matchLine of matchLines) {
    const start = Math.max(1, matchLine - contextLines);
    const end = Math.min(fileLines.length, matchLine + contextLines);
    for (let lineNumber = start;lineNumber <= end; lineNumber++) {
      const built = buildReadSeekLine(lineNumber, fileLines[lineNumber - 1] ?? "");
      const candidate = { kind: lineNumber === matchLine ? "match" : "context", line: built };
      const existing = lineMap.get(lineNumber);
      if (!existing || existing.kind === "context" && candidate.kind === "match") {
        lineMap.set(lineNumber, candidate);
      }
    }
  }
  const ordered = [...lineMap.entries()].sort(([a], [b]) => a - b);
  const entries = [];
  for (let i = 0;i < ordered.length; i++) {
    if (i > 0 && ordered[i][0] > ordered[i - 1][0] + 1)
      entries.push({ kind: "separator", text: "--" });
    entries.push(ordered[i][1]);
  }
  return entries;
}
function scopeGrepGroupsToSymbols(input) {
  const warnings = [];
  const rendered = [];
  for (const group of input.groups) {
    const fileLines = input.fileLinesByPath.get(group.absolutePath);
    const fileMap = input.fileMapsByPath.get(group.absolutePath) ?? null;
    if (!fileLines || !fileMap) {
      warnings.push({
        code: "unmappable-file",
        message: `[Warning: symbol scoping unavailable for ${group.absolutePath} — showing normal grep lines for this file]`,
        path: group.absolutePath
      });
      rendered.push({ order: firstLineNumber(group), group });
      continue;
    }
    const symbolBuckets = new Map;
    const fallbackMatchLines = [];
    for (const entry of group.entries) {
      if (entry.kind !== "match")
        continue;
      const symbol = findEnclosingSymbol(fileMap, entry.line.line);
      if (!symbol) {
        fallbackMatchLines.push(entry.line.line);
        warnings.push({
          code: "no-enclosing-symbol",
          message: `[Warning: no enclosing symbol for ${group.absolutePath}:${entry.line.line} — showing normal grep lines for this match]`,
          path: group.absolutePath,
          line: entry.line.line
        });
        continue;
      }
      const key = `${symbol.startLine}:${symbol.endLine}:${symbol.parentName ?? ""}:${symbol.name}`;
      const bucket = symbolBuckets.get(key) ?? { symbol, matchLines: new Set };
      bucket.matchLines.add(entry.line.line);
      symbolBuckets.set(key, bucket);
    }
    const scopedGroups = [...symbolBuckets.values()].sort((a, b) => {
      if (a.symbol.startLine !== b.symbol.startLine)
        return a.symbol.startLine - b.symbol.startLine;
      return a.symbol.name.localeCompare(b.symbol.name);
    }).map(({ symbol, matchLines }) => ({
      displayPath: group.displayPath,
      absolutePath: group.absolutePath,
      matchCount: matchLines.size,
      scope: {
        mode: "symbol",
        symbol,
        matchLines: [...matchLines].sort((a, b) => a - b),
        ...input.scopeContext !== undefined ? { contextLines: input.scopeContext } : {}
      },
      entries: buildSymbolEntries(fileLines, symbol, matchLines, input.scopeContext)
    }));
    for (const scopedGroup of scopedGroups)
      rendered.push({ order: scopedGroup.scope.symbol.startLine, group: scopedGroup });
    if (fallbackMatchLines.length > 0) {
      rendered.push({
        order: Math.min(...fallbackMatchLines),
        group: {
          displayPath: group.displayPath,
          absolutePath: group.absolutePath,
          matchCount: fallbackMatchLines.length,
          entries: buildFallbackEntries(fileLines, fallbackMatchLines, input.contextLines)
        }
      });
    }
    if (scopedGroups.length === 0 && fallbackMatchLines.length === 0) {
      rendered.push({ order: firstLineNumber(group), group });
    }
  }
  rendered.sort((a, b) => {
    if (a.order !== b.order)
      return a.order - b.order;
    if (a.group.absolutePath !== b.group.absolutePath)
      return a.group.absolutePath.localeCompare(b.group.absolutePath);
    return a.group.displayPath.localeCompare(b.group.displayPath);
  });
  return { groups: rendered.map((item) => item.group), warnings };
}

// src/grep-render-helpers.ts
function formatGrepCallText(args) {
  const pattern = typeof args?.pattern === "string" ? args.pattern : "";
  const parts = [];
  if (typeof args?.path === "string" && args.path !== ".") {
    parts.push(args.path);
  }
  if (typeof args?.glob === "string") {
    parts.push(args.glob);
  }
  return {
    pattern,
    suffix: parts.length > 0 ? parts.join(" ") : undefined
  };
}
var GREP_TRUNCATION_THRESHOLD = 50;
function formatGrepResultText(input) {
  if (input.isError && input.errorText) {
    return {
      summary: "",
      badges: [],
      noMatches: false,
      truncated: false,
      errorText: input.errorText
    };
  }
  const { totalMatches, summary, fileCount } = input;
  const noMatches = totalMatches === 0;
  const truncated = totalMatches > GREP_TRUNCATION_THRESHOLD;
  const matchWord = totalMatches === 1 ? "match" : "matches";
  const fileWord = fileCount === 1 ? "file" : "files";
  const summaryText = noMatches ? "" : `✓ ${totalMatches} ${matchWord} in ${fileCount} ${fileWord}`;
  const badges = [];
  if (truncated)
    badges.push("10/file cap");
  if (summary)
    badges.push("summary");
  if (input.hasBinaryWarning)
    badges.push("⚠ binary");
  return {
    summary: summaryText,
    badges,
    noMatches,
    truncated,
    errorText: undefined
  };
}

// src/coerce-obvious-int.ts
import {
  coerceObviousBase10Int as coerceObviousBase10Int2
} from "@jarkkojs/readseek-api";

// src/tui-source-render.ts
import { getLanguageFromPath, highlightCode } from "@earendil-works/pi-coding-agent";
import { wrapTextWithAnsi as wrapTextWithAnsi2 } from "@earendil-works/pi-tui";
var GREP_ANCHOR_RE = /^(.*?):(>>|  )(\d+):([0-9a-zA-Z]{1,16})\|(.*)$/;
var readSourceCache = new WeakMap;
function renderGrepSourceForDisplay(text, anchors, renderPath = (path3) => path3) {
  return text.split(`
`).map((line) => {
    const match = line.match(GREP_ANCHOR_RE);
    if (!match)
      return line;
    const anchor = `${match[3]}:${match[4]}`;
    if (!anchors.has(anchor))
      return line;
    const separator = match[2] === ">>" ? ":" : "-";
    return `${renderPath(match[1])}${separator}${match[3]}${separator}${match[5] ?? ""}`;
  }).join(`
`);
}

// src/readseek-params.ts
import { Type as Type3 } from "@sinclair/typebox";
function searchPathParam() {
  return Type3.Optional(Type3.String({ description: PARAM_DESCRIPTIONS.searchPath }));
}
function languageParam() {
  return Type3.Optional(Type3.String({ description: PARAM_DESCRIPTIONS.language }));
}
function readSeekGitSearchParams() {
  return {
    cached: Type3.Optional(Type3.Boolean({ description: PARAM_DESCRIPTIONS.cached })),
    others: Type3.Optional(Type3.Boolean({ description: PARAM_DESCRIPTIONS.others })),
    ignored: Type3.Optional(Type3.Boolean({ description: PARAM_DESCRIPTIONS.ignored }))
  };
}
function validateIgnoredRequiresOthers(tool, params) {
  const validated = validateGitSelection(params);
  if (!validated.ok) {
    return buildToolErrorResult(tool, "invalid-parameter", `${tool} parameter 'ignored' requires 'others'`);
  }
  return null;
}

// src/grep.ts
var grepSchema = Type4.Object({
  pattern: Type4.String({ description: PARAM_DESCRIPTIONS.grepPattern }),
  path: searchPathParam(),
  glob: Type4.Optional(Type4.String({ description: PARAM_DESCRIPTIONS.glob })),
  ignoreCase: Type4.Optional(Type4.Boolean({ description: PARAM_DESCRIPTIONS.ignoreCase })),
  literal: Type4.Optional(Type4.Boolean({ description: PARAM_DESCRIPTIONS.literal })),
  context: optionalIntOrString(PARAM_DESCRIPTIONS.context),
  limit: optionalIntOrString(PARAM_DESCRIPTIONS.matchLimit),
  summary: Type4.Optional(Type4.Boolean({ description: PARAM_DESCRIPTIONS.summary })),
  scope: Type4.Optional(Type4.Literal("symbol", {
    description: PARAM_DESCRIPTIONS.grepScope
  })),
  scopeContext: optionalIntOrString(PARAM_DESCRIPTIONS.scopeContext)
});
var MATCH_LINE_RE = /^(.*?):(\d+): (.*)$/;
var CONTEXT_LINE_RE = /^(.*?)-(\d+)- (.*)$/;
function parseGrepOutputLine(line) {
  const match = line.match(MATCH_LINE_RE);
  if (match) {
    return {
      kind: "match",
      displayPath: match[1],
      lineNumber: Number.parseInt(match[2], 10),
      text: match[3]
    };
  }
  const context = line.match(CONTEXT_LINE_RE);
  if (context) {
    return {
      kind: "context",
      displayPath: context[1],
      lineNumber: Number.parseInt(context[2], 10),
      text: context[3]
    };
  }
  return null;
}
var GREP_MAX_MATCHES_PER_FILE = 10;
function dedupeContextEntries(entries) {
  if (entries.length === 0)
    return entries;
  const byLine = new Map;
  for (const entry of entries) {
    if (entry.kind === "separator")
      continue;
    const existing = byLine.get(entry.line.line);
    if (!existing || entry.kind === "match" && existing.kind === "context") {
      byLine.set(entry.line.line, entry);
    }
  }
  const sorted = [...byLine.entries()].sort(([a], [b]) => a - b);
  const result = [];
  for (let i = 0;i < sorted.length; i++) {
    if (i > 0 && sorted[i][0] > sorted[i - 1][0] + 1) {
      result.push({ kind: "separator", text: "--" });
    }
    result.push(sorted[i][1]);
  }
  return result;
}
function truncateGroupEntries(group) {
  let matchesSeen = 0;
  let truncatedCount = 0;
  const kept = [];
  for (const entry of group.entries) {
    if (entry.kind === "match") {
      matchesSeen++;
      if (matchesSeen <= GREP_MAX_MATCHES_PER_FILE) {
        kept.push(entry);
      } else {
        truncatedCount++;
      }
    } else if (matchesSeen <= GREP_MAX_MATCHES_PER_FILE) {
      kept.push(entry);
    }
  }
  if (truncatedCount > 0) {
    kept.push({ kind: "separator", text: `... +${truncatedCount} more matches` });
  }
  return { ...group, entries: kept };
}
function recordsFromGroups(groups) {
  return groups.flatMap((group) => group.entries.flatMap((entry) => entry.kind === "separator" ? [] : [{ path: group.absolutePath, ...entry.line, kind: entry.kind }]));
}
function escapeForRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
async function executeGrep(opts) {
  const { toolCallId, params, signal, onUpdate, cwd, onFileAnchored } = opts;
  await ensureHashInit();
  const rawParams = params;
  const context = coerceObviousBase10Int2(rawParams.context, "context");
  if (!context.ok) {
    return buildToolErrorResult("grep", "invalid-params-combo", context.message);
  }
  const limit = coerceObviousBase10Int2(rawParams.limit, "limit");
  if (!limit.ok) {
    return buildToolErrorResult("grep", "invalid-limit", limit.message);
  }
  const scopeContext = coerceObviousBase10Int2(rawParams.scopeContext, "scopeContext");
  if (!scopeContext.ok) {
    return buildToolErrorResult("grep", "invalid-params-combo", scopeContext.message);
  }
  if (scopeContext.value !== undefined && rawParams.scope !== "symbol") {
    const message = 'Invalid scopeContext: requires scope: "symbol". For normal surrounding-line context outside symbol scope, use the `context` parameter.';
    return buildToolErrorResult("grep", "invalid-params-combo", message);
  }
  if (scopeContext.value !== undefined && scopeContext.value < 0) {
    const message = `Invalid scopeContext: expected a non-negative integer, received ${scopeContext.value}.`;
    return buildToolErrorResult("grep", "invalid-params-combo", message);
  }
  const p = {
    ...rawParams,
    context: context.value,
    limit: limit.value,
    scopeContext: scopeContext.value
  };
  const builtin = createGrepTool(cwd);
  const result = await builtin.execute(toolCallId, {
    ...p,
    context: context.value,
    limit: limit.value
  }, signal, onUpdate);
  const textBlock = result.content?.find((item) => item.type === "text" && ("text" in item) && typeof item.text === "string");
  if (!textBlock?.text)
    return result;
  const { path: rawSearchPath } = p;
  const searchPath = resolveToCwd2(rawSearchPath || ".", cwd);
  let searchPathIsDirectory = false;
  try {
    searchPathIsDirectory = (await fsStat(searchPath)).isDirectory();
  } catch {
    searchPathIsDirectory = false;
  }
  if (!searchPathIsDirectory) {
    try {
      const buf = await fsReadFile2(searchPath);
      if (looksLikeBinary(buf)) {
        const warning = `[Warning: '${p.path ?? searchPath}' appears to be a binary file — grep skips binary files by default. Use a hex tool or the read tool to inspect it.]`;
        return {
          ...result,
          content: result.content.map((item) => item === textBlock ? { ...item, text: warning } : item),
          details: {
            ...typeof result.details === "object" && result.details !== null ? result.details : {},
            readSeekValue: {
              tool: "grep",
              summary: !!p.summary,
              totalMatches: 0,
              records: []
            }
          }
        };
      }
    } catch {}
  }
  const fileCache = new Map;
  const bareCRFiles = new Set;
  const getFileLines = async (absolutePath) => {
    throwIfAborted(signal);
    if (fileCache.has(absolutePath))
      return fileCache.get(absolutePath);
    try {
      const rawBuffer = await fsReadFile2(absolutePath);
      if (looksLikeBinary(rawBuffer)) {
        fileCache.set(absolutePath, undefined);
        return;
      }
      const raw = rawBuffer.toString("utf-8");
      if (hasBareCarriageReturn(raw))
        bareCRFiles.add(absolutePath);
      const lines = normalizeToLF(stripBom(raw).text).split(`
`);
      fileCache.set(absolutePath, lines);
      return lines;
    } catch {
      fileCache.set(absolutePath, undefined);
      return;
    }
  };
  const toAbsolutePath = (displayPath) => {
    if (searchPathIsDirectory)
      return path3.resolve(searchPath, displayPath);
    return searchPath;
  };
  const groupsByPath = new Map;
  const passthroughLines = [];
  let totalMatches = 0;
  let parsedCount = 0;
  let candidateUnparsedCount = 0;
  const candidateLinePattern = /^.+(?::|-)\d+(?::|-)\s/;
  if (!p.summary) {
    const pathsToRead = new Set;
    for (const line of textBlock.text.split(`
`)) {
      throwIfAborted(signal);
      const parsed = parseGrepOutputLine(line);
      if (parsed && Number.isFinite(parsed.lineNumber) && parsed.lineNumber >= 1) {
        pathsToRead.add(toAbsolutePath(parsed.displayPath));
      }
    }
    const CONCURRENCY = 8;
    const pathList = [...pathsToRead];
    for (let i = 0;i < pathList.length; i += CONCURRENCY) {
      await Promise.all(pathList.slice(i, i + CONCURRENCY).map((p2) => getFileLines(p2)));
    }
  }
  const addSummaryMatch = (displayPath, absolutePath) => {
    let group = groupsByPath.get(displayPath);
    if (!group) {
      group = { displayPath, absolutePath, matchCount: 0, entries: [] };
      groupsByPath.set(displayPath, group);
    }
    group.matchCount++;
    totalMatches++;
  };
  const addEntry = (displayPath, absolutePath, kind, line) => {
    let group = groupsByPath.get(displayPath);
    if (!group) {
      group = { displayPath, absolutePath, matchCount: 0, entries: [] };
      groupsByPath.set(displayPath, group);
    }
    group.entries.push({ kind, line });
    if (kind === "match") {
      group.matchCount++;
      totalMatches++;
    }
  };
  for (const line of textBlock.text.split(`
`)) {
    throwIfAborted(signal);
    const parsed = parseGrepOutputLine(line);
    if (!parsed || !Number.isFinite(parsed.lineNumber) || parsed.lineNumber < 1) {
      if (candidateLinePattern.test(line)) {
        candidateUnparsedCount++;
      }
      const trimmed = line.trim();
      if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
        passthroughLines.push(trimmed);
      }
      continue;
    }
    parsedCount++;
    const absolute = toAbsolutePath(parsed.displayPath);
    if (p.summary) {
      if (parsed.kind === "match") {
        addSummaryMatch(parsed.displayPath, absolute);
      }
      continue;
    }
    const fileLines = await getFileLines(absolute);
    if (fileLines === undefined)
      continue;
    if (parsed.kind === "match" && bareCRFiles.has(absolute)) {
      const flags = p.ignoreCase ? "i" : "";
      let patternRe = null;
      try {
        patternRe = p.literal ? new RegExp(escapeForRegex(p.pattern), flags) : new RegExp(p.pattern, flags);
      } catch {}
      if (patternRe !== null) {
        let emitted = false;
        for (let i = 0;i < fileLines.length; i++) {
          if (!patternRe.test(fileLines[i]))
            continue;
          addEntry(parsed.displayPath, absolute, "match", buildReadSeekLine(i + 1, fileLines[i]));
          emitted = true;
        }
        if (emitted)
          continue;
      }
    }
    const sourceLine = fileLines[parsed.lineNumber - 1] ?? parsed.text;
    const built = buildReadSeekLine(parsed.lineNumber, sourceLine);
    addEntry(parsed.displayPath, absolute, parsed.kind, {
      ...built,
      display: escapeControlCharsForDisplay(parsed.text)
    });
  }
  if (p.summary && parsedCount === 0 && candidateUnparsedCount > 0) {
    const passthroughDetails = typeof result.details === "object" && result.details !== null ? result.details : {};
    return {
      ...result,
      details: {
        ...passthroughDetails,
        readSeekValue: {
          tool: "grep",
          summary: true,
          totalMatches: 0,
          records: []
        }
      }
    };
  }
  if (parsedCount === 0 && candidateUnparsedCount > 0) {
    const warning = "[hashline grep passthrough] Unparsed grep format; returned original output.";
    const passthroughDetails = typeof result.details === "object" && result.details !== null ? result.details : {};
    return {
      ...result,
      content: result.content.map((item) => item === textBlock ? { ...item, text: `${textBlock.text}

${warning}` } : item),
      details: {
        ...passthroughDetails,
        hashlinePassthrough: true,
        hashlineWarning: warning,
        readSeekValue: {
          tool: "grep",
          summary: !!p.summary,
          totalMatches: 0,
          records: []
        }
      }
    };
  }
  const summary = !!p.summary;
  const effectiveLimit = typeof p.limit === "number" ? p.limit : 100;
  const groups = [...groupsByPath.values()];
  for (const group of groups) {
    group.entries = dedupeContextEntries(group.entries);
  }
  let renderedGroups = totalMatches > GREP_TRUNCATION_THRESHOLD ? groups.map(truncateGroupEntries) : groups;
  let scopeWarnings = [];
  if (p.scope === "symbol" && !summary) {
    const fileLinesByPath = new Map;
    const fileMapsByPath = new Map;
    for (const group of renderedGroups) {
      const lines = await getFileLines(group.absolutePath);
      if (lines)
        fileLinesByPath.set(group.absolutePath, lines);
      fileMapsByPath.set(group.absolutePath, await getOrGenerateMap(group.absolutePath));
    }
    const scoped = scopeGrepGroupsToSymbols({
      groups: renderedGroups,
      fileLinesByPath,
      fileMapsByPath,
      contextLines: typeof p.context === "number" ? p.context : 0,
      scopeContext: typeof p.scopeContext === "number" ? p.scopeContext : undefined
    });
    renderedGroups = scoped.groups;
    scopeWarnings = scoped.warnings;
  }
  const readSeekRecords = recordsFromGroups(renderedGroups);
  const builtOutput = buildGrepOutput({
    summary: !!summary,
    totalMatches,
    groups: renderedGroups,
    limit: effectiveLimit,
    records: readSeekRecords,
    scopeMode: p.scope === "symbol" && !summary ? "symbol" : undefined,
    scopeWarnings,
    passthroughLines
  });
  if (!summary && readSeekRecords.length > 0) {
    const anchoredPaths = new Set(readSeekRecords.map((record) => record.path));
    for (const absolutePath of anchoredPaths) {
      onFileAnchored?.(absolutePath);
    }
  }
  const existingDetails = typeof result.details === "object" && result.details !== null ? result.details : {};
  const { linesTruncated: _ignoredLinesTruncated, truncation: _ignoredTruncation, ...compactDetails } = existingDetails;
  return {
    ...result,
    content: result.content.map((item) => item === textBlock ? { ...item, text: builtOutput.text } : item),
    details: {
      ...compactDetails,
      readSeekValue: builtOutput.readSeekValue
    }
  };
}
function registerGrepTool(pi, options = {}) {
  const name = options.name ?? "readSeek_grep";
  const promptMetadata = defineToolPromptMetadata({
    promptUrl: new URL("../prompts/grep.md", import.meta.url),
    promptSnippet: "Search text or regex with edit-ready LINE:HASH anchors",
    registeredName: name
  });
  const tool = registerReadSeekTool(pi, {
    name,
    label: "grep",
    description: promptMetadata.description,
    parameters: grepSchema,
    promptSnippet: promptMetadata.promptSnippet,
    promptGuidelines: promptMetadata.promptGuidelines,
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      return executeGrep({
        toolCallId,
        params,
        signal,
        onUpdate,
        cwd: ctx.cwd,
        onFileAnchored: options.onFileAnchored
      });
    },
    renderCall(args, theme, ...rest) {
      const context = rest[0] ?? {};
      const cwd = context.cwd ?? process.cwd();
      const { pattern, suffix } = formatGrepCallText(args);
      const rawPath = typeof args?.path === "string" && args.path !== "." ? args.path : undefined;
      const glob = typeof args?.glob === "string" ? args.glob : undefined;
      let text = `${renderToolLabel(theme, "grep")} ${theme.fg("accent", `/${pattern}/`)}`;
      if (suffix) {
        if (rawPath) {
          text += theme.fg("dim", " in ");
          text += linkToolPath(theme.fg("dim", rawPath), rawPath, cwd);
          if (glob)
            text += theme.fg("dim", ` ${glob}`);
        } else {
          text += theme.fg("dim", ` in ${suffix}`);
        }
      }
      return new Text4(clampLineToWidth(text, context.width), 0, 0);
    },
    renderResult(result, options2, theme, ...rest) {
      const { isPartial, isError, expanded, cwd, width } = resolveRenderResultContext(options2, rest, resolveReadSeekToolDisplayMode("grep") === "expanded");
      if (isPartial)
        return renderPendingResult("pending grep", width, theme);
      const content = result.content?.[0];
      const textContent = content?.type === "text" ? content.text : "";
      if (isError || result.isError)
        return renderErrorResult(textContent, { expanded, width, theme });
      const readSeekValue = result.details?.readSeekValue;
      const hasBinaryWarning = textContent.includes("appears to be a binary file");
      const fileSet = new Set;
      for (const r of readSeekValue?.records ?? []) {
        if (r.path)
          fileSet.add(r.path);
      }
      const info = formatGrepResultText({
        totalMatches: readSeekValue?.totalMatches ?? 0,
        summary: readSeekValue?.summary ?? false,
        records: readSeekValue?.records ?? [],
        fileCount: fileSet.size,
        hasBinaryWarning
      });
      if (info.noMatches && !hasBinaryWarning)
        return new Text4(summaryLine("no matches", { theme, style: "dim" }), 0, 0);
      const matchCount = readSeekValue?.totalMatches ?? 0;
      const matchWord = matchCount === 1 ? "match" : "matches";
      let text = summaryLine(`${matchCount} ${matchWord} returned`, {
        hidden: !!textContent && !expanded,
        theme,
        style: "success"
      });
      for (const badge of info.badges)
        text += theme.fg(badge.startsWith("⚠") ? "warning" : "dim", `  ${badge}`);
      if (expanded && textContent && readSeekValue?.records) {
        const anchors = new Set(readSeekValue.records.map((record) => record.anchor));
        text += `
` + renderGrepSourceForDisplay(textContent, anchors, (displayPath) => linkToolPath(theme.fg("dim", displayPath), displayPath, cwd));
      }
      return new Text4(clampLinesToWidth(text.split(`
`), width).join(`
`), 0, 0);
    }
  });
  return tool;
}

// src/search.ts
import path4 from "node:path";
import { Type as Type5 } from "@sinclair/typebox";

// src/stat-search-path.ts
import { stat as fsStat2 } from "node:fs/promises";
async function statSearchPathOrError(tool, rawPath, searchPath) {
  try {
    return { ok: true, stats: await fsStat2(searchPath) };
  } catch (err) {
    const path4 = rawPath ?? searchPath;
    const { code, message } = formatFsError(err, "stat-error");
    return { ok: false, error: buildToolErrorResult(tool, code, message, { path: path4 }) };
  }
}

// src/search-output.ts
function buildSearchOutput(input) {
  if (input.files.length === 0) {
    return {
      text: `No matches found for pattern: ${input.pattern}`,
      readSeekValue: {
        tool: "search",
        files: []
      }
    };
  }
  return {
    text: formatAnchoredFileBlocks(input.files),
    readSeekValue: {
      tool: "search",
      files: input.files.map((file) => ({
        path: file.path,
        ranges: file.ranges.map((range) => ({ ...range })),
        lines: file.lines.map((line) => ({ ...line }))
      }))
    }
  };
}

// src/search.ts
function mergeRanges(ranges) {
  if (ranges.length === 0)
    return [];
  if (ranges.length === 1)
    return [{ ...ranges[0] }];
  const sorted = [...ranges].sort((a, b) => a.startLine - b.startLine);
  const merged = [{ ...sorted[0] }];
  for (let i = 1;i < sorted.length; i++) {
    const current = sorted[i];
    const last = merged[merged.length - 1];
    if (current.startLine <= last.endLine + 2) {
      last.endLine = Math.max(last.endLine, current.endLine);
    } else {
      merged.push({ ...current });
    }
  }
  return merged;
}
var SEARCH_PROMPT_METADATA = defineToolPromptMetadata({
  promptUrl: new URL("../prompts/search.md", import.meta.url),
  promptSnippet: "Search code by AST structure using ast-grep-style patterns"
});
function linesFromSearchResult(result, ranges) {
  const lineMap = new Map;
  for (const match of result.matches) {
    for (const line of match.hashlines) {
      lineMap.set(line.line, buildReadSeekLineWithHash(line.line, line.hash, line.text));
    }
  }
  const lines = [];
  const seen = new Set;
  for (const range of ranges) {
    for (let line = range.startLine;line <= range.endLine; line++) {
      if (seen.has(line))
        continue;
      const readSeekLine = lineMap.get(line);
      if (!readSeekLine)
        continue;
      seen.add(line);
      lines.push(readSeekLine);
    }
  }
  return lines;
}
function readSeekLanguageForPath(language, searchPath, isFile) {
  if (language === "typescript" && isFile && path4.extname(searchPath).toLowerCase() === ".tsx")
    return "tsx";
  return language;
}
async function executeSearch(opts) {
  await ensureHashInit();
  const { params, signal, cwd, onFileAnchored } = opts;
  const p = params;
  const ignoredError = validateIgnoredRequiresOthers("search", p);
  if (ignoredError)
    return ignoredError;
  const searchPath = resolveToCwd2(p.path ?? ".", cwd);
  const statResult = await statSearchPathOrError("search", p.path, searchPath);
  if (!statResult.ok)
    return statResult.error;
  const searchPathIsFile = statResult.stats.isFile();
  try {
    const effectiveLang = readSeekLanguageForPath(p.language, searchPath, searchPathIsFile);
    const results = await readSeekSearch(searchPath, p.pattern, {
      language: effectiveLang,
      cached: p.cached,
      others: p.others,
      ignored: p.ignored,
      signal
    });
    if (results.length === 0) {
      const emptyOutput = buildSearchOutput({ pattern: p.pattern, files: [] });
      return {
        content: [{ type: "text", text: emptyOutput.text }],
        details: {
          readSeekValue: emptyOutput.readSeekValue
        }
      };
    }
    const readSeekFiles = [];
    for (const result of results) {
      const abs = path4.isAbsolute(result.file) ? result.file : path4.resolve(cwd, result.file);
      const display = path4.relative(cwd, abs) || abs;
      const ranges = result.matches.map((match) => ({ startLine: match.start_line, endLine: match.end_line }));
      const mergedRanges = mergeRanges(ranges);
      const lines = linesFromSearchResult(result, mergedRanges);
      if (lines.length === 0)
        continue;
      readSeekFiles.push({
        displayPath: display,
        path: abs,
        ranges: mergedRanges.map((range) => ({ ...range })),
        lines
      });
    }
    if (readSeekFiles.length === 0) {
      const emptyOutput = buildSearchOutput({ pattern: p.pattern, files: [] });
      return {
        content: [{ type: "text", text: emptyOutput.text }],
        details: {
          readSeekValue: emptyOutput.readSeekValue
        }
      };
    }
    const builtOutput = buildSearchOutput({
      pattern: p.pattern,
      files: readSeekFiles
    });
    for (const readSeekFile of readSeekFiles) {
      onFileAnchored?.(readSeekFile.path);
    }
    return {
      content: [{ type: "text", text: builtOutput.text }],
      details: {
        readSeekValue: builtOutput.readSeekValue
      }
    };
  } catch (err) {
    const failure = classifyReadSeekFailure(err);
    return buildToolErrorResult("search", failure.code, failure.message, failure.hint ? { hint: failure.hint } : {});
  }
}
function registerSearchTool(pi, options = {}) {
  const tool = registerReadSeekTool(pi, {
    name: "readSeek_search",
    label: "Structural Search",
    description: SEARCH_PROMPT_METADATA.description,
    promptSnippet: SEARCH_PROMPT_METADATA.promptSnippet,
    promptGuidelines: SEARCH_PROMPT_METADATA.promptGuidelines,
    parameters: Type5.Object({
      pattern: Type5.String({ description: PARAM_DESCRIPTIONS.pattern }),
      language: languageParam(),
      path: searchPathParam(),
      ...readSeekGitSearchParams()
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeSearch({ params, signal, cwd: ctx.cwd, onFileAnchored: options.onFileAnchored });
    },
    renderCall(args, theme, ...rest) {
      return renderReadSeekSearchCall(args, theme, rest, {
        label: "search",
        accent: `/${args.pattern}/`,
        flags: [args.cached && "cached", args.others && "others", args.ignored && "ignored"]
      });
    },
    renderResult(result, options2, theme, ...rest) {
      return renderAnchoredFilesResult(result, options2, theme, rest, {
        pendingLabel: "pending search",
        emptyLabel: "no matches",
        unitSingular: "match",
        unitPlural: "matches"
      });
    }
  });
  return tool;
}

// src/refs.ts
import { Type as Type6 } from "@sinclair/typebox";
import path5 from "node:path";

// src/refs-output.ts
function refsQueryLabel(input) {
  if (input.name)
    return input.name;
  if (input.scope && input.line !== undefined) {
    return input.column === undefined ? `line:${input.line}` : `line:${input.line}:${input.column}`;
  }
  return "?";
}
function buildRefsOutput(input) {
  if (input.files.length === 0) {
    return {
      text: `No references found for: ${refsQueryLabel(input)}`,
      readSeekValue: { tool: "refs", files: [] }
    };
  }
  return {
    text: formatAnchoredFileBlocks(input.files, (line) => line.enclosingSymbol ? ` (in ${line.enclosingSymbol})` : ""),
    readSeekValue: {
      tool: "refs",
      files: input.files.map((file) => ({
        path: file.path,
        lines: file.lines.map((line) => ({ ...line }))
      }))
    }
  };
}

// src/refs.ts
var REFS_PROMPT_METADATA = defineToolPromptMetadata({
  promptUrl: new URL("../prompts/refs.md", import.meta.url),
  promptSnippet: "Find references by identifier name or cursor binding"
});
function refsLine(reference) {
  return {
    ...buildReadSeekLineWithHash(reference.line, reference.line_hash, reference.text),
    enclosingSymbol: reference.enclosingSymbol
  };
}
function groupReferences(references, cwd) {
  const files = new Map;
  const seen = new Set;
  for (const reference of references) {
    const abs = path5.isAbsolute(reference.file) ? reference.file : path5.resolve(cwd, reference.file);
    const dedupeKey = `${abs}:${reference.line}:${reference.column}`;
    if (seen.has(dedupeKey))
      continue;
    seen.add(dedupeKey);
    let file = files.get(abs);
    if (!file) {
      file = { displayPath: path5.relative(cwd, abs) || abs, path: abs, lines: [] };
      files.set(abs, file);
    }
    file.lines.push(refsLine(reference));
  }
  return [...files.values()];
}
function isReadSeekCursorValidationFailure(message) {
  return /line and column must be greater than zero/i.test(message) || /line \d+ not found/i.test(message) || /column \d+ exceeds maximum column \d+ for line \d+/i.test(message);
}
async function executeRefs(opts) {
  await ensureHashInit();
  const { params, signal, cwd, onFileAnchored } = opts;
  const p = params;
  const ignoredError = validateIgnoredRequiresOthers("refs", p);
  if (ignoredError)
    return ignoredError;
  const scopeError = validateRefsNameVsScope(p);
  if (!scopeError.ok) {
    return buildToolErrorResult("refs", "invalid-parameter", `refs parameter: ${scopeError.error}`);
  }
  const searchPath = resolveToCwd2(p.path ?? ".", cwd);
  const statResult = await statSearchPathOrError("refs", p.path, searchPath);
  if (!statResult.ok)
    return statResult.error;
  try {
    const references = await readSeekRefs(searchPath, {
      name: p.name,
      scope: p.scope,
      line: p.line,
      column: p.column,
      language: p.language,
      cached: p.cached,
      others: p.others,
      ignored: p.ignored,
      signal
    });
    const files = groupReferences(references, cwd);
    const builtOutput = buildRefsOutput({
      name: p.name,
      scope: p.scope,
      line: p.line,
      column: p.column,
      files
    });
    for (const file of files) {
      onFileAnchored?.(file.path);
    }
    return {
      content: [{ type: "text", text: builtOutput.text }],
      details: { readSeekValue: builtOutput.readSeekValue }
    };
  } catch (err) {
    const failure = classifyReadSeekFailure(err);
    if (p.scope && isReadSeekCursorValidationFailure(failure.message)) {
      return buildToolErrorResult("refs", "invalid-parameter", failure.message);
    }
    return buildToolErrorResult("refs", failure.code, failure.message, failure.hint ? { hint: failure.hint } : {});
  }
}
function registerRefsTool(pi, options = {}) {
  const tool = registerReadSeekTool(pi, {
    name: "readSeek_refs",
    label: "References",
    description: REFS_PROMPT_METADATA.description,
    promptSnippet: REFS_PROMPT_METADATA.promptSnippet,
    promptGuidelines: REFS_PROMPT_METADATA.promptGuidelines,
    parameters: Type6.Object({
      name: Type6.Optional(Type6.String({ description: PARAM_DESCRIPTIONS.refsName })),
      path: searchPathParam(),
      language: languageParam(),
      scope: Type6.Optional(Type6.Boolean({ description: PARAM_DESCRIPTIONS.scope })),
      line: Type6.Optional(Type6.Number({ description: PARAM_DESCRIPTIONS.line })),
      column: Type6.Optional(Type6.Number({ description: PARAM_DESCRIPTIONS.column })),
      ...readSeekGitSearchParams()
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeRefs({ params, signal, cwd: ctx.cwd, onFileAnchored: options.onFileAnchored });
    },
    renderCall(args, theme, ...rest) {
      const accent = args.name ?? (args.scope ? args.column === undefined ? `line:${args.line}` : `line:${args.line}:${args.column}` : "?");
      return renderReadSeekSearchCall(args, theme, rest, {
        label: "refs",
        accent,
        flags: [args.scope && "scope", args.cached && "cached", args.others && "others", args.ignored && "ignored"]
      });
    },
    renderResult(result, options2, theme, ...rest) {
      return renderAnchoredFilesResult(result, options2, theme, rest, {
        pendingLabel: "pending refs",
        emptyLabel: "no references",
        unitSingular: "reference",
        unitPlural: "references"
      });
    }
  });
  return tool;
}

// src/rename.ts
import { Type as Type7 } from "@sinclair/typebox";
import path6 from "node:path";
import { Text as Text5 } from "@earendil-works/pi-tui";
var RENAME_PROMPT_METADATA = defineToolPromptMetadata({
  promptUrl: new URL("../prompts/rename.md", import.meta.url),
  promptSnippet: "Rename a symbol at a source location with verified edits"
});
var renameSchema = Type7.Object({
  path: filePathParam(),
  line: Type7.Integer({ minimum: 1, description: PARAM_DESCRIPTIONS.renameLine }),
  column: Type7.Optional(Type7.Integer({ minimum: 1, description: PARAM_DESCRIPTIONS.column })),
  to: Type7.String({ description: PARAM_DESCRIPTIONS.to }),
  workspace: Type7.Optional(Type7.Boolean({ description: PARAM_DESCRIPTIONS.workspace })),
  apply: Type7.Optional(Type7.Boolean({ description: PARAM_DESCRIPTIONS.applyDefaultTrue }))
});
async function executeRename(opts) {
  await ensureHashInit();
  const { params, signal, cwd, onFileMutated } = opts;
  const p = params;
  if (!p.to.trim()) {
    return buildToolErrorResult("rename", "invalid-parameter", "rename parameter 'to' must not be empty");
  }
  if (!Number.isSafeInteger(p.line) || p.line < 1) {
    return buildToolErrorResult("rename", "invalid-parameter", "rename parameter 'line' must be a positive integer");
  }
  if (p.column !== undefined && (!Number.isSafeInteger(p.column) || p.column < 1)) {
    return buildToolErrorResult("rename", "invalid-parameter", "rename parameter 'column' must be a positive integer");
  }
  const filePath = resolveToCwd2(p.path, cwd);
  try {
    const output = await readSeekRename(filePath, {
      to: p.to,
      line: p.line,
      column: p.column,
      workspace: p.workspace ? cwd : undefined,
      apply: p.apply ?? true,
      signal
    });
    if (output.applied) {
      for (const file of [output, ...output.others]) {
        if (file.edits.length === 0)
          continue;
        const absoluteFile = path6.isAbsolute(file.file) ? file.file : path6.resolve(cwd, file.file);
        onFileMutated?.(absoluteFile);
      }
    }
    const files = [output.file];
    for (const other of output.others) {
      const abs = path6.isAbsolute(other.file) ? other.file : path6.resolve(cwd, other.file);
      if (!files.includes(abs))
        files.push(abs);
    }
    const totalEdits = output.edits.length + output.others.reduce((sum, o) => sum + o.edits.length, 0);
    const totalConflicts = output.conflicts.length + output.others.reduce((sum, o) => sum + o.conflicts.length, 0);
    const parts = [];
    if (totalConflicts > 0) {
      parts.push(`${totalConflicts} naming conflict(s)`);
    }
    parts.push(`renamed ${output.old_name} to ${output.new_name} in ${totalEdits} location(s) across ${files.length} file(s)`);
    let text = parts.join("; ");
    if (output.applied)
      text += " (applied)";
    else
      text += " (dry-run)";
    const firstConflict = output.conflicts[0] ?? output.others.find((o) => o.conflicts.length > 0)?.conflicts[0];
    if (firstConflict) {
      text += `
First conflict at ${firstConflict.line}:${firstConflict.column}: ${firstConflict.reason}`;
    }
    return {
      content: [{ type: "text", text }],
      details: {
        readSeekValue: {
          tool: "rename",
          ok: true,
          path: filePath,
          output
        }
      }
    };
  } catch (err) {
    const failure = classifyReadSeekFailure(err);
    return buildToolErrorResult("rename", failure.code, failure.message, failure.hint ? { hint: failure.hint } : {});
  }
}
function registerRenameTool(pi, options = {}) {
  registerReadSeekTool(pi, {
    name: "readSeek_rename",
    label: "Rename",
    description: RENAME_PROMPT_METADATA.description,
    promptSnippet: RENAME_PROMPT_METADATA.promptSnippet,
    promptGuidelines: RENAME_PROMPT_METADATA.promptGuidelines,
    parameters: renameSchema,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeRename({ params, signal, cwd: ctx.cwd, onFileMutated: options.onFileMutated });
    },
    renderCall(args, theme, ...rest) {
      const context = rest[0] ?? {};
      const cwd = context.cwd ?? process.cwd();
      const displayPath = typeof args?.path === "string" ? args.path : "?";
      let text = theme.fg("toolTitle", theme.bold("rename"));
      text += ` ${linkToolPath(theme.fg("accent", displayPath), displayPath, cwd)}`;
      if (args?.to)
        text += theme.fg("dim", ` → ${args.to}`);
      return new Text5(clampLineToWidth(text, context.width), 0, 0);
    },
    renderResult(result, options2, theme, ...rest) {
      const { isPartial, isError, expanded, cwd, width } = resolveRenderResultContext(options2, rest);
      if (isPartial)
        return renderPendingResult("pending rename", width, theme);
      const content = result.content?.[0];
      const textContent = content?.type === "text" ? content.text : "";
      const readSeekValue = result.details?.readSeekValue;
      const output = readSeekValue?.output;
      if (isError || result.isError) {
        return renderErrorResult(textContent, { expanded, width, fallback: "rename failed", theme });
      }
      const outputs = output ? [output, ...output.others] : [];
      const editCount = outputs.reduce((total, file) => total + file.edits.length, 0);
      const conflictCount = outputs.reduce((total, file) => total + file.conflicts.length, 0);
      const fileCount = outputs.length;
      const action = output?.applied ? `renamed ${output.old_name} → ${output.new_name}` : `rename plan for ${output?.old_name ?? "?"} → ${output?.new_name ?? "?"} (dry-run)`;
      const details = output ? ` • ${editCount} ${editCount === 1 ? "edit" : "edits"} in ${fileCount} ${fileCount === 1 ? "file" : "files"}` : "";
      const conflicts = conflictCount > 0 ? ` • ${conflictCount} ${conflictCount === 1 ? "conflict" : "conflicts"}` : "";
      let text = summaryLine(`${action}${details}${conflicts}`, {
        theme,
        style: conflictCount > 0 ? "warning" : "success"
      });
      if (expanded && output) {
        for (const file of outputs) {
          const display = path6.relative(cwd, file.file) || file.file;
          text += `
${linkedPathLine(theme, file.file, display, cwd, ` (${file.edits.length} edits)`, width)}`;
        }
      }
      const lines = clampLinesToWidth(text.split(`
`), width);
      return new Text5(lines.join(`
`), 0, 0);
    }
  });
}

// src/write.ts
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname as dirname2, relative as relative3 } from "node:path";
import { withFileMutationQueue as withFileMutationQueue2, truncateHead as truncateHead2 } from "@earendil-works/pi-coding-agent";
import { Text as Text6 } from "@earendil-works/pi-tui";
import { Type as Type8 } from "@sinclair/typebox";

// src/pending-diff-preview.ts
import { existsSync as existsSync3, readFileSync as readFileSync2, realpathSync, statSync as statSync4 } from "node:fs";
import { dirname, isAbsolute, relative as relative2, resolve, sep } from "node:path";
var PENDING_DIFF_MAX_BYTES = 1024 * 1024;
function skip(reason) {
  return { type: "skip", reason };
}
function isInsidePath(parent, child) {
  const rel = relative2(parent, child);
  return rel === "" || rel !== "" && !rel.startsWith("..") && !rel.startsWith(sep) && !resolve(rel).startsWith(".." + sep);
}
function resolveWorkspacePreviewPath(rawPath, cwd, allowMissing) {
  if (!readseekWorker()) return skip("Changes will be shown with the tool result");
  if (typeof rawPath !== "string" || rawPath.trim() === "")
    return { type: "skip", reason: "missing path" };
  const workspace = realpathSync(cwd);
  const normalizedPath = rawPath.replace(/^@/, "");
  const explicitAbsolute = isAbsolute(normalizedPath);
  const requested = resolve(workspace, normalizedPath);
  if (existsSync3(requested)) {
    const realTarget = realpathSync(requested);
    if (!explicitAbsolute && !isInsidePath(workspace, realTarget))
      return { type: "skip", reason: "path outside workspace" };
    return { type: "ok", path: realTarget, existed: true };
  }
  if (!explicitAbsolute && !isInsidePath(workspace, requested))
    return { type: "skip", reason: "path outside workspace" };
  if (!allowMissing)
    return { type: "skip", reason: "file not found" };
  const parent = dirname(requested);
  if (!existsSync3(parent))
    return { type: "skip", reason: "parent directory not found" };
  return { type: "ok", path: requested, existed: false };
}
function readUtf8File(filePath) {
  const stat = statSync4(filePath);
  if (!stat.isFile())
    return { type: "skip", reason: "not a file" };
  if (stat.size > PENDING_DIFF_MAX_BYTES)
    return { type: "skip", reason: "file too large" };
  const content = readFileSync2(filePath, "utf-8");
  if (content.includes("\x00"))
    return { type: "skip", reason: "binary file" };
  return { type: "ok", content };
}
function buildData(filePath, previousContent, nextContent, existed, headerLabel) {
  const diff = generateDiffString(normalizeToLF(previousContent), normalizeToLF(nextContent)).diff;
  return {
    type: "ok",
    data: {
      filePath,
      previousContent,
      nextContent,
      fileExistedBeforeWrite: existed,
      headerLabel,
      diff
    }
  };
}
function buildPendingWritePreviewData(input, cwd) {
  if (typeof input.content !== "string")
    return skip("missing content");
  if (Buffer.byteLength(input.content, "utf8") > PENDING_DIFF_MAX_BYTES)
    return skip("content too large");
  const resolved = resolveWorkspacePreviewPath(input.path, cwd, true);
  if (resolved.type === "skip")
    return resolved;
  const previous = resolved.existed ? readUtf8File(resolved.path) : { type: "ok", content: "" };
  if (previous.type === "skip")
    return previous;
  return buildData(resolved.path, previous.content, input.content, resolved.existed, resolved.existed ? "pending overwrite" : "pending create");
}
function buildWritePreviewKey(input) {
  if (typeof input.path !== "string" || typeof input.content !== "string")
    return;
  return JSON.stringify({ path: input.path, content: input.content });
}
function resolvePendingDiffPreview(context, stateKey, previewKey, compute) {
  if (!previewKey)
    return;
  const root = context?.state;
  if (!root)
    return;
  const slot = root[stateKey] ??= {};
  if (slot.key !== previewKey) {
    slot.key = previewKey;
    slot.data = undefined;
    slot.pending = false;
  }
  if (slot.data !== undefined)
    return slot.data;
  if (slot.pending)
    return;
  let value;
  try {
    value = compute();
  } catch (err) {
    const skipped = { type: "skip", reason: `projection failed: ${err?.message ?? String(err)}` };
    slot.data = skipped;
    return skipped;
  }
  if (value && typeof value.then === "function") {
    slot.pending = true;
    value.then((resolved) => {
      if (slot.key !== previewKey)
        return;
      slot.data = resolved;
      slot.pending = false;
      context?.invalidate?.();
    }).catch((err) => {
      if (slot.key !== previewKey)
        return;
      slot.data = { type: "skip", reason: `projection failed: ${err?.message ?? String(err)}` };
      slot.pending = false;
      context?.invalidate?.();
    });
    return;
  }
  slot.data = value;
  return slot.data;
}

// src/write.ts
var WRITE_PENDING_PREVIEW_STATE_KEY = "hashline-write-pending-preview";
var CONTENT_PREVIEW_MAX_LINES = 200;
function formatContentPreviewLines(content, theme) {
  const lines = content.split(`
`);
  if (lines.length > 0 && lines[lines.length - 1] === "")
    lines.pop();
  const shown = lines.slice(0, CONTENT_PREVIEW_MAX_LINES);
  const width = String(shown.length).length;
  const fg = typeof theme?.fg === "function" ? (style, text) => theme.fg(style, text) : (_style, text) => text;
  const formatted = shown.map((line, index) => {
    const gutter = fg("dim", `${String(index + 1).padStart(width, " ")} │ `);
    return `  ${gutter}${line}`;
  });
  if (lines.length > CONTENT_PREVIEW_MAX_LINES) {
    formatted.push(`  ${fg("dim", `… ${lines.length - CONTENT_PREVIEW_MAX_LINES} more lines not shown`)}`);
  }
  return formatted;
}
function pendingWritePreviewParts(summary, preview, expanded, theme) {
  if (!preview || preview.type !== "ok")
    return { lines: summary.split(`
`) };
  const hasOldSide2 = preview.data.fileExistedBeforeWrite;
  const headerLine = summaryLine(preview.data.headerLabel, { hidden: !expanded });
  if (!hasOldSide2) {
    const lines = [summary, headerLine];
    if (expanded)
      lines.push(...formatContentPreviewLines(preview.data.nextContent, theme));
    return { lines };
  }
  const diffData = buildDiffData({ path: preview.data.filePath, oldContent: preview.data.previousContent, newContent: preview.data.nextContent, diff: preview.data.diff });
  return { lines: [summary, headerLine], diffData: expanded ? diffData : undefined };
}
function isToolErrorResult(result) {
  return "isError" in result && result.isError === true;
}
async function readPreviousTextForDiff(filePath) {
  try {
    const previous = await readFile(filePath);
    return {
      content: looksLikeBinary(previous) ? "" : previous.toString("utf-8"),
      existed: true
    };
  } catch (err) {
    if (err?.code === "ENOENT") {
      return { content: "", existed: false };
    }
    throw err;
  }
}
function generateWriteDiff(previousContent, nextContent) {
  if (previousContent !== "")
    return generateCompactOrFullDiff(previousContent, nextContent);
  const normalizedNext = normalizeToLF(nextContent);
  if (normalizedNext === "")
    return { diff: "", firstChangedLine: undefined };
  const lines = normalizedNext.split(`
`);
  if (lines[lines.length - 1] === "")
    lines.pop();
  const width = String(lines.length).length;
  return {
    diff: lines.map((line, index) => `+${String(index + 1).padStart(width, " ")} ${line}`).join(`
`),
    firstChangedLine: 1
  };
}
function buildWriteFsErrorResult(err, absolutePath) {
  const { code, message } = formatFsError(err, "write-error");
  return buildToolErrorResult("write", code, message, {
    path: absolutePath,
    extra: { lines: [], warnings: [] }
  });
}
async function executeWrite(opts) {
  await ensureHashInit();
  const { path: filePath, content, cwd } = opts;
  const warnings = [];
  const readSeekWarnings = [];
  if (hasBareCarriageReturn(content)) {
    const message = "File content contains bare CR (\\r) line endings; readSeek_write refuses to emit anchors that readSeek_digest/readSeek_edit would normalize differently.";
    warnings.push(message);
    readSeekWarnings.push(buildReadSeekWarning("bare-cr", message));
    return buildToolErrorResult("write", "bare-cr", `Cannot write ${filePath}
⚠️ ${message}`, {
      path: filePath,
      extra: { lines: [], warnings: readSeekWarnings }
    });
  }
  if (looksLikeBinary(Buffer.from(content, "utf-8"))) {
    const message = "File content appears to be binary.";
    warnings.push(message);
    readSeekWarnings.push(buildReadSeekWarning("binary-content", message));
    return buildToolErrorResult("write", "binary-content", `Cannot write ${filePath}
⚠️ ${message} — refusing to write.`, {
      path: filePath,
      extra: { lines: [], warnings: readSeekWarnings }
    });
  }
  const { content: previousContent, existed: existedBeforeWrite } = await readPreviousTextForDiff(filePath);
  await mkdir(dirname2(filePath), { recursive: true });
  await writeFile(filePath, content, "utf-8");
  const normalizedContent = stripBom(content).text;
  const rawLines = normalizedContent === "" ? [] : normalizedContent.split(`
`);
  if (rawLines[rawLines.length - 1] === "")
    rawLines.pop();
  for (let i = 0;i < rawLines.length; i++) {
    if (rawLines[i].endsWith("\r"))
      rawLines[i] = rawLines[i].slice(0, -1);
  }
  const readSeekLines = [];
  const displayLines = [];
  for (let i = 0;i < rawLines.length; i++) {
    const lineNum = i + 1;
    const readSeekLine = buildReadSeekLine(lineNum, rawLines[i]);
    readSeekLines.push(readSeekLine);
    displayLines.push(formatHashlineDisplay(lineNum, rawLines[i]));
  }
  const fullText = displayLines.join(`
`);
  const truncated = truncateHead2(fullText);
  let text = truncated.content;
  if (truncated.truncated) {
    if (truncated.truncatedBy === "lines") {
      text += `
[… ${truncated.totalLines - truncated.outputLines} more lines not shown — full anchors in readSeekValue]`;
    } else {
      text += `
[… output truncated at 50 KB — full anchors in readSeekValue]`;
    }
  }
  const displayPath = cwd ? relative3(cwd, filePath) || filePath : filePath;
  const normalizedPrevious = normalizeToLF(previousContent);
  const normalizedNext = normalizeToLF(content);
  const diffResult = generateWriteDiff(normalizedPrevious, normalizedNext);
  const diffData = buildDiffData({
    path: filePath,
    oldContent: normalizedPrevious,
    newContent: normalizedNext,
    diff: diffResult.diff
  });
  return {
    text,
    warnings,
    writeState: existedBeforeWrite ? "overwritten" : "created",
    diff: diffResult.diff,
    diffData,
    readSeekValue: {
      tool: "write",
      path: displayPath,
      lines: readSeekLines,
      warnings: readSeekWarnings,
      diff: diffResult.diff,
      diffData
    }
  };
}
function registerWriteTool(pi, options = {}) {
  const name = options.name ?? "readSeek_write";
  const promptMetadata = defineToolPromptMetadata({
    promptUrl: new URL("../prompts/write.md", import.meta.url),
    promptSnippet: "Create or replace a complete file with LINE:HASH anchors",
    registeredName: name
  });
  const tool = registerReadSeekTool(pi, {
    name,
    label: "write",
    description: promptMetadata.description,
    promptSnippet: promptMetadata.promptSnippet,
    promptGuidelines: promptMetadata.promptGuidelines,
    parameters: Type8.Object({
      path: filePathParam(),
      content: Type8.String({ description: PARAM_DESCRIPTIONS.content })
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const cwd = ctx?.cwd ?? process.cwd();
      const absolutePath = resolveToCwd2(params.path, cwd);
      try {
        return await withFileMutationQueue2(absolutePath, async () => {
          let result;
          try {
            result = await executeWrite({
              path: absolutePath,
              content: params.content,
              cwd
            });
          } catch (err) {
            return buildWriteFsErrorResult(err, absolutePath);
          }
          if (isToolErrorResult(result))
            return result;
          if (result.readSeekValue.lines.length > 0) {
            options.onFileAnchored?.(absolutePath);
          }
          return {
            content: [{ type: "text", text: result.text }],
            details: {
              ...result.diff !== undefined ? { diff: result.diff } : {},
              ...result.diffData !== undefined ? { diffData: result.diffData } : {},
              ...result.writeState ? { writeState: result.writeState } : {},
              readSeekValue: result.readSeekValue,
              warnings: result.warnings
            }
          };
        });
      } catch (err) {
        return buildWriteFsErrorResult(err, absolutePath);
      }
    },
    renderCall(args, theme, context = {}) {
      const { path: path7, content } = args;
      const cwd = context.cwd ?? process.cwd();
      const label = renderToolLabel(theme, "write");
      const lineCount = typeof content === "string" ? content.split(`
`).length : 0;
      const bytes = typeof content === "string" ? Buffer.byteLength(content, "utf8") : 0;
      const renderedPath = typeof path7 === "string" ? linkToolPath(theme.fg("muted", path7), path7, cwd) : theme.fg("toolOutput", "...");
      let text = clampLineToWidth(`${label} ${renderedPath}${typeof content === "string" ? ` (${lineCount} ${lineCount === 1 ? "line" : "lines"} • ${bytes} B)` : ""}`, context.width);
      if (context.executionStarted) {
        return upsertTextComponent(context.lastComponent, text);
      }
      const previewKey = buildWritePreviewKey(args ?? {});
      const preview = resolvePendingDiffPreview(context, WRITE_PENDING_PREVIEW_STATE_KEY, previewKey, () => buildPendingWritePreviewData(args ?? {}, context.cwd ?? process.cwd()));
      const expanded = !!context.expanded;
      const parts = pendingWritePreviewParts(text, preview, expanded, theme);
      if (parts.diffData) {
        return upsertDiffComponent(context.lastComponent, { prefixLines: parts.lines, diffData: parts.diffData, theme, expanded: true });
      }
      return upsertTextComponent(context.lastComponent, clampLinesToWidth(parts.lines, context.width).join(`
`));
    },
    renderResult(result, options2, theme, ...rest) {
      const { isPartial, expanded, width, context } = resolveRenderResultContext(options2, rest, resolveReadSeekToolDisplayMode("write") === "expanded");
      if (isPartial)
        return renderPendingResult("pending write", width, theme);
      const details = result.details ?? {};
      const output = result.content?.[0]?.type === "text" ? result.content[0].text : "";
      if (result.isError || details.readSeekValue?.ok === false) {
        return renderErrorResult(output, { expanded, width, fallback: "write failed", theme });
      }
      const diffData = details.diffData;
      const state = details.writeState === "overwritten" ? "overwritten" : "created";
      if (state === "created") {
        const readSeekLines = details.readSeekValue?.lines ?? [];
        const hasContent = readSeekLines.length > 0;
        const header2 = summaryLine(state, { hidden: hasContent && !expanded, theme, style: "success" });
        const lines = header2.split(`
`);
        if (expanded && hasContent) {
          const content = readSeekLines.map((l) => l.raw).join(`
`);
          lines.push(...formatContentPreviewLines(content, theme));
        }
        return new Text6(clampLinesToWidth(lines, width).join(`
`), 0, 0);
      }
      const hasExpandableDiff = !!diffData;
      let text = summaryLine(state, { hidden: hasExpandableDiff && !expanded, theme, style: "success" });
      if (expanded && hasExpandableDiff) {
        return upsertDiffComponent(context.lastComponent, { prefixLines: text.split(`
`), diffData, theme, expanded: true });
      }
      return new Text6(clampLinesToWidth(text.split(`
`), width).join(`
`), 0, 0);
    }
  });
  return tool;
}

// src/def.ts
import { Type as Type9 } from "@sinclair/typebox";
import path7 from "node:path";
var DEF_PROMPT_METADATA = defineToolPromptMetadata({
  promptUrl: new URL("../prompts/def.md", import.meta.url),
  promptSnippet: "Go to a symbol definition or declaration by name"
});
async function executeDef(opts) {
  await ensureHashInit();
  const { params, signal, cwd, onFileAnchored } = opts;
  const p = params;
  const ignoredError = validateIgnoredRequiresOthers("def", p);
  if (ignoredError)
    return ignoredError;
  if (!p.name || !p.name.trim()) {
    return buildToolErrorResult("def", "invalid-parameter", "readSeek_def requires 'name'");
  }
  const searchPath = resolveToCwd2(p.path ?? ".", cwd);
  const statResult = await statSearchPathOrError("def", p.path, searchPath);
  if (!statResult.ok)
    return statResult.error;
  try {
    const definitions = await readSeekDef(searchPath, {
      name: p.name,
      language: p.language,
      cached: p.cached,
      others: p.others,
      ignored: p.ignored,
      signal
    });
    if (definitions.length === 0) {
      return {
        content: [{ type: "text", text: "no definitions found" }],
        details: {
          readSeekValue: { tool: "def", ok: true, path: searchPath, definitions: [] }
        }
      };
    }
    const files = new Map;
    for (const def of definitions) {
      const abs = path7.isAbsolute(def.file) ? def.file : path7.resolve(cwd, def.file);
      let file = files.get(abs);
      if (!file) {
        file = { displayPath: path7.relative(cwd, abs) || abs, path: abs, lines: [] };
        files.set(abs, file);
      }
      file.lines.push(buildReadSeekLineWithHash(def.line, def.line_hash, def.text));
    }
    const fileList = [...files.values()];
    for (const file of fileList) {
      onFileAnchored?.(file.path);
    }
    const textParts = [];
    for (const file of fileList) {
      textParts.push(file.displayPath);
      for (const line of file.lines) {
        textParts.push(`  ${line.line}:${line.hash} ${line.display}`);
      }
    }
    return {
      content: [{ type: "text", text: textParts.join(`
`) }],
      details: {
        readSeekValue: { tool: "def", ok: true, path: searchPath, definitions }
      }
    };
  } catch (err) {
    const failure = classifyReadSeekFailure(err);
    return buildToolErrorResult("def", failure.code, failure.message, failure.hint ? { hint: failure.hint } : {});
  }
}
function registerDefTool(pi, options = {}) {
  registerReadSeekTool(pi, {
    name: "readSeek_def",
    label: "Definition",
    description: DEF_PROMPT_METADATA.description,
    promptSnippet: DEF_PROMPT_METADATA.promptSnippet,
    promptGuidelines: DEF_PROMPT_METADATA.promptGuidelines,
    parameters: Type9.Object({
      name: Type9.String({ description: PARAM_DESCRIPTIONS.name }),
      path: searchPathParam(),
      language: languageParam(),
      ...readSeekGitSearchParams()
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeDef({ params, signal, cwd: ctx.cwd, onFileAnchored: options.onFileAnchored });
    },
    renderCall(args, theme, ...rest) {
      return renderReadSeekSearchCall(args, theme, rest, {
        label: "def",
        accent: args.name,
        flags: [args.cached && "cached", args.others && "others", args.ignored && "ignored"]
      });
    },
    renderResult(result, options2, theme, ...rest) {
      return renderAnchoredFilesResult(result, options2, theme, rest, {
        pendingLabel: "pending def",
        emptyLabel: "no definitions",
        unitSingular: "definition",
        unitPlural: "definitions"
      });
    }
  });
}

// src/digest.ts
import { Text as Text7 } from "@earendil-works/pi-tui";
import { Type as Type10 } from "@sinclair/typebox";
var DIGEST_FACETS2 = DIGEST_FACETS;
var facetSchema = Type10.Union(DIGEST_FACETS2.map((facet) => Type10.Literal(facet)));
var digestSchema = Type10.Object({
  path: filePathParam(),
  select: Type10.Optional(Type10.Union([
    facetSchema,
    Type10.Array(facetSchema, { minItems: 1 }),
    Type10.String({
      description: PARAM_DESCRIPTIONS.selectComma
    })
  ], {
    description: PARAM_DESCRIPTIONS.select
  })),
  at: Type10.Optional(Type10.String({
    description: PARAM_DESCRIPTIONS.at
  })),
  end: optionalIntOrString(PARAM_DESCRIPTIONS.end),
  limit: optionalIntOrString(PARAM_DESCRIPTIONS.limit),
  depth: optionalIntOrString(PARAM_DESCRIPTIONS.digestDepth),
  language: Type10.Optional(Type10.String({ description: PARAM_DESCRIPTIONS.languageOverride })),
  visionMode: Type10.Optional(Type10.Union(VISION_MODES.map((mode) => Type10.Literal(mode)), { description: PARAM_DESCRIPTIONS.visionModeDigest })),
  visionLevel: Type10.Optional(Type10.Union(VISION_LEVELS.map((level) => Type10.Literal(level)), { description: PARAM_DESCRIPTIONS.visionLevel }))
});
function hasDigestAnchors(value) {
  if (!value || typeof value !== "object")
    return false;
  const record = value;
  if (Array.isArray(record.hashlines) && record.hashlines.length > 0)
    return true;
  return Object.values(record).some(hasDigestAnchors);
}
function parseSelect(select) {
  if (select === undefined)
    return;
  if (Array.isArray(select)) {
    const facets = select;
    if (facets.length === 0)
      throw new Error("select must include at least one facet");
    for (const facet of facets) {
      if (!DIGEST_FACETS2.includes(facet)) {
        throw new Error(`unknown digest facet \`${facet}\`; expected ${DIGEST_FACETS2.join(", ")}`);
      }
    }
    return facets;
  }
  if (typeof select !== "string") {
    throw new Error("select must be a facet, facet list, or comma-separated facets");
  }
  if (DIGEST_FACETS2.includes(select)) {
    return select;
  }
  const parts = select.split(",").map((part) => part.trim()).filter((part) => part.length > 0);
  if (parts.length === 0)
    throw new Error("select must include at least one facet");
  for (const part of parts) {
    if (!DIGEST_FACETS2.includes(part)) {
      throw new Error(`unknown digest facet \`${part}\`; expected ${DIGEST_FACETS2.join(", ")}`);
    }
  }
  return parts;
}
function selectedFacets(select) {
  if (select === undefined)
    return ["content"];
  return Array.isArray(select) ? select : [select];
}
function summarizeEnvelope(envelope, facets) {
  if (!envelope || typeof envelope !== "object")
    return `digested ${facets.join(",")}`;
  const record = envelope;
  const parts = [];
  for (const facet of facets) {
    if (facet === "metadata" || record[facet] !== undefined)
      parts.push(facet);
  }
  if (record.metadata !== undefined && !parts.includes("metadata"))
    parts.unshift("metadata");
  return `digested ${parts.join(",") || "metadata"}`;
}
function parseImageEnvelope(envelope) {
  if (!envelope || typeof envelope !== "object")
    return;
  const record = envelope;
  if (!record.metadata || typeof record.metadata !== "object")
    return;
  const metadata = record.metadata;
  if (typeof metadata.type !== "string" || !metadata.type.startsWith("image/"))
    return;
  if (!record.content || typeof record.content !== "object")
    return { metadata };
  const content = record.content;
  const mime = content.mime ?? content.type ?? metadata.mime ?? metadata.type;
  const prepared = content.encoding === "base64" && typeof content.data === "string" && typeof mime === "string" ? { data: content.data, mimeType: mime } : undefined;
  return { metadata, prepared };
}
function buildDigestSuccess(filePath, facets, envelope, content = [{ type: "text", text: JSON.stringify(envelope) }]) {
  return {
    content,
    details: {
      readSeekValue: {
        tool: "digest",
        ok: true,
        path: filePath,
        select: facets,
        envelope
      }
    }
  };
}
async function executeDigest(opts) {
  await ensureHashInit();
  const { params, signal, cwd, onFileAnchored } = opts;
  const p = params;
  let select;
  try {
    select = parseSelect(p.select);
  } catch (err) {
    return buildToolErrorResult("digest", "invalid-parameter", err?.message ?? String(err), {
      path: p.path
    });
  }
  const facets = selectedFacets(select);
  const appliesImagePolicy = opts.imageMode !== undefined && facets.includes("content");
  const end = coerceObviousBase10Int2(p.end, "end");
  if (!end.ok || end.value !== undefined && end.value < 1) {
    const message = end.ok ? `Invalid end: expected a positive integer, received ${end.value}.` : end.message;
    return buildToolErrorResult("digest", "invalid-parameter", message, { path: p.path });
  }
  const limit = coerceObviousBase10Int2(p.limit, "limit");
  if (!limit.ok || limit.value !== undefined && limit.value < 1) {
    const message = limit.ok ? `Invalid limit: expected a positive integer, received ${limit.value}.` : limit.message;
    return buildToolErrorResult("digest", "invalid-parameter", message, { path: p.path });
  }
  const depth = coerceObviousBase10Int2(p.depth, "depth");
  if (!depth.ok || depth.value !== undefined && depth.value < 0) {
    const message = depth.ok ? `Invalid depth: expected a non-negative integer, received ${depth.value}.` : depth.message;
    return buildToolErrorResult("digest", "invalid-parameter", message, { path: p.path });
  }
  if (depth.value !== undefined && !facets.includes("map")) {
    return buildToolErrorResult("digest", "invalid-parameter", "depth requires the map facet.", { path: p.path });
  }
  const at = typeof p.at === "string" ? p.at.trim() : undefined;
  if (p.at !== undefined && !at) {
    return buildToolErrorResult("digest", "invalid-parameter", "Invalid at: expected a non-empty location.", {
      path: p.path
    });
  }
  if (p.visionLevel !== undefined && p.visionMode === undefined && !appliesImagePolicy) {
    return buildToolErrorResult("digest", "invalid-params-combo", "visionLevel requires visionMode.", {
      path: p.path
    });
  }
  const filePath = resolveToCwd2(p.path, cwd);
  const commonOptions = {
    select,
    signal,
    depth: depth.value ?? (facets.includes("map") ? DEFAULT_DIGEST_MAP_DEPTH : undefined)
  };
  const textOptions = {
    ...commonOptions,
    at,
    end: end.value,
    limit: limit.value,
    language: p.language
  };
  const hasTextOptions = at !== undefined || end.value !== undefined || limit.value !== undefined || p.language !== undefined;
  const hasVisionOptions = p.visionMode !== undefined || p.visionLevel !== undefined;
  const initialVisionMode = appliesImagePolicy ? undefined : p.visionMode;
  const initialVisionLevel = appliesImagePolicy ? undefined : p.visionLevel;
  try {
    const envelope = await readSeekDigestNative(filePath, {
      ...appliesImagePolicy ? commonOptions : textOptions,
      visionMode: initialVisionMode,
      visionLevel: initialVisionLevel,
      vision: initialVisionMode !== undefined && initialVisionMode !== "none"
    });
    const image = appliesImagePolicy ? parseImageEnvelope(envelope) : undefined;
    if (image) {
      const imageDetails = { metadata: image.metadata };
      if (opts.imageMode === "off") {
        return buildDigestSuccess(filePath, facets, imageDetails, [
          { type: "text", text: `[Skipped standalone image: ${p.path}; readseek.imageMode is off]` }
        ]);
      }
      if (opts.imageMode === "auto" && opts.modelSupportsImages && image.prepared) {
        return buildDigestSuccess(filePath, facets, imageDetails, [
          { type: "image", data: image.prepared.data, mimeType: image.prepared.mimeType }
        ]);
      }
      const visionMode = p.visionMode && p.visionMode !== "none" ? p.visionMode : "all";
      const analyzedEnvelope = await readSeekDigestNative(filePath, {
        ...commonOptions,
        visionMode,
        visionLevel: p.visionLevel,
        vision: true
      });
      return buildDigestSuccess(filePath, facets, analyzedEnvelope);
    }
    if (p.visionLevel !== undefined && p.visionMode === undefined) {
      return buildToolErrorResult("digest", "invalid-params-combo", "visionLevel requires visionMode.", {
        path: p.path
      });
    }
    const textEnvelope = appliesImagePolicy && (hasTextOptions || hasVisionOptions) ? await readSeekDigestNative(filePath, {
      ...textOptions,
      visionMode: p.visionMode,
      visionLevel: p.visionLevel,
      vision: p.visionMode !== undefined && p.visionMode !== "none"
    }) : envelope;
    if (hasDigestAnchors(textEnvelope))
      onFileAnchored?.(filePath);
    return buildDigestSuccess(filePath, facets, textEnvelope);
  } catch (err) {
    const failure = classifyReadSeekFailure(err);
    return buildToolErrorResult("digest", failure.code, failure.message, failure.hint ? { hint: failure.hint } : {});
  }
}
function registerDigestTool(pi, options = {}) {
  const promptMetadata = defineToolPromptMetadata({
    promptUrl: new URL("../prompts/digest.md", import.meta.url),
    promptSnippet: "Digest source facets as a native CLI envelope",
    registeredName: options.name ?? "readSeek_digest",
    toolAliases: options.toolAliases
  });
  return registerReadSeekTool(pi, {
    name: options.name ?? "readSeek_digest",
    label: "Digest",
    description: promptMetadata.description,
    promptSnippet: promptMetadata.promptSnippet,
    toolAliases: options.toolAliases,
    promptGuidelines: promptMetadata.promptGuidelines,
    parameters: digestSchema,
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeDigest({
        params,
        signal,
        cwd: ctx.cwd,
        onFileAnchored: options.onFileAnchored,
        imageMode: options.imageMode,
        modelSupportsImages: ctx.model?.input.includes("image") ?? false
      });
    },
    renderCall(args, theme, ...rest) {
      const context = rest[0] ?? {};
      const cwd = context.cwd ?? process.cwd();
      const displayPath = typeof args?.path === "string" ? args.path : "?";
      let text = theme.fg("toolTitle", theme.bold("digest"));
      text += ` ${linkToolPath(theme.fg("accent", displayPath), displayPath, cwd)}`;
      if (args?.select !== undefined) {
        const select = Array.isArray(args.select) ? args.select.join(",") : String(args.select);
        text += theme.fg("dim", ` [${select}]`);
      }
      if (typeof args?.at === "string" && args.at)
        text += theme.fg("dim", ` @ ${args.at}`);
      return new Text7(clampLineToWidth(text, context.width), 0, 0);
    },
    renderResult(result, options2, theme, ...rest) {
      const { isPartial, isError, expanded, width } = resolveRenderResultContext(options2, rest);
      if (isPartial)
        return renderPendingResult("pending digest", width, theme);
      const textContent = result.content?.[0]?.type === "text" ? result.content[0].text : "";
      if (isError || result.isError) {
        return renderErrorResult(textContent, { expanded, width, fallback: "digest failed", theme });
      }
      const value = result.details?.readSeekValue;
      const facets = Array.isArray(value?.select) ? value.select : ["content"];
      const label = summarizeEnvelope(value?.envelope, facets);
      let text = summaryLine(label, { hidden: !!textContent && !expanded, theme, style: "success" });
      if (expanded && textContent)
        text += `
${textContent}`;
      return new Text7(clampLinesToWidth(text.split(`
`), width).join(`
`), 0, 0);
    }
  });
}

// src/view.ts
import {
  DEFAULT_MAX_BYTES as DEFAULT_MAX_BYTES2,
  DEFAULT_MAX_LINES as DEFAULT_MAX_LINES2,
  truncateHead as truncateHead3
} from "@earendil-works/pi-coding-agent";
import { Text as Text8 } from "@earendil-works/pi-tui";
import { Type as Type11 } from "@sinclair/typebox";
var NODE_KINDS = DOCUMENT_NODE_KINDS;
var VIEW_PROMPT_METADATA = defineToolPromptMetadata({
  promptUrl: new URL("../prompts/view.md", import.meta.url),
  promptSnippet: "Digest a document's structure or selected content"
});
async function executeView(opts) {
  await ensureHashInit();
  const { params, signal, cwd } = opts;
  const input = params;
  const page = coerceObviousBase10Int2(input.page, "page");
  if (!page.ok || page.value !== undefined && page.value < 1) {
    const message = page.ok ? `Invalid page: expected a positive integer, received ${page.value}.` : page.message;
    return buildToolErrorResult("view", "invalid-page", message, { path: input.path });
  }
  const depth = coerceObviousBase10Int2(input.depth, "depth");
  if (!depth.ok || depth.value !== undefined && depth.value < 0) {
    const message = depth.ok ? `Invalid depth: expected a non-negative integer, received ${depth.value}.` : depth.message;
    return buildToolErrorResult("view", "invalid-depth", message, { path: input.path });
  }
  const node = input.node?.trim();
  if (input.node !== undefined && !node) {
    return buildToolErrorResult("view", "invalid-node", "Invalid node: expected a non-empty ID.", {
      path: input.path
    });
  }
  const visionValidation = validateVisionLevelVsMode({
    outline: input.outline,
    visionMode: input.visionMode,
    visionLevel: input.visionLevel
  });
  if (!visionValidation.ok) {
    return buildToolErrorResult("view", "invalid-params-combo", `${visionValidation.error}.`, {
      path: input.path
    });
  }
  const filePath = resolveToCwd2(input.path, cwd);
  try {
    const output = await readSeekView(filePath, {
      node,
      page: page.value,
      kind: input.kind,
      depth: depth.value,
      outline: input.outline,
      visionMode: input.visionMode,
      visionLevel: input.visionLevel,
      signal
    });
    const truncation = truncateHead3(output, {
      maxLines: DEFAULT_MAX_LINES2,
      maxBytes: DEFAULT_MAX_BYTES2
    });
    const notice = truncation.truncated ? `
[… document view truncated; narrow it with page, node, kind, or depth]` : "";
    return {
      content: [{ type: "text", text: `${truncation.content}${notice}` }],
      details: {
        readSeekValue: {
          tool: "view",
          path: filePath,
          truncated: truncation.truncated
        }
      }
    };
  } catch (error) {
    const failure = classifyReadSeekFailure(error);
    return buildToolErrorResult("view", failure.code, failure.message, failure.hint ? { hint: failure.hint } : {});
  }
}
function registerViewTool(pi) {
  return registerReadSeekTool(pi, {
    name: "readSeek_view",
    label: "View",
    description: VIEW_PROMPT_METADATA.description,
    promptSnippet: VIEW_PROMPT_METADATA.promptSnippet,
    promptGuidelines: VIEW_PROMPT_METADATA.promptGuidelines,
    parameters: Type11.Object({
      path: filePathParam(),
      node: Type11.Optional(Type11.String({ description: PARAM_DESCRIPTIONS.node })),
      page: optionalIntOrString(PARAM_DESCRIPTIONS.page),
      kind: Type11.Optional(Type11.Union(NODE_KINDS.map((kind) => Type11.Literal(kind)), {
        description: PARAM_DESCRIPTIONS.kind
      })),
      depth: optionalIntOrString(PARAM_DESCRIPTIONS.depth),
      visionMode: Type11.Optional(Type11.Union(VISION_ANALYSIS_MODES.map((mode) => Type11.Literal(mode)), { description: PARAM_DESCRIPTIONS.visionModeView })),
      visionLevel: Type11.Optional(Type11.Union(VISION_LEVELS.map((level) => Type11.Literal(level)), { description: PARAM_DESCRIPTIONS.visionLevel })),
      outline: Type11.Optional(Type11.Boolean({ description: PARAM_DESCRIPTIONS.outline }))
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      return executeView({ params, signal, cwd: ctx.cwd });
    },
    renderCall(args, theme, ...rest) {
      const context = rest[0] ?? {};
      const cwd = context.cwd ?? process.cwd();
      const displayPath = typeof args?.path === "string" ? args.path : "?";
      const text = `${theme.fg("toolTitle", theme.bold("view"))} ${linkToolPath(theme.fg("accent", displayPath), displayPath, cwd)}`;
      return new Text8(clampLineToWidth(text, context.width), 0, 0);
    },
    renderResult(result, options, theme, ...rest) {
      const { isPartial, isError, expanded, width } = resolveRenderResultContext(options, rest);
      if (isPartial)
        return renderPendingResult("pending view", width, theme);
      const textContent = result.content?.[0]?.type === "text" ? result.content[0].text : "";
      if (isError || result.isError) {
        return renderErrorResult(textContent, { expanded, width, fallback: "view failed", theme });
      }
      const lines = textContent.split(`
`).filter(Boolean).length;
      let text = summaryLine(`loaded ${lines} document ${lines === 1 ? "line" : "lines"}`, {
        hidden: !!textContent && !expanded,
        theme,
        style: "success"
      });
      if (expanded && textContent)
        text += `
${textContent}`;
      return new Text8(clampLinesToWidth(text.split(`
`), width).join(`
`), 0, 0);
    }
  });
}

// src/session-anchors.ts
class SessionAnchors {
  #paths = new Set(readseekWorker()?.anchors ?? []);
  markAnchored(absolutePath) {
    this.#paths.add(absolutePath);
    recordReadseekAnchor("mark", absolutePath);
  }
  forget(absolutePath) {
    this.#paths.delete(absolutePath);
    recordReadseekAnchor("forget", absolutePath);
  }
  clear() {
    this.#paths.clear();
    recordReadseekAnchor("clear");
  }
  hasFreshAnchors(absolutePath) {
    return this.#paths.has(absolutePath);
  }
}

// index.ts
var READSEEK_TOOL_ENTRIES = [
  { builtIn: "edit", readSeekName: "readSeek_edit" },
  { builtIn: "grep", readSeekName: "readSeek_grep" },
  { builtIn: null, readSeekName: "readSeek_search" },
  { builtIn: null, readSeekName: "readSeek_refs" },
  { builtIn: null, readSeekName: "readSeek_rename" },
  { builtIn: "write", readSeekName: "readSeek_write" },
  { builtIn: null, readSeekName: "readSeek_def" },
  { builtIn: "read", readSeekName: "readSeek_digest" },
  { builtIn: null, readSeekName: "readSeek_view" }
];
function formatSettingsWarning(warning) {
  return `${warning.message} (${warning.source})`;
}
function toolRoutingPolicy(aliases) {
  return renderToolRoutingPolicy({
    aliases,
    title: "ReadSeek tool policy:"
  });
}
function piReadSeekExtension(pi) {
  const sessionAnchors = new SessionAnchors;
  const markAnchored = (absolutePath) => sessionAnchors.markAnchored(absolutePath);
  const hasFreshAnchors = (absolutePath) => sessionAnchors.hasFreshAnchors(absolutePath);
  const forgetAnchors = (absolutePath) => sessionAnchors.forget(absolutePath);
  const { settings } = resolveReadSeekJsonSettings();
  const replacedBuiltIns = new Set(settings.overrideTools ?? []);
  const swap = (builtIn, readSeekName) => replacedBuiltIns.has(builtIn) ? builtIn : readSeekName;
  const readName = swap("read", "readSeek_digest");
  const editName = swap("edit", "readSeek_edit");
  const writeName = swap("write", "readSeek_write");
  const grepName = swap("grep", "readSeek_grep");
  const toolAliases = {
    readSeek_digest: readName,
    readSeek_edit: editName,
    readSeek_grep: grepName,
    readSeek_write: writeName
  };
  const policyAliases = Object.fromEntries(TOOL_NAMES.map((name) => {
    const readSeekName = `readSeek_${name}`;
    return [name, toolAliases[readSeekName] ?? readSeekName];
  }));
  registerEditTool(pi, { wasReadInSession: hasFreshAnchors, onFileMutated: forgetAnchors, name: editName, toolAliases });
  registerGrepTool(pi, { onFileAnchored: markAnchored, name: grepName });
  registerSearchTool(pi, { onFileAnchored: markAnchored });
  registerRefsTool(pi, { onFileAnchored: markAnchored });
  registerRenameTool(pi, { onFileMutated: forgetAnchors });
  registerDefTool(pi, { onFileAnchored: markAnchored });
  registerDigestTool(pi, {
    onFileAnchored: markAnchored,
    name: readName,
    toolAliases,
    imageMode: replacedBuiltIns.has("read") ? resolveReadSeekImageMode() : undefined
  });
  registerViewTool(pi);
  registerWriteTool(pi, { onFileAnchored: markAnchored, name: writeName });
  const activeReadSeekNames = READSEEK_TOOL_ENTRIES.map((entry) => entry.builtIn && replacedBuiltIns.has(entry.builtIn) ? entry.builtIn : entry.readSeekName);
  const inactiveReadSeekNames = new Set(READSEEK_TOOL_ENTRIES.filter((entry) => entry.builtIn !== null && replacedBuiltIns.has(entry.builtIn)).map((entry) => entry.readSeekName));
  const activateReadSeekTools = () => {
    if (!readSeekBinaryAvailability().available)
      return false;
    const current = pi.getActiveTools();
    const currentSet = new Set(current);
    const missing = activeReadSeekNames.some((name) => !currentSet.has(name));
    const extraInactive = current.some((name) => inactiveReadSeekNames.has(name));
    if (!missing && !extraInactive)
      return true;
    pi.setActiveTools([
      ...new Set([...current, ...activeReadSeekNames].filter((name) => !inactiveReadSeekNames.has(name)))
    ]);
    return true;
  };
  pi.on("before_agent_start", (event) => {
    if (!activateReadSeekTools())
      return;
    return { systemPrompt: `${event.systemPrompt}

${toolRoutingPolicy(policyAliases)}` };
  });
  pi.on("session_start", (_event, ctx) => {
    sessionAnchors.clear();
    const { warnings } = resolveReadSeekJsonSettings();
    const problems = warnings.map(formatSettingsWarning);
    const availability = readSeekBinaryAvailability();
    if (!availability.available) {
      problems.push(`ReadSeek unavailable: ${availability.reason}`);
    }
    for (const problem of problems) {
      if (ctx.hasUI)
        ctx.ui.notify(problem, "warning");
      else
        console.warn(problem);
    }
    activateReadSeekTools();
  });
}
export {
  piReadSeekExtension as default
};
