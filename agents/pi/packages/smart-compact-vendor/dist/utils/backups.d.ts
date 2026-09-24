import type { PreparedConversationBackup } from "../types.ts";
export declare function prepareConversationBackup(source: string | (() => string), sessionId: string, metadata?: {
    branchLeafId?: string;
    contextTokens?: number;
}): PreparedConversationBackup | null;
/** Materialize and commit the scrubbed payload only after native confirmation. */
export declare function commitPreparedConversationBackup(prepared: PreparedConversationBackup): Promise<string | null>;
export interface BackupEntry {
    path: string;
    sessionId: string;
    date: string;
    sizeBytes: number;
}
export declare function listBackups(limit?: number): BackupEntry[];
export interface ConversationBackup {
    content: string;
    branchLeafId?: string;
    contextTokens?: number;
}
export declare function readConversationBackup(file: string): ConversationBackup | null;
export declare function readBackupContent(file: string): string | null;
export declare function buildRestoreMessage(content: string, source: string): {
    customType: string;
    content: string;
    display: boolean;
    details: {
        source: string;
        restoredAt: number;
    };
};
//# sourceMappingURL=backups.d.ts.map