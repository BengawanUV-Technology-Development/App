import { useCallback, useEffect, useState } from "react";
import { apiGet } from "../services/api";

const initialMessages = {
  ok: true,
  count: 0,
  messages: [],
  error: null,
};

export function useMissionMessages() {
  const [missionMessages, setMissionMessages] = useState(initialMessages);

  const refreshMessages = useCallback(async () => {
    const result = await apiGet("/api/v1/messages");
    if (!result.ok) {
      setMissionMessages((previous) => ({ ...previous, error: result.error || "Mission Planner messages unavailable" }));
      return { messages: [], error: result.error };
    }
    setMissionMessages({ ...result.data, error: null });
    return { messages: result.data?.messages || [], error: null };
  }, []);

  useEffect(() => {
    refreshMessages();
    const interval = setInterval(refreshMessages, 2000);
    return () => clearInterval(interval);
  }, [refreshMessages]);

  return { missionMessages, refreshMessages };
}
