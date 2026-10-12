import { constants, closeSync, fstatSync, lstatSync, openSync, readFileSync, readSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";
function failure(code, exitCode = 4) {
    const error = new Error(code);
    error.exitCode = exitCode;
    throw error;
}
function readPrivateBytes(path, maxBytes, optional) {
    if (maxBytes !== undefined && (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 16 * 1024 * 1024)) failure("pi-private-size");
    const parent = lstatSync(dirname(path));
    if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) failure("pi-private-directory");
    let fd;
    try {
        fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    } catch (error) {
        if (optional && error.code === "ENOENT") return undefined;
        throw error;
    }
    try {
        const info = fstatSync(fd);
        if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600) failure("pi-private-file");
        if (maxBytes === undefined) return readFileSync(fd);
        if (info.size > maxBytes) failure("pi-private-size");
        const bytes = Buffer.alloc(maxBytes + 1);
        let offset = 0;
        while(offset < bytes.length){
            const count = readSync(fd, bytes, offset, bytes.length - offset, null);
            if (!count) break;
            offset += count;
        }
        if (offset > maxBytes) failure("pi-private-size");
        return bytes.subarray(0, offset);
    } finally{
        closeSync(fd);
    }
}
export function privateBytes(path, maxBytes) {
    return readPrivateBytes(path, maxBytes, false);
}
export function optionalPrivateBytes(path, maxBytes) {
    return readPrivateBytes(path, maxBytes, true);
}
export function privateFile(path) {
    return privateBytes(path).toString("utf8");
}
export function writePrivate(path, text) {
    const parent = lstatSync(dirname(path));
    if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) failure("pi-private-directory");
    const temporary = path + "." + randomUUID();
    try {
        writeFileSync(temporary, text, {
            mode: 0o600,
            flag: "wx"
        });
        renameSync(temporary, path);
    } finally{
        try {
            unlinkSync(temporary);
        } catch (error) {
            if (error.code !== "ENOENT") throw error;
        }
    }
}
