import type { ActionReference } from "./types.ts";

export const ACTION_DIGEST_PATTERN = /^[0-9a-f]{24}$/;

export function formatActionReference(digest: unknown): ActionReference | undefined {
	if (typeof digest !== "string" || !ACTION_DIGEST_PATTERN.test(digest)) return undefined;
	return `action:${digest}`;
}

export function isActionReference(value: unknown): value is ActionReference {
	return typeof value === "string" && value.startsWith("action:") && ACTION_DIGEST_PATTERN.test(value.slice(7));
}
