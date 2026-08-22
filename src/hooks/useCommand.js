import { useState } from "react";
import { apiPost } from "../services/api";

export function useCommand() {
  const [status, setStatus] = useState("-");
  const [isLoading, setIsLoading] = useState(false);
  const [lastResult, setLastResult] = useState(null);

  const execute = async (path, label, body = null) => {
    setIsLoading(true);
    setStatus(`PENDING ${label}`);
    setLastResult({ ok: null, label, message: `Sending ${label}...` });

    const result = await apiPost(path, body);
    setIsLoading(false);

    if (!result.ok) {
      const message = result.error || `Failed ${label}`;
      setStatus(`FAIL ${label}: ${message}`);
      setLastResult({ ok: false, label, message, result });
      return result;
    }

    const message = result.data?.message || `${label} berhasil`;
    setStatus(`OK ${label}: ${message}`);
    setLastResult({ ok: true, label, message, result });
    return result;
  };

  return { execute, status, isLoading, lastResult };
}
