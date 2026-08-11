import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiGet, apiPost } from "../../services/api";

const EMPTY_OVERLAY = { stale: true, detections: [] };

function overlayBoxStyle(detection, width, height) {
  const bbox = detection?.bbox_network;
  if (!Array.isArray(bbox) || bbox.length !== 4 || width <= 0 || height <= 0) return null;

  const [x1, y1, x2, y2] = bbox.map(Number);
  if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return null;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const left = clamp((x1 / width) * 100, 0, 100);
  const top = clamp((y1 / height) * 100, 0, 100);
  const right = clamp((x2 / width) * 100, 0, 100);
  const bottom = clamp((y2 / height) * 100, 0, 100);

  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${Math.max(0, right - left)}%`,
    height: `${Math.max(0, bottom - top)}%`,
  };
}

function CameraPreview() {
  const [camera, setCamera] = useState({ camera_status: "STARTING", camera_error: null });
  const [overlay, setOverlay] = useState(EMPTY_OVERLAY);
  const [streamKey, setStreamKey] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [sourceError, setSourceError] = useState(null);

  const refresh = useCallback(async () => {
    const result = await apiGet("/api/v1/camera/status");
    if (result.ok) setCamera(result.data);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  }, [refresh]);

  const refreshOverlay = useCallback(async () => {
    const result = await apiGet("/api/v1/detection/overlay");
    if (result.ok) {
      setOverlay(result.data);
    } else {
      setOverlay((current) => ({ ...current, ...EMPTY_OVERLAY }));
    }
  }, []);

  useEffect(() => {
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await refreshOverlay();
      } finally {
        inFlight = false;
      }
    };
    poll();
    const interval = setInterval(poll, 250);
    return () => clearInterval(interval);
  }, [refreshOverlay]);

  const restart = async () => {
    setIsLoading(true);
    if (!camera.recording) {
      await apiPost("/api/v1/camera/stop");
    }
    await apiPost("/api/v1/camera/start");
    setStreamKey((value) => value + 1);
    await refresh();
    setIsLoading(false);
  };

  const stop = async () => {
    setIsLoading(true);
    await apiPost("/api/v1/camera/stop");
    await refresh();
    setIsLoading(false);
  };

  const switchPreview = async (source) => {
    setIsLoading(true);
    setSourceError(null);
    const result = await apiPost("/api/v1/camera/preview-source", { source });
    if (result.ok) {
      setCamera(result.data);
    } else {
      setSourceError(result.error || "Preview source switch failed");
      if (result.data) setCamera(result.data);
    }
    setIsLoading(false);
  };

  const overlayWidth = Number(overlay.network_width || camera.width || 0);
  const overlayHeight = Number(overlay.network_height || camera.height || 0);
  const previewSource = camera.preview_source || camera.preview?.source || "digital";
  const analogAvailable = Boolean(
    camera.preview_analog_available ?? camera.preview?.analog_available
  );
  const detections = overlay.stale || camera.camera_status !== "LIVE" || previewSource !== "digital"
    ? []
    : Array.isArray(overlay.detections)
      ? overlay.detections
      : [];

  return (
    <div className="vision-frame live-camera-frame">
      <img
        key={streamKey}
        className={camera.camera_status === "LIVE" ? "camera-preview-image is-live" : "camera-preview-image"}
        src={`${API_BASE}/api/v1/camera/preview?stream=${streamKey}`}
        alt="Live Jetson Arducam preview"
      />
      <div className="camera-detection-overlay" aria-label="Live object detections">
        {detections.map((detection, index) => {
          const style = overlayBoxStyle(detection, overlayWidth, overlayHeight);
          if (!style) return null;
          return (
            <div
              className="camera-detection-box"
              key={`${overlay.frame_id ?? "frame"}-${index}`}
              style={style}
            >
              <span>{detection.class || "object"}</span>
              <strong>{`${(Number(detection.confidence || 0) * 100).toFixed(0)}%`}</strong>
            </div>
          );
        })}
      </div>
      {camera.camera_status !== "LIVE" ? (
        <div className="camera-preview-empty">
          <strong>{camera.camera_status || "CONNECTING"}</strong>
          <span>
            {camera.camera_error ||
              (camera.camera_source === "jetson_udp"
                ? `Waiting for H.264/RTP on UDP :${camera.stream_port ?? "-"}`
                : `Opening camera index ${camera.camera_index ?? "-"}`)}
          </span>
        </div>
      ) : null}
      <div className="vision-reticle" />
      <div className="camera-preview-controls">
        <span className={camera.camera_status === "LIVE" ? "is-live" : ""}>
          {(camera.camera_status || "OFFLINE") + ` · ${previewSource.toUpperCase()}`}
          {camera.width ? ` · ${camera.width}×${camera.height} @ ${Number(camera.fps || 0).toFixed(1)} FPS` : ""}
        </span>
        <div className="camera-preview-source-controls" aria-label="Global preview source">
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
            title={analogAvailable ? "Show the EasyCAP feed selected by the pilot" : "EasyCAP is not configured on Jetson"}
          >
            ANALOG
          </button>
          <button type="button" onClick={restart} disabled={isLoading}>RECONNECT</button>
          <button
            type="button"
            onClick={stop}
            disabled={isLoading || camera.recording === true || camera.status === "REMOTE_UNKNOWN"}
          >
            RELEASE
          </button>
        </div>
      </div>
      {sourceError ? <div className="camera-preview-source-error">{sourceError}</div> : null}
      {previewSource === "analog" ? (
        <div className="camera-preview-ai-status">AI: B0249 ACTIVE · OVERLAY HIDDEN ON ANALOG</div>
      ) : null}
    </div>
  );
}

export default CameraPreview;
