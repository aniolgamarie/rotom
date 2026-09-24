import path from "node:path";
import picomatch from "picomatch";
const FILE_TOOLS = new Set(["read", "edit", "write"]);
export function extractTarget(event, cwd) {
    if (("isError" in event && event.isError) || !FILE_TOOLS.has(event.toolName))
        return undefined;
    const rawPath = event.input.path;
    if (typeof rawPath !== "string" || rawPath.trim().length === 0)
        return undefined;
    const withoutAt = rawPath.startsWith("@") ? rawPath.slice(1) : rawPath;
    const absolutePath = path.resolve(cwd, withoutAt);
    const relativePath = path.relative(cwd, absolutePath);
    if (relativePath.length === 0 ||
        relativePath === ".." ||
        relativePath.startsWith(`..${path.sep}`) ||
        path.isAbsolute(relativePath)) {
        return undefined;
    }
    return toPosixPath(relativePath);
}
export function ruleMatchesTarget(rule, target) {
    if (!rule.paths)
        return false;
    const patterns = rule.paths.map(normalizePattern);
    return picomatch.isMatch(target, patterns, { dot: true });
}
export function ruleMatchesToolCallEvent(rule, toolName) {
    return !rule.events || rule.events.tool_call.some((name) => name === toolName);
}
function normalizePattern(pattern) {
    return toPosixPath(pattern).replace(/^\.\//, "");
}
function toPosixPath(value) {
    return value.split(path.sep).join("/");
}
//# sourceMappingURL=matching.js.map