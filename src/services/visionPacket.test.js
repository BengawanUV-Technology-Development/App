import assert from "node:assert/strict";
import test from "node:test";
import { containRect, normalizedBoxToCanvas, parseVisionEnvelope } from "./visionPacket.js";

test("binary packet keeps exact JSON header and JPEG bytes", () => {
  const header = new TextEncoder().encode(JSON.stringify({ frame_id: 7 }));
  const jpeg = Uint8Array.from([0xff, 0xd8, 1, 0xff, 0xd9]);
  const packet = new Uint8Array(4 + header.length + jpeg.length);
  new DataView(packet.buffer).setUint32(0, header.length, false);
  packet.set(header, 4);
  packet.set(jpeg, 4 + header.length);
  const decoded = parseVisionEnvelope(packet.buffer);
  assert.equal(decoded.header.frame_id, 7);
  assert.deepEqual(decoded.jpeg, jpeg);
});

test("normalized bbox stays on image under letterbox and resize", () => {
  const wide = normalizedBoxToCanvas([0.25, 0.25, 0.75, 0.75], containRect(1000, 1000, 960, 540));
  assert.ok(Math.abs(wide.left - 250) < 1e-9);
  assert.ok(Math.abs(wide.top - 359.375) < 1e-9);
  assert.ok(Math.abs(wide.width - 500) < 1e-9);
  assert.ok(Math.abs(wide.height - 281.25) < 1e-9);
  const full = normalizedBoxToCanvas([0, 0, 1, 1], containRect(1920, 1080, 960, 540));
  assert.deepEqual(full, { left: 0, top: 0, width: 1920, height: 1080 });
});

test("invalid bbox is rejected", () => {
  assert.equal(normalizedBoxToCanvas([0.8, 0.1, 0.2, 0.9], containRect(100, 100, 100, 100)), null);
});
