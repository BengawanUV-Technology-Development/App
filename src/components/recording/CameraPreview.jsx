import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE, apiGet, apiPost } from "../../services/api";

function CameraPreview() {
  const [camera, setCamera] = useState({ camera_status: "STARTING", camera_error: null });
  const [isLoading, setIsLoading] = useState(false);
  const [streamNonce, setStreamNonce] = useState(0);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [streamError, setStreamError] = useState(null);

  const previewUrl = useMemo(
    () => `${API_BASE}/api/v1/camera/preview?session=${streamNonce}`,
    [streamNonce],
  );

  const refresh = useCallback(async () => {
    const result = await apiGet("/api/v1/camera/status");
    if (result.ok) {
      setCamera(result.data);
    } else {
      setCamera((previous) => ({
        ...previous,
        camera_status: "OFFLINE",
        camera_error: result.error,
      }));
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  }, [refresh]);

  const restart = async () => {
    setIsLoading(true);
    setStreamError(null);
    await apiPost("/api/v1/camera/stop");
    const result = await apiPost("/api/v1/camera/start");
    if (!result.ok) setStreamError(result.error || "Kamera gagal dimulai");
    setImageLoaded(false);
    setStreamNonce((value) => value + 1);
    await refresh();
    setIsLoading(false);
  };

  const streamState = imageLoaded ? "RUNNING" : camera.camera_status || "STOPPED";

  return (
    <div className="vision-frame live-camera-frame">
      <img
        key={streamNonce}
        src={previewUrl}
        className={`camera-preview-image ${imageLoaded ? "is-live" : ""}`}
        alt="Live Arducam preview"
        onLoad={() => {
          setImageLoaded(true);
          setStreamError(null);
        }}
        onError={() => {
          setImageLoaded(false);
          setStreamError("Preview camera tidak dapat dibuka");
        }}
      />
      {!imageLoaded ? (
        <div className="camera-preview-empty">
          <strong>{streamState}</strong>
          <span>{streamError || camera.camera_error || "Menunggu frame H.264/RTP dari Jetson"}</span>
        </div>
      ) : null}
      <div className="vision-frame-metrics">
        <span>CAM ARDUCAM</span>
        <span>STREAM {streamState}</span>
        <span>{Number(camera.width || 0)}×{Number(camera.height || 0)}</span>
        <span>{Number(camera.fps || camera.expected_fps || 0).toFixed(1)} FPS</span>
        <span>FRAMES {camera.frame_count || 0}</span>
      </div>
      <div className="camera-preview-controls">
        <span className={streamState === "RUNNING" ? "is-live" : ""}>
          {camera.transport || "H264/RTP/UDP"} · UDP {camera.stream_port || "-"}
        </span>
        <div><button type="button" onClick={restart} disabled={isLoading}>RECONNECT</button></div>
      </div>
    </div>
  );
}

export default CameraPreview;
