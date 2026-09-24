// 直接导入明确文件，避免测试发现器为绝对 glob 遍历真实文件系统根。
import { pathToFileURL } from "node:url";
for (const file of process.argv.slice(2)) await import(pathToFileURL(file).href);
