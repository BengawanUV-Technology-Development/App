import { useCallback, useEffect, useState } from "react";
import { API_BASE, apiGet, apiPost } from "../../services/api";

function CameraPreview() {
  const [camera, setCamera] = useState({ camera_status: "STARTING", camera_error: null });
  const [streamKey, setStreamKey] = useState(0);
  const [isLoading, setIsLoading] = useState(false);

  const refresh = useCallback(async () => {
    const result = await apiGet("/api/v1/camera/status");
    if (result.ok) setCamera(result.data);
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  }, [refresh]);

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

  return (
    <div className="vision-frame live-camera-frame">
      <img
        key={streamKey}
        className={camera.camera_status === "LIVE" ? "camera-preview-image is-live" : "camera-preview-image"}
        src={`${API_BASE}/api/v1/camera/preview?stream=${streamKey}`}
        alt="Live Jetson Arducam preview"
      />
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
          {camera.camera_status || "OFFLINE"}
          {camera.width ? ` · ${camera.width}×${camera.height} @ ${Number(camera.fps || 0).toFixed(1)} FPS` : ""}
        </span>
        <div>
          <button type="button" onClick={restart} disabled={isLoading}>RECONNECT</button>
          <button type="button" onClick={stop} disabled={isLoading || camera.recording}>RELEASE</button>
        </div>
      </div>
    </div>
  );
}

export default CameraPreview;
