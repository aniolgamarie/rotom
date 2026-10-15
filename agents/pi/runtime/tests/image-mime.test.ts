import assert from "node:assert/strict";
import { test } from "node:test";
import { detectImageMimeType } from "../image-mime.ts";

const signatures = [
  ["image/png", [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]],
  ["image/jpeg", [0xff, 0xd8, 0xff]],
  ["image/gif", [0x47, 0x49, 0x46, 0x38, 0x37, 0x61]],
  ["image/gif", [0x47, 0x49, 0x46, 0x38, 0x39, 0x61]],
  ["image/webp", [0x52, 0x49, 0x46, 0x46, 0x18, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50]],
];

for (const [mime, signature] of signatures) {
  test(`recognizes ${mime} signature without decoding content`, () => {
    assert.equal(detectImageMimeType(Uint8Array.from(signature)), mime);
    assert.equal(detectImageMimeType(Buffer.from([...signature, 0, 1, 2])), mime);
  });
  test(`rejects every truncated ${mime} header`, () => {
    for (let length = 0; length < signature.length; length++) {
      assert.equal(detectImageMimeType(Uint8Array.from(signature.slice(0, length))), null);
    }
  });
}

test("rejects incorrect signatures and unsupported formats", () => {
  for (const value of [[], [0xff, 0xd8, 0], [0x89, 0x50, 0x4e, 0x47],
    Buffer.from("GIF88a"), Buffer.from("RIFFxxxxWAVE"), Buffer.from("RIFXxxxxWEBP"),
    Buffer.from("RIFFxxxxWEBx"), Buffer.from("BMbitmap"), Buffer.from("<svg></svg>"), Buffer.from("plain text")]) {
    assert.equal(detectImageMimeType(Uint8Array.from(value)), null);
  }
});

test("uses only the supplied byte view without modifying it", () => {
  for (const [mime, signature] of signatures) {
    const storage = Uint8Array.from([0, ...signature, 0]), before = storage.slice();
    assert.equal(detectImageMimeType(storage.subarray(1, 1 + signature.length)), mime);
    assert.equal(detectImageMimeType(storage.subarray(1, signature.length)), null);
    assert.equal(detectImageMimeType(storage), null);
    assert.deepEqual(storage, before);
  }
});
