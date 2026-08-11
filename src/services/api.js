export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:5001";
export const WS_BASE = API_BASE.replace(/^http/, "ws");
let operatorToken = "";

export function setOperatorToken(value) {
  operatorToken = String(value || "").trim();
}

export function clearOperatorToken() {
  operatorToken = "";
}

export function webSocketUrl(path) {
  const url = new URL(`${WS_BASE}${path}`);
  if (operatorToken) url.searchParams.set("token", operatorToken);
  return url.toString();
}

async function apiRequest(path, options = {}) {
  try {
    const headers = new Headers(options.headers || {});
    if (operatorToken) headers.set("Authorization", `Bearer ${operatorToken}`);
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
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
