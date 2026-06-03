const API_BASE = "http://localhost:5001";

async function apiRequest(path, options = {}) {
  try {
    const response = await fetch(`${API_BASE}${path}`, options);
    const data = await response.json().catch(() => null);

    if (!response.ok) {
      return {
        ok: false,
        error: data?.error || data?.message || `Request failed: ${response.status}`,
        data,
      };
    }

    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: String(error) };
  }
}

export function apiGet(path) {
  return apiRequest(path);
}

export function apiPost(path, body = null) {
  const options = { method: "POST" };

  if (body !== null && body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }

  return apiRequest(path, options);
}
