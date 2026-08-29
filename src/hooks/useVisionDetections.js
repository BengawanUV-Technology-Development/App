import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../services/api";
import { normalizeLatestVisionResponse } from "../services/visionDetection.js";

const POLL_INTERVAL_MS = 750;

const initialState = {
  active: false,
  mission_id: null,
  detection: null,
  coordinate: null,
  latest_overlay: null,
  error: null,
};

export function useVisionDetections() {
  const [vision, setVision] = useState(initialState);

  const refresh = useCallback(async () => {
    const result = await apiGet("/api/v1/detection/latest");
    setVision({ ...initialState, ...normalizeLatestVisionResponse(result) });
    return result;
  }, []);

  useEffect(() => {
    let stopped = false;
    const poll = async () => {
      if (!stopped) await refresh();
    };
    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [refresh]);

  return { vision, refresh };
}
