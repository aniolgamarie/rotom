import test from "node:test";
import assert from "node:assert/strict";
import { detectImageMimeType } from "../image-mime.ts";

const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
function chunk(type, data = Buffer.alloc(0)) {
  const result = Buffer.alloc(12 + data.length);
  result.writeUInt32BE(data.length); result.write(type, 4, 4, "ascii"); data.copy(result, 8);
  // CRC不由MIME识别器解码校验；完整性/图像解码是其它层。
  return result;
}
function png(extra = []) {
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(1); ihdr.writeUInt32BE(1, 4); ihdr[8] = 8; ihdr[9] = 2;
  return Buffer.concat([signature, chunk("IHDR", ihdr), ...extra, chunk("IDAT", Buffer.from([1])), chunk("IEND")]);
}
function bmp() {
  const bytes = Buffer.alloc(58); bytes.write("BM"); bytes.writeUInt32LE(58, 2); bytes.writeUInt32LE(54, 10);
  bytes.writeUInt32LE(40, 14); bytes.writeInt32LE(1, 18); bytes.writeInt32LE(1, 22);
  bytes.writeUInt16LE(1, 26); bytes.writeUInt16LE(24, 28); return bytes;
}
function webp() { const bytes = Buffer.alloc(16); bytes.write("RIFF"); bytes.writeUInt32LE(8, 4); bytes.write("WEBP", 8); return bytes; }

for (const [name, bytes, mime] of [["jpeg", Buffer.from([0xff, 0xd8, 0xff, 0xe0]), "image/jpeg"], ["png", png(), "image/png"],
  ["gif87", Buffer.from("GIF87a"), "image/gif"], ["gif89", Buffer.from("GIF89a"), "image/gif"], ["webp", webp(), "image/webp"], ["bmp", bmp(), "image/bmp"]]) {
  test("recognizes supported " + name + " bytes without changing input", () => {
    const before = Buffer.from(bytes); assert.equal(detectImageMimeType(bytes), mime); assert.deepEqual(bytes, before);
  });
}
for (const value of [null, undefined, "/private/path.png", {}, [], new Uint8Array([0xff, 0xd8, 0xff, 0xe0]),
  Buffer.alloc(0), Buffer.from("business text"), Buffer.from("/private/path.png"), Buffer.from("GIF90a"),
  Buffer.from([0xff, 0x4f, 0xff, 0x51]), Buffer.from([0, 0, 0, 12, 106, 80, 32, 32, 13, 10, 135, 10]), Buffer.from([0xff, 0xd8, 0xff, 0xf7])]) {
  test("unknown/nonbuffer/unsupported input returns null", () => assert.equal(detectImageMimeType(value), null));
}

test("every truncated PNG prefix is rejected", () => {
  const bytes = png();
  for (let length = 0; length < bytes.length; length++) assert.equal(detectImageMimeType(bytes.subarray(0, length)), null, String(length));
});

test("animated PNG remains rejected before or after image data", () => {
  assert.equal(detectImageMimeType(png([chunk("acTL", Buffer.alloc(8))])), null);
  const bytes = png();
  assert.equal(detectImageMimeType(Buffer.concat([bytes.subarray(0, bytes.length - 12), chunk("acTL", Buffer.alloc(8)), chunk("IEND")])), null);
});

test("PNG bad chunk lengths and nonalphabetic/reserved type are rejected", () => {
  const huge = png(); huge.writeUInt32BE(0xffffffff, 8);
  assert.equal(detectImageMimeType(huge), null);
  assert.equal(detectImageMimeType(png([chunk("t3XT")])), null);
  assert.equal(detectImageMimeType(png([chunk("texT")])), null);
});

test("PNG rejects wrong initial header, missing image data, duplicate header, invalid end", () => {
  assert.equal(detectImageMimeType(Buffer.concat([signature, chunk("IEND")])), null);
  const header = png().subarray(8, 33);
  assert.equal(detectImageMimeType(Buffer.concat([signature, header, chunk("IEND")])), null);
  assert.equal(detectImageMimeType(png([header])), null);
  const bytes = png();
  assert.equal(detectImageMimeType(Buffer.concat([bytes.subarray(0, bytes.length - 12), chunk("IEND", Buffer.from([1]))])), null);
  assert.equal(detectImageMimeType(Buffer.concat([bytes, Buffer.from([1])])), null);
});

test("PNG ancillary traversal is bounded even for zero-length chunks", () => {
  assert.equal(detectImageMimeType(png([chunk("tEXt"), chunk("pHYs", Buffer.alloc(9))])), "image/png");
  assert.equal(detectImageMimeType(png(Array.from({ length: 4096 }, () => chunk("tEXt")))), null);
});

test("other signatures do not accept truncated or confused headers", () => {
  assert.equal(detectImageMimeType(Buffer.from([0xff, 0xd8, 0xff])), null);
  assert.equal(detectImageMimeType(Buffer.from("RIFFxxxxWAVExxxx")), null);
  assert.equal(detectImageMimeType(webp().subarray(0, 11)), null);
  assert.equal(detectImageMimeType(Buffer.from("BM business text")), null);
  const bytes = bmp(); bytes.writeUInt16LE(2, 26);
  assert.equal(detectImageMimeType(bytes), null);
  assert.equal(detectImageMimeType(Buffer.from("GIF89a").map(value => value | 0x80)), null);
});
