// Todo语言只由当前agentcfg实例选择，保留九种原始语言资源，不扫描全局配置。
import type { TaskStatus } from "../tool/types.js";

export const I18N_NAMESPACE = "@juicesharp/rpiv-todo";

type ScopeFn = (key: string, fallback: string) => string;
import { readFileSync } from "node:fs";
import { pluginSettings } from "@agentcfg/pi-runtime/plugin-settings";
const dictionaries = new Map<string, Record<string, string>>();
const supported = new Set(["de", "en", "es", "fr", "pt-BR", "pt", "ru", "uk", "zh"]);
export const t: ScopeFn = (key, fallback) => {
  const locale = pluginSettings("pi-todo", "todo").locale ?? "en";
  if (typeof locale !== "string" || !supported.has(locale)) throw new Error("PI_TODO_LOCALE_INVALID");
  if (!dictionaries.has(locale)) dictionaries.set(locale, JSON.parse(readFileSync(new URL("../locales/" + locale + ".json", import.meta.url), "utf8")));
  const value = dictionaries.get(locale)?.[key];
  return typeof value === "string" ? value : fallback;
};

const STATUS_LABEL_PENDING = "pending";
const STATUS_LABEL_IN_PROGRESS = "in progress";
const STATUS_LABEL_COMPLETED = "completed";
const STATUS_LABEL_DELETED = "deleted";

export function formatStatusLabel(status: TaskStatus): string {
	switch (status) {
		case "pending":
			return t("status.pending", STATUS_LABEL_PENDING);
		case "in_progress":
			return t("status.in_progress", STATUS_LABEL_IN_PROGRESS);
		case "completed":
			return t("status.completed", STATUS_LABEL_COMPLETED);
		case "deleted":
			return t("status.deleted", STATUS_LABEL_DELETED);
	}
}
