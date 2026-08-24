import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE, apiGet, apiPost } from "../../services/api";

const initialRecorder = {
  recording: false,
  status: "IDLE",
  session_id: null,
  frame_count: 0,
  duration_seconds: 0,
  error: null,
};

function sourceLabel(source) {
  return source === "analog" ? "ANALOG" : "CSI / ARDUCAM";
}

function CameraPreview() {
  const [camera, setCamera] = useState({ camera_status: "STOPPED", camera_error: null });
  const [recorder, setRecorder] = useState(initialRecorder);
  const [source, setSource] = useState("csi");
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [busyAction, setBusyAction] = useState(null);
  const [streamNonce, setStreamNonce] = useState(0);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [streamError, setStreamError] = useState(null);
  const initializedRef = useRef(false);

  const previewUrl = useMemo(
    () => `${API_BASE}/api/v1/camera/preview?session=${streamNonce}`,
    [streamNonce],
  );

  const refresh = useCallback(async () => {
    const [cameraResult, recorderResult, sourceResult] = await Promise.all([
      apiGet("/api/v1/camera/status"),
      apiGet("/api/v1/recordings/status"),
      apiGet("/api/v1/camera/source"),
    ]);

    if (cameraResult.ok) {
      setCamera(cameraResult.data);
      if (!initializedRef.current) {
        setIsOpen(cameraResult.data.camera_status !== "STOPPED");
      }
    } else {
      setCamera((previous) => ({
        ...previous,
        camera_status: "OFFLINE",
        camera_error: cameraResult.error,
      }));
    }

    if (recorderResult.ok) {
      setRecorder(recorderResult.data);
      if (recorderResult.data.recording) setIsOpen(true);
    } else {
      setRecorder((previous) => ({
        ...previous,
        status: "REMOTE_UNKNOWN",
        error: recorderResult.error,
      }));
    }

    if (sourceResult.ok && sourceResult.data.source) {
      setSource(sourceResult.data.source);
    }
    initializedRef.current = true;
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 1500);
    return () => clearInterval(interval);
  }, [refresh]);

  const finishAction = () => {
    setBusyAction(null);
    setIsLoading(false);
  };

  const openCamera = async () => {
    setIsLoading(true);
    setBusyAction("open");
    setStreamError(null);
    const result = await apiPost("/api/v1/camera/start");
    if (result.ok) {
      setIsOpen(true);
      setImageLoaded(false);
      setStreamNonce((value) => value + 1);
      await refresh();
    } else {
      setStreamError(result.error || "Kamera gagal dibuka");
    }
    finishAction();
  };

  const closeCamera = async () => {
    setIsLoading(true);
    setBusyAction("close");
    const result = await apiPost("/api/v1/camera/stop");
    if (result.ok) {
      setIsOpen(false);
      setImageLoaded(false);
      setStreamError(null);
      await refresh();
    } else {
      setStreamError(result.error || "Kamera gagal ditutup");
    }
    finishAction();
  };

  const switchSource = async (nextSource) => {
    if (nextSource === source && isOpen) return;
    setIsLoading(true);
    setBusyAction(`source-${nextSource}`);
    setStreamError(null);
    const result = await apiPost("/api/v1/camera/source", { source: nextSource });
    if (result.ok) {
      setSource(nextSource);
      setIsOpen(true);
      setImageLoaded(false);
      setStreamNonce((value) => value + 1);
      await refresh();
    } else {
      setStreamError(result.error || `Sumber ${nextSource} gagal dipilih`);
    }
    finishAction();
  };

  const startRecording = async (recordingSource) => {
    setIsLoading(true);
    setBusyAction(`record-${recordingSource}`);
    setStreamError(null);
    const result = await apiPost("/api/v1/recordings/start", { source: recordingSource });
    if (result.ok) {
      setRecorder(result.data);
      setSource(recordingSource);
      setIsOpen(true);
      setImageLoaded(false);
      setStreamNonce((value) => value + 1);
      await refresh();
    } else {
      setStreamError(result.error || "Recording gagal dimulai");
      setRecorder((previous) => ({ ...previous, error: result.error }));
    }
    finishAction();
  };

  const stopRecording = async () => {
    setIsLoading(true);
    setBusyAction("stop-recording");
    const result = await apiPost("/api/v1/recordings/stop");
    if (result.ok) {
      setRecorder(result.data);
      setIsOpen(false);
      setImageLoaded(false);
      setStreamError(null);
      await refresh();
    } else {
      setStreamError(result.error || "Recording gagal dihentikan");
    }
    finishAction();
  };

  const reconnect = async () => {
    setIsLoading(true);
    setBusyAction("reconnect");
    setStreamError(null);
    await apiPost("/api/v1/camera/stop");
    const result = await apiPost("/api/v1/camera/start");
    if (!result.ok) setStreamError(result.error || "Kamera gagal disambungkan ulang");
    setIsOpen(true);
    setImageLoaded(false);
    setStreamNonce((value) => value + 1);
    await refresh();
    finishAction();
  };

  const streamState = imageLoaded ? "RUNNING" : camera.camera_status || "STOPPED";
  const recordingActive = Boolean(recorder.recording);

  return (
    <div className="vision-frame live-camera-frame">
      {isOpen ? (
        <img
          key={streamNonce}
          src={previewUrl}
          className={`camera-preview-image ${imageLoaded ? "is-live" : ""}`}
          alt={`${sourceLabel(source)} live preview`}
          onLoad={() => {
            setImageLoaded(true);
            setStreamError(null);
          }}
          onError={() => {
            setImageLoaded(false);
            setStreamError("Preview camera tidak dapat dibuka");
          }}
        />
      ) : null}
      {!imageLoaded ? (
        <div className="camera-preview-empty">
          <strong>{isOpen ? streamState : "CAMERA CLOSED"}</strong>
          <span>
            {streamError
              || camera.camera_error
              || (isOpen ? "Menunggu frame H.264/RTP dari Jetson" : "Tekan OPEN CAMERA untuk menampilkan stream")}
          </span>
        </div>
      ) : null}
      <div className="vision-frame-metrics">
        <span>CAM {sourceLabel(source)}</span>
        <span>STREAM {streamState}</span>
        <span>{Number(camera.width || 0)}×{Number(camera.height || 0)}</span>
        <span>{Number(camera.fps || camera.expected_fps || 0).toFixed(1)} FPS</span>
        <span>FRAMES {camera.frame_count || 0}</span>
        {recordingActive ? <span className="camera-recording-chip">● RECORDING</span> : null}
      </div>
      <div className="camera-preview-controls camera-preview-control-stack">
        <div className="camera-source-controls" aria-label="Camera source">
          <span>SOURCE</span>
          <button
            type="button"
            className={source === "csi" ? "is-active" : ""}
            onClick={() => switchSource("csi")}
            disabled={isLoading}
          >
            CSI
          </button>
          <button
            type="button"
            className={source === "analog" ? "is-active" : ""}
            onClick={() => switchSource("analog")}
            disabled={isLoading}
          >
            ANALOG
          </button>
        </div>
        <div className="camera-control-row">
          <span className={streamState === "RUNNING" ? "is-live" : ""}>
            {camera.transport || "H264/RTP/UDP"} · UDP {camera.stream_port || "-"}
          </span>
          <div>
            <button type="button" onClick={isOpen ? closeCamera : openCamera} disabled={isLoading || recordingActive}>
              {busyAction === "open" ? "OPENING…" : busyAction === "close" ? "CLOSING…" : isOpen ? "CLOSE CAMERA" : "OPEN CAMERA"}
            </button>
            {isOpen && !recordingActive ? (
              <button type="button" onClick={reconnect} disabled={isLoading}>RECONNECT</button>
            ) : null}
          </div>
        </div>
        <div className="camera-recording-controls" aria-label="Jetson recording controls">
          {recordingActive ? (
            <button type="button" className="is-stop" onClick={stopRecording} disabled={isLoading}>
              {busyAction === "stop-recording" ? "STOPPING…" : "STOP & AUTO CLOSE"}
            </button>
          ) : (
            <>
              <button type="button" className="is-record" onClick={() => startRecording("csi")} disabled={isLoading}>
                {busyAction === "record-csi" ? "STARTING…" : "REC CSI"}
              </button>
              <button type="button" className="is-record" onClick={() => startRecording("analog")} disabled={isLoading}>
                {busyAction === "record-analog" ? "STARTING…" : "REC ANALOG"}
              </button>
            </>
          )}
          <span className="camera-recording-status">{recorder.status}</span>
        </div>
      </div>
    </div>
  );
}

export default CameraPreview;
