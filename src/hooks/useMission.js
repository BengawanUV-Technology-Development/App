import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../services/api";

const initialMission = {
  ok: true,
  count: 0,
  positioned_count: 0,
  current_seq: null,
  current_waypoint: null,
  waypoints: [],
  error: null,
};

export function useMission() {
  const [mission, setMission] = useState(initialMission);

  const refreshMission = useCallback(async () => {
    const result = await apiGet("/api/v1/mission");
    if (!result.ok) {
      setMission((previous) => ({ ...previous, error: result.error || "Mission unavailable" }));
      return { mission: null, error: result.error };
    }
    setMission({ ...result.data, error: null });
    return { mission: result.data, error: null };
  }, []);

  useEffect(() => {
    refreshMission();
    const interval = setInterval(refreshMission, 5000);
    return () => clearInterval(interval);
  }, [refreshMission]);

  return { mission, refreshMission };
}
