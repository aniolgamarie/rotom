import { createHash, createHmac } from "node:crypto";

import type { ResultClass } from "./types.ts";

export const ALLOW_REPEAT_MARKER = "loop-guard: allow-repeat";
const DEFAULT_MAX_CANONICAL_CHARS = 1_000_000;
// 排除常见的误报模式：
// - "0 matches" / "no matches" 是 grep 正常无结果输出
// - "0 errors" 表示成功
// - "error:" 后跟数字通常是预期的错误码输出
const FAILURE_PATTERN =
	/\b(error|failed|failure|exception|referenceerror|typeerror|syntaxerror|enoent|eperm|eacces|erofs|permission denied|not found|tool .* not found|exit code [1-9])\b/i;
const FAILURE_EXCLUSION_PATTERN =
	/\b(0\s+(matches|errors|failures)|no\s+matches\s+found|succeeded|successful)\b/i;

export class FingerprintInputError extends Error {
	constructor(message: string) {
		super(message);
		this.name = "FingerprintInputError";
	}
}

export function stableStringify(
	value: unknown,
	maxChars = DEFAULT_MAX_CANONICAL_CHARS,
): string {
	const ancestors = new Set<object>();
	let size = 0;

	function append(part: string): string {
		size += part.length;
		if (size > maxChars) {
			throw new FingerprintInputError(`canonical input exceeds ${maxChars} characters`);
		}
		return part;
	}

	function visit(item: unknown, depth: number): string {
		if (depth > 64) throw new FingerprintInputError("canonical input exceeds 64 levels");
		if (item === null) return append("null");
		if (typeof item === "string") return append(JSON.stringify(item));
		if (typeof item === "boolean") return append(item ? "true" : "false");
		if (typeof item === "number") {
			if (Number.isNaN(item)) return append('"<nan>"');
			if (item === Infinity) return append('"<infinity>"');
			if (item === -Infinity) return append('"<-infinity>"');
			if (Object.is(item, -0)) return append("-0");
			return append(String(item));
		}
		if (typeof item === "bigint") return append(JSON.stringify(`${item}n`));
		if (typeof item === "undefined") return append('"<undefined>"');
		if (typeof item === "function" || typeof item === "symbol") {
			throw new FingerprintInputError(`unsupported canonical value: ${typeof item}`);
		}

		const object = item as object;
		if (ancestors.has(object)) throw new FingerprintInputError("cyclic tool input");
		ancestors.add(object);
		try {
			if (Array.isArray(item)) {
				let output = append("[");
				for (let index = 0; index < item.length; index++) {
					if (index > 0) output += append(",");
					output += visit(item[index], depth + 1);
				}
				return output + append("]");
			}

			const record = item as Record<string, unknown>;
			const keys = Object.keys(record).sort();
			let output = append("{");
			for (let index = 0; index < keys.length; index++) {
				if (index > 0) output += append(",");
				const key = keys[index];
				output += append(JSON.stringify(key)) + append(":") + visit(record[key], depth + 1);
			}
			return output + append("}");
		} finally {
			ancestors.delete(object);
		}
	}

	return visit(value, 0);
}

export function stripAllowRepeatAnnotation(command: unknown): string {
	if (typeof command !== "string") return String(command ?? "");
	return command
		.replace(/[ \t]*(?:#[ \t]*)?loop-guard:[ \t]*allow-repeat(?=[ \t]*(?:\n|$))/g, "")
		.trim();
}

export function canonicalToolInput(
	toolName: string,
	input: Record<string, unknown>,
): Record<string, unknown> {
	if (toolName !== "bash") return input;
	return { ...input, command: stripAllowRepeatAnnotation(input.command) };
}

export function actionFingerprint(
	toolName: string,
	input: Record<string, unknown>,
	cwd: string,
): string {
	const canonical = stableStringify({
		toolName,
		cwd,
		input: canonicalToolInput(toolName, input),
	});
	return sha256(canonical);
}

export function createSessionSalt(sessionId: string): string {
	return sha256(`starter-pi-loop-guard:v1:${sessionId}`);
}

export function sessionScopedDigest(fingerprint: string, sessionSalt: string): string {
	return createHmac("sha256", sessionSalt).update(fingerprint).digest("hex").slice(0, 24);
}

export function resultText(content: unknown): string {
	if (!Array.isArray(content)) return "";
	return content
		.map((part) => {
			if (!part || typeof part !== "object" || !("text" in part)) return "";
			return String((part as { text?: unknown }).text ?? "");
		})
		.join("\n");
}

export function normalizeResultText(text: string): string {
	return text
		.normalize("NFKC")
		.replace(/\u001b\[[0-9;]*m/g, "")
		.replace(/\r\n?/g, "\n")
		.split("\n")
		.map((line) => line.trimEnd())
		.join("\n")
		.trim();
}

export function resultFingerprint(content: unknown): string {
	return sha256(normalizeResultText(resultText(content)));
}

export function classifyResult(content: unknown, isError: boolean): ResultClass {
	const text = normalizeResultText(resultText(content));
	if (isError) return "error";
	if (text === "") return "empty";
	const hasFailure = FAILURE_PATTERN.test(text);
	// 排除模式仅在无失败模式时生效，避免 "Build succeeded with 3 errors" 被误判为成功
	if (!hasFailure && FAILURE_EXCLUSION_PATTERN.test(text)) return "success";
	return hasFailure ? "failure-text" : "success";
}

function sha256(value: string): string {
	return createHash("sha256").update(value).digest("hex");
}
