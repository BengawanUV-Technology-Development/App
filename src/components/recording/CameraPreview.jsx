import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost, webSocketUrl } from "../../services/api";
import { containRect, normalizedBoxToCanvas, parseVisionEnvelope } from "../../services/visionPacket";

function CameraPreview() {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const bitmapRef = useRef(null);
  const reconnectRef = useRef(null);
  const [camera, setCamera] = useState({ camera_status: "STARTING", camera_error: null });
  const [header, setHeader] = useState(null);
  const [socketState, setSocketState] = useState("CONNECTING");
  const [isLoading, setIsLoading] = useState(false);
  const [overlayEnabled, setOverlayEnabled] = useState(true);
  const [minimumConfidence, setMinimumConfidence] = useState(0.45);
  const [classFilter, setClassFilter] = useState("");
  const [connectionNonce, setConnectionNonce] = useState(0);
  const [sourceError, setSourceError] = useState(null);

  const previewSource = camera.preview_source || "digital";
  const analogAvailable = camera.preview_analog_available === true;

  const filteredDetections = useCallback(() => {
    if (previewSource === "analog" || !overlayEnabled || !Array.isArray(header?.detections)) return [];
    const wanted = classFilter.trim().toLowerCase();
    return header.detections.filter((item) => (
      Number(item.confidence || 0) >= minimumConfidence
      && (!wanted || String(item.class || "").toLowerCase().includes(wanted))
    ));
  }, [classFilter, header, minimumConfidence, overlayEnabled, previewSource]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    const bitmap = bitmapRef.current;
    if (!canvas || !container) return;
    const rect = container.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * ratio));
    canvas.height = Math.max(1, Math.round(rect.height * ratio));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = "#02070b";
    context.fillRect(0, 0, rect.width, rect.height);
    if (!bitmap) return;
    const imageRect = containRect(rect.width, rect.height, bitmap.width, bitmap.height);
    context.drawImage(bitmap, imageRect.x, imageRect.y, imageRect.width, imageRect.height);
    context.lineWidth = 2;
    context.font = "600 12px ui-monospace, monospace";
    filteredDetections().forEach((detection) => {
      const box = detection.bbox_normalized_xyxy;
      if (!Array.isArray(box) || box.length !== 4) return;
      const canvasBox = normalizedBoxToCanvas(box, imageRect);
      if (!canvasBox) return;
      const { left, top, width, height } = canvasBox;
      context.strokeStyle = "#22d3ee";
      context.strokeRect(left, top, width, height);
      const label = `${detection.class || "object"} ${(Number(detection.confidence || 0) * 100).toFixed(0)}%`;
      const labelWidth = context.measureText(label).width + 10;
      context.fillStyle = "rgba(3, 105, 161, .9)";
      context.fillRect(left, Math.max(imageRect.y, top - 20), labelWidth, 20);
      context.fillStyle = "#fff";
      context.fillText(label, left + 5, Math.max(imageRect.y + 14, top - 6));
    });
  }, [filteredDetections]);

  useEffect(() => {
    const observer = new ResizeObserver(draw);
    if (containerRef.current) observer.observe(containerRef.current);
    draw();
    return () => observer.disconnect();
  }, [draw]);

  useEffect(() => {
    let stopped = false;
    let socket;
    const connect = () => {
      if (stopped) return;
      setSocketState("CONNECTING");
      socket = new WebSocket(webSocketUrl("/api/v1/vision/ws"));
      socket.binaryType = "arraybuffer";
      socket.onopen = () => setSocketState("CONNECTED");
      socket.onmessage = async (event) => {
        const packetReceivedAt = performance.now();
        try {
          const packet = parseVisionEnvelope(event.data);
          const bitmap = await createImageBitmap(new Blob([packet.jpeg], { type: "image/jpeg" }));
          if (stopped) { bitmap.close(); return; }
          bitmapRef.current?.close();
          bitmapRef.current = bitmap;
          setHeader(packet.header);
          const renderedFrame = packet.header;
          requestAnimationFrame(() => {
            apiPost("/api/v1/vision/metrics", {
              schema_version: renderedFrame.schema_version,
              mission_id: renderedFrame.mission_id,
              capture_epoch: renderedFrame.capture_epoch,
              frame_id: renderedFrame.frame_id,
              camera_id: renderedFrame.camera_id,
              receive_to_render_ms: Math.max(0, performance.now() - packetReceivedAt),
            }).catch(() => {});
          });
        } catch (error) {
          setSocketState(`PACKET_ERROR: ${String(error)}`);
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        setSocketState("RECONNECTING");
        reconnectRef.current = setTimeout(connect, 1500);
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(reconnectRef.current);
      socket?.close();
      bitmapRef.current?.close();
      bitmapRef.current = null;
    };
  }, [connectionNonce]);

  useEffect(draw, [draw, header]);

  const refresh = useCallback(async () => {
    const result = await apiGet("/api/v1/camera/status");
    if (result.ok) setCamera(result.data);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  }, [refresh]);

  const switchPreview = async (source) => {
    setIsLoading(true);
    setSourceError(null);
    const result = await apiPost("/api/v1/camera/preview-source", { source });
    if (!result.ok) {
      setSourceError(result.error || "Gagal mengubah sumber preview");
    } else {
      await refresh();
    }
    setIsLoading(false);
  };

  const restart = async () => {
    setIsLoading(true);
    if (!camera.recording) await apiPost("/api/v1/camera/stop");
    await apiPost("/api/v1/camera/start");
    setConnectionNonce((value) => value + 1);
    await refresh();
    setIsLoading(false);
  };

  const detectionState = header?.detection_state || "WAITING_FOR_FRAME";
  const streamState = header?.stream_state || camera.camera_status || socketState;

  return (
    <div className="vision-frame live-camera-frame" ref={containerRef}>
      <canvas ref={canvasRef} className="camera-preview-canvas" aria-label="Synchronized Arducam preview" />
      {!bitmapRef.current ? (
        <div className="camera-preview-empty">
          <strong>{streamState}</strong>
          <span>{camera.camera_error || `Vision WebSocket ${socketState.toLowerCase()}`}</span>
        </div>
      ) : null}
      {sourceError ? (
        <div className="camera-preview-source-error">{sourceError}</div>
      ) : null}
      {previewSource === "analog" ? (
        <div className="camera-preview-ai-status">ANALOG FPV ACTIVE · AI DETECTION CONTINUES ON DIGITAL</div>
      ) : null}
      <div className="vision-frame-metrics">
        <span>CAM {header?.camera_id || "arducam"}</span>
        <span>STREAM {streamState}</span>
        <span>SRC {previewSource.toUpperCase()}</span>
        <span>DETECTOR {header?.detector_state || "UNKNOWN"}</span>
        <span>{detectionState}</span>
        <span>{Number(header?.fps || 0).toFixed(1)} FPS</span>
        <span>{Number(header?.ground_queue_latency_ms || 0).toFixed(0)} ms</span>
      </div>
      <div className="vision-filter-controls">
        <label><input type="checkbox" checked={overlayEnabled} onChange={(event) => setOverlayEnabled(event.target.checked)} /> Overlay</label>
        <label>Confidence <input type="range" min="0" max="1" step="0.05" value={minimumConfidence} onChange={(event) => setMinimumConfidence(Number(event.target.value))} /></label>
        <input value={classFilter} onChange={(event) => setClassFilter(event.target.value)} placeholder="class filter" aria-label="Detection class filter" />
      </div>
      <div className="camera-preview-controls">
        <div className="camera-preview-sources">
          <button
            type="button"
            className={previewSource === "digital" ? "is-selected" : ""}
            onClick={() => switchPreview("digital")}
            disabled={isLoading || previewSource === "digital"}
          >
            DIGITAL
          </button>
          <button
            type="button"
            className={previewSource === "analog" ? "is-selected" : ""}
            onClick={() => switchPreview("analog")}
            disabled={isLoading || !analogAvailable || previewSource === "analog"}
            title={analogAvailable ? "Switch to EasyCAP analog video" : "EasyCAP hardware is not connected"}
          >
            ANALOG
          </button>
        </div>
        <span className={streamState === "RUNNING" ? "is-live" : ""}>FRAME {header?.frame_id ?? "-"} · EPOCH {header?.capture_epoch ?? "-"}</span>
        <div><button type="button" onClick={restart} disabled={isLoading}>RECONNECT</button></div>
      </div>
    </div>
  );
}

export default CameraPreview;
