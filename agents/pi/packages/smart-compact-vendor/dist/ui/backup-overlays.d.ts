import { type ExtensionCommandContext } from "@earendil-works/pi-coding-agent";
import type { BackupEntry } from "../utils/backups.ts";
/** Picker for `/smart-compact restore` — list backups, return the chosen path. */
export declare function showRestorePicker(ctx: ExtensionCommandContext, backups: BackupEntry[]): Promise<string | null>;
/** Scrollable viewer for a restored backup's content. */
export declare function showBackupViewer(ctx: ExtensionCommandContext, content: string, file: string): Promise<void>;
/** Action menu after a backup is picked: view its content or restore it. */
export declare function showRestoreAction(ctx: ExtensionCommandContext, backupPath: string): Promise<"view" | "restore" | null>;
//# sourceMappingURL=backup-overlays.d.ts.map