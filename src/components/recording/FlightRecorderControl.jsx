import { useFlightRecorder } from "../../hooks/useFlightRecorder";

function formatDuration(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const remainder = String(seconds % 60).padStart(2, "0");
  return `${hours}:${minutes}:${remainder}`;
}

function FlightRecorderControl({ onEvent }) {
  const { recorder, isLoading, startRecording, stopRecording } = useFlightRecorder();

  const toggleRecording = async () => {
    const action = recorder.recording ? "stop" : "start";
    const result = recorder.recording ? await stopRecording() : await startRecording();
    onEvent?.(
      result.ok ? "ok" : "danger",
      result.ok
        ? `${action === "start" ? "Recording started" : "Recording saved"}: ${result.data?.session_id || "-"}`
        : `Recording ${action} failed: ${result.error}`,
    );
  };

  const remoteUnknown = recorder.status === "REMOTE_UNKNOWN";
  const active = recorder.recording === true
    || recorder.status === "STARTING"
    || recorder.status === "STOPPING"
    || remoteUnknown;
  return (
    <section className={`flight-recorder-panel ${active ? "is-recording" : ""}`}>
      <div className="flight-recorder-heading">
        <span><i /> JETSON HIGH-RES</span>
        <strong>{recorder.status}</strong>
      </div>
      <div className="flight-recorder-metrics">
        <span><small>TIME</small>{formatDuration(recorder.duration_seconds)}</span>
        <span><small>FRAMES</small>{recorder.frame_count || 0}</span>
      </div>
      <button
        type="button"
        onClick={toggleRecording}
        disabled={isLoading || recorder.status === "STOPPING" || remoteUnknown}
      >
        {remoteUnknown ? "JETSON CONNECTION LOST" : active ? "STOP & SAVE" : "START RECORDING"}
      </button>
      {recorder.error ? <small className="flight-recorder-error">{recorder.error}</small> : null}
      {recorder.stream_target?.host ? (
        <small>
          STREAM → {recorder.stream_target.host}:{recorder.stream_target.video_port}
        </small>
      ) : null}
      {recorder.session_id ? <small title={recorder.session_dir || ""}>{recorder.session_id}</small> : null}
    </section>
  );
}

export default FlightRecorderControl;
