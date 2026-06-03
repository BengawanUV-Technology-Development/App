import { useState } from "react";
import { apiPost } from "../services/api";

export function useCommand() {
  const [status, setStatus] = useState("-");
  const [isLoading, setIsLoading] = useState(false);

  const execute = async (path, label, body = null) => {
    setIsLoading(true);
    setStatus(`Sending ${label}...`);

    const result = await apiPost(path, body);
    setIsLoading(false);

    if (!result.ok) {
      setStatus(result.error);
      return result;
    }

    setStatus(result.data?.message || `${label} berhasil`);
    return result;
  };

  return { execute, status, isLoading };
}
