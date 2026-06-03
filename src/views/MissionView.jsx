import { useState } from "react";
import { apiGet, apiPost } from "../services/api";

function MissionView({ isConnected, onTelemetryRefresh }) {
  const [missionDraft, setMissionDraft] = useState(`[
  {
    "seq": 0,
    "latitude_deg": -6.2001,
    "longitude_deg": 106.8166,
    "relative_altitude_m": 15,
    "speed_m_s": 5,
    "is_fly_through": false
  }
]`);
  const [missionStatus, setMissionStatus] = useState("-");
  const [missionProgress, setMissionProgress] = useState("-");

  const uploadMission = async () => {
    try {
      const waypoints = JSON.parse(missionDraft);
      const result = await apiPost("/mission/upload", { waypoints });
      if (!result.ok) {
        throw new Error(result.error || "Gagal upload mission");
      }

      setMissionStatus(result.data?.message || "Mission uploaded");
      await onTelemetryRefresh();
    } catch (error) {
      setMissionStatus(String(error));
      console.error("Error uploading mission:", error);
    }
  };

  const runMissionCommand = async (path, label) => {
    try {
      const result = await apiPost(path);
      if (!result.ok) {
        throw new Error(result.error || `Gagal ${label}`);
      }

      setMissionStatus(result.data?.message || `${label} requested`);
      await onTelemetryRefresh();
    } catch (error) {
      setMissionStatus(String(error));
      console.error(`Error ${label}:`, error);
    }
  };

  const refreshMissionProgress = async () => {
    try {
      const result = await apiGet("/mission/progress");
      if (!result.ok) {
        throw new Error(result.error || "Gagal ambil progress mission");
      }

      setMissionProgress(
        result.data?.current === undefined || result.data?.total === undefined
          ? "-"
          : `${result.data.current}/${result.data.total}`,
      );
      setMissionStatus("Mission progress diperbarui");
    } catch (error) {
      setMissionStatus(String(error));
      console.error("Error reading mission progress:", error);
    }
  };

  return (
    <>
      <header className="view-header">
        <div>
          <p className="view-kicker">Mission</p>
          <h1 className="view-title">Waypoint upload</h1>
          <p className="view-copy">Existing mission controls are preserved while the map redesign waits for a later phase.</p>
        </div>
      </header>

      <section className="panel">
        <div className="panel-header mission-header">
          <div>
            <p className="panel-label">Mission</p>
            <h2>Upload waypoint sederhana</h2>
            <p className="muted">UI ini sengaja minimal supaya backend bisa dicoba sekarang.</p>
          </div>
          <div className="mission-meta">
            <span>Upload: {missionStatus}</span>
            <span>Progress: {missionProgress}</span>
          </div>
        </div>

        <div className="mission-layout">
          <label className="mission-editor">
            <span>Waypoint JSON</span>
            <textarea
              value={missionDraft}
              onChange={(event) => setMissionDraft(event.target.value)}
              spellCheck={false}
            />
          </label>

          <div className="mission-actions">
            <button type="button" onClick={uploadMission} disabled={!isConnected}>Upload</button>
            <button type="button" onClick={() => runMissionCommand("/mission/start", "start mission")} disabled={!isConnected}>
              Start
            </button>
            <button type="button" onClick={() => runMissionCommand("/mission/pause", "pause mission")} disabled={!isConnected}>
              Pause
            </button>
            <button type="button" onClick={() => runMissionCommand("/mission/clear", "clear mission")} disabled={!isConnected}>
              Clear
            </button>
            <button type="button" onClick={refreshMissionProgress} disabled={!isConnected}>
              Refresh Progress
            </button>
          </div>
        </div>
      </section>
    </>
  );
}

export default MissionView;
