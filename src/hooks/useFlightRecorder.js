import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../services/api";

const initialState = {
  recording: false,
  status: "IDLE",
  session_id: null,
  session_dir: null,
  frame_count: 0,
  duration_seconds: 0,
  error: null,
};

export function useFlightRecorder() {
  const [recorder, setRecorder] = useState(initialState);
  const [isLoading, setIsLoading] = useState(false);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    const result = await apiGet("/api/v1/recordings/status");
    if (mountedRef.current && result.ok) setRecorder(result.data);
    return result;
  }, []);

  const execute = useCallback(async (action) => {
    setIsLoading(true);
    const result = await apiPost(`/api/v1/recordings/${action}`);
    if (mountedRef.current) {
      if (result.data) setRecorder(result.data);
      else if (!result.ok) setRecorder((previous) => ({ ...previous, error: result.error }));
      setIsLoading(false);
    }
    return result;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    refresh();
    const interval = setInterval(refresh, recorder.recording ? 500 : 2000);
    return () => {
      mountedRef.current = false;
      clearInterval(interval);
    };
  }, [recorder.recording, refresh]);

  return {
    recorder,
    isLoading,
    startRecording: () => execute("start"),
    stopRecording: () => execute("stop"),
  };
}
