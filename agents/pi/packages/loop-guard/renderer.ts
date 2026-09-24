import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import type { Component } from "@earendil-works/pi-tui";

import { LOOP_GUARD_CHECKPOINT_TYPE } from "./persistence.ts";
import {
	buildMalformedTerminalReport,
	buildTerminalReport,
	terminalCheckpointLooksEligible,
} from "./terminal-report.ts";

class TerminalReportComponent implements Component {
	private readonly lines: string[];

	constructor(lines: string[]) {
		this.lines = lines;
	}

	invalidate(): void {}

	render(width: number): string[] {
		const boundedWidth = Math.max(1, Math.floor(width));
		return this.lines.flatMap((line) => wrapLine(line, boundedWidth));
	}
}

export function registerTerminalCheckpointRenderer(pi: ExtensionAPI): void {
	pi.registerEntryRenderer(LOOP_GUARD_CHECKPOINT_TYPE, (entry, { expanded }) => {
		const report = buildTerminalReport(entry.data);
		if (!report) {
			if (!terminalCheckpointLooksEligible(entry.data)) return undefined;
			return new TerminalReportComponent(buildMalformedTerminalReport().expandedLines);
		}
		return new TerminalReportComponent(expanded ? report.expandedLines : report.collapsedLines);
	});
}

function wrapLine(line: string, width: number): string[] {
	if (line === "" || line.length <= width) return [line];
	const lines: string[] = [];
	for (let offset = 0; offset < line.length; offset += width) {
		lines.push(line.slice(offset, offset + width));
	}
	return lines;
}
