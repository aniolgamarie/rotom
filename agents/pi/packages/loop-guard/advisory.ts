import { createHash } from "node:crypto";

import type {
	ActionResultObservation,
	AdvisoryFinding,
	EffectiveConfig,
	ResponseObservation,
} from "./types.ts";

export interface ResponseAnalysis {
	classification: "empty" | "below-minimum" | "analyzed";
	coverage: "assistant-visible-text-only";
	finding?: AdvisoryFinding;
}

export interface AdvisorySummary {
	responseObservations: number;
	responseFindings: number;
	cycleFindings: number;
	latestFinding?: AdvisoryFinding;
	coverage: "assistant-visible-text-only";
}

export class AdvisoryTracker {
	private responses: ResponseObservation[] = [];
	private findings = new Map<string, AdvisoryFinding>();
	private latestFinding?: AdvisoryFinding;
	private responseStreak = 0;

	observeResponse(text: string, sequence: number, config: EffectiveConfig): ResponseAnalysis {
		const normalized = normalizeAssistantText(text);
		if (normalized.length === 0) {
			return { classification: "empty", coverage: "assistant-visible-text-only" };
		}
		if (normalized.length < config.minResponseChars) {
			return { classification: "below-minimum", coverage: "assistant-visible-text-only" };
		}

		const observation: ResponseObservation = {
			fingerprint: hash(normalized),
			grams: responseGrams(normalized),
			length: normalized.length,
			sequence,
		};
		let bestScore = 0;
		for (const previous of this.responses) {
			bestScore = Math.max(bestScore, jaccard(observation.grams, previous.grams));
		}
		this.responses.push(observation);
		while (this.responses.length > config.maxResponses) this.responses.shift();

		if (bestScore < config.responseSimilarityThreshold) {
			this.responseStreak = 0;
			return { classification: "analyzed", coverage: "assistant-visible-text-only" };
		}
		this.responseStreak++;
		if (this.responseStreak < config.responseRepeatLimit) {
			return { classification: "analyzed", coverage: "assistant-visible-text-only" };
		}
		const key = `response:${observation.fingerprint.slice(0, 16)}`;
		const finding = this.recordFinding({
			type: "response-similarity",
			key,
			score: bestScore,
			count: 1,
			sequence,
			coverage: "assistant-visible-text-only",
		});
		return {
			classification: "analyzed",
			coverage: "assistant-visible-text-only",
			finding,
		};
	}

	observeCycle(
		history: readonly ActionResultObservation[],
		sequence: number,
	): AdvisoryFinding | undefined {
		for (const period of [1, 2, 3] as const) {
			if (history.length < period * 2) continue;
			const left = history.slice(history.length - period * 2, history.length - period);
			const right = history.slice(history.length - period);
			if (!left.every((item, index) => sameEvidence(item, right[index]))) continue;
			const keyMaterial = right
				.map(
					(item) =>
						`${item.actionDigest}:${item.resultFingerprint ?? "none"}:${item.evidenceRevision}`,
				)
				.join("|");
			return this.recordFinding({
				type: "action-cycle",
				key: `cycle:${period}:${hash(keyMaterial).slice(0, 16)}`,
				period,
				count: 1,
				sequence,
			});
		}
		return undefined;
	}

	summary(): AdvisorySummary {
		let responseFindings = 0;
		let cycleFindings = 0;
		for (const finding of this.findings.values()) {
			if (finding.type === "response-similarity") responseFindings += finding.count;
			else cycleFindings += finding.count;
		}
		return {
			responseObservations: this.responses.length,
			responseFindings,
			cycleFindings,
			...(this.latestFinding ? { latestFinding: { ...this.latestFinding } } : {}),
			coverage: "assistant-visible-text-only",
		};
	}

	reset(): void {
		this.responses = [];
		this.findings.clear();
		delete this.latestFinding;
		this.responseStreak = 0;
	}

	private recordFinding(finding: AdvisoryFinding): AdvisoryFinding {
		const existing = this.findings.get(finding.key);
		const recorded = existing
			? { ...finding, count: existing.count + 1 }
			: { ...finding };
		this.findings.delete(finding.key);
		this.findings.set(finding.key, recorded);
		while (this.findings.size > 64) {
			const oldest = this.findings.keys().next().value as string | undefined;
			if (!oldest) break;
			this.findings.delete(oldest);
		}
		this.latestFinding = recorded;
		return { ...recorded };
	}
}

export function normalizeAssistantText(text: string): string {
	return text
		.normalize("NFKC")
		.toLowerCase()
		.replace(/```[\s\S]*?```/g, " <code> ")
		.replace(/`[^`]*`/g, " <inline-code> ")
		.replace(/\b[0-9a-f]{7,64}\b/g, "<hex>")
		.replace(/\b\d+(?:\.\d+)?\b/g, "<num>")
		.replace(/\/(?:[^\s'"`/]+\/)+[^\s'"`]+/g, "<path>")
		.replace(/\s+/g, " ")
		.trim();
}

export function responseGrams(text: string): Set<string> {
	const grams = new Set<string>();
	const words = text.match(/[\p{L}\p{N}_<>-]+/gu) ?? [];
	if (words.length >= 3) {
		for (let index = 0; index <= words.length - 3; index++) {
			grams.add(`w:${words[index]} ${words[index + 1]} ${words[index + 2]}`);
		}
	} else {
		for (const word of words) grams.add(`w:${word}`);
	}

	const compact = text.replace(/[\p{P}\p{S}\s]+/gu, "");
	const cjkCount = [...compact].filter((character) => /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(character)).length;
	if (cjkCount >= 4 || (words.length < 3 && compact.length >= 3)) {
		const characters = [...compact];
		for (let index = 0; index <= characters.length - 3; index++) {
			grams.add(`c:${characters.slice(index, index + 3).join("")}`);
		}
	}
	return grams;
}

export function jaccard(left: Set<string>, right: Set<string>): number {
	if (left.size === 0 || right.size === 0) return 0;
	let intersection = 0;
	for (const value of left) {
		if (right.has(value)) intersection++;
	}
	return intersection / (left.size + right.size - intersection);
}

function sameEvidence(left: ActionResultObservation, right: ActionResultObservation): boolean {
	return (
		left.actionFingerprint === right.actionFingerprint &&
		left.resultFingerprint === right.resultFingerprint &&
		left.evidenceRevision === right.evidenceRevision
	);
}

function hash(value: string): string {
	return createHash("sha256").update(value).digest("hex");
}
