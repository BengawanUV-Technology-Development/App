export function parseVisionEnvelope(buffer) {
  const view = new DataView(buffer);
  if (view.byteLength < 4) throw new Error("Truncated vision packet");
  const headerLength = view.getUint32(0, false);
  if (headerLength > 1024 * 1024 || 4 + headerLength >= view.byteLength) {
    throw new Error("Invalid vision header length");
  }
  const bytes = new Uint8Array(buffer);
  const header = JSON.parse(new TextDecoder().decode(bytes.slice(4, 4 + headerLength)));
  return { header, jpeg: bytes.slice(4 + headerLength) };
}

export function containRect(viewWidth, viewHeight, imageWidth, imageHeight) {
  if (![viewWidth, viewHeight, imageWidth, imageHeight].every((value) => Number(value) > 0)) {
    throw new Error("Canvas and image dimensions must be positive");
  }
  const scale = Math.min(viewWidth / imageWidth, viewHeight / imageHeight);
  const width = imageWidth * scale;
  const height = imageHeight * scale;
  return { x: (viewWidth - width) / 2, y: (viewHeight - height) / 2, width, height };
}

export function normalizedBoxToCanvas(box, rect) {
  if (!Array.isArray(box) || box.length !== 4) return null;
  const [x1, y1, x2, y2] = box.map(Number);
  if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return null;
  const clamp = (value) => Math.max(0, Math.min(1, value));
  const left = rect.x + clamp(x1) * rect.width;
  const top = rect.y + clamp(y1) * rect.height;
  return {
    left,
    top,
    width: (clamp(x2) - clamp(x1)) * rect.width,
    height: (clamp(y2) - clamp(y1)) * rect.height,
  };
}
