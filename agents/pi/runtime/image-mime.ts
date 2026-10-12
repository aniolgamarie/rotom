// 只识别已受监管读取的Buffer，不打开路径、不导入SDK；不证明完整图像解码/CRC有效性。
const pngSignature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const ascii = (bytes, offset, text) => bytes.length >= offset + text.length
  && [...text].every((char, index) => bytes[offset + index] === char.charCodeAt(0));

function png(bytes) {
  let offset = 8, chunks = 0, imageData = false;
  while (offset < bytes.length && ++chunks <= 4096) {
    if (bytes.length - offset < 12) return false;
    const size = bytes.readUInt32BE(offset), end = offset + 12 + size;
    if (end > bytes.length) return false;
    // 类型只能是四个ASCII字母，PNG保留位（第三字符）必须为大写。
    const typeBytes = bytes.subarray(offset + 4, offset + 8);
    if ([...typeBytes].some(value => !(value >= 65 && value <= 90 || value >= 97 && value <= 122))
        || typeBytes[2] < 65 || typeBytes[2] > 90) return false;
    const type = typeBytes.toString("ascii");
    if (chunks === 1 ? type !== "IHDR" || size !== 13 : type === "IHDR") return false;
    // 扫到文件末尾，不在首个IDAT提前成功，避免漏掉晚到的动画声明。
    if (["acTL", "fcTL", "fdAT"].includes(type)) return false;
    if (type === "IDAT") imageData = true;
    if (type === "IEND") return size === 0 && imageData && end === bytes.length;
    offset = end;
  }
  return false;
}

function bmp(bytes) {
  if (bytes.length < 26) return false;
  const size = bytes.readUInt32LE(2), pixelOffset = bytes.readUInt32LE(10), header = bytes.readUInt32LE(14);
  if (![12, 40, 52, 56, 108, 124].includes(header) || bytes.length < 14 + header
      || pixelOffset < 14 + header || pixelOffset > bytes.length || size !== 0 && (size > bytes.length || pixelOffset >= size)) return false;
  const planeOffset = header === 12 ? 22 : 26;
  return bytes.readUInt16LE(planeOffset) === 1 && [1, 4, 8, 16, 24, 32].includes(bytes.readUInt16LE(planeOffset + 2));
}

export function detectImageMimeType(bytes) {
  if (!Buffer.isBuffer(bytes)) return null;
  if (bytes.length >= 4 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) {
    return bytes[3] === 247 ? null : "image/jpeg";
  }
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(pngSignature)) return png(bytes) ? "image/png" : null;
  if (ascii(bytes, 0, "GIF87a") || ascii(bytes, 0, "GIF89a")) return "image/gif";
  if (ascii(bytes, 0, "RIFF") && ascii(bytes, 8, "WEBP")) return "image/webp";
  if (ascii(bytes, 0, "BM") && bmp(bytes)) return "image/bmp";
  return null;
}
