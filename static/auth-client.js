const TOKEN_KEY = "consilium_access_token";
const REFRESH_KEY = "consilium_refresh_token";

export function getAccessToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access, refresh) {
  if (access) localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export async function refreshAccessToken() {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  const res = await fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) {
    clearTokens();
    return false;
  }
  const data = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return true;
}

export async function authFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res = await fetch(url, { ...options, headers, credentials: "same-origin" });
  if (res.status === 401 && (await refreshAccessToken())) {
    headers.set("Authorization", `Bearer ${getAccessToken()}`);
    res = await fetch(url, { ...options, headers, credentials: "same-origin" });
  }
  return res;
}

export async function fetchAuthMe() {
  const res = await authFetch("/api/auth/me");
  if (!res.ok) return null;
  return res.json();
}

export async function fetchBalance() {
  const res = await authFetch("/api/billing/balance");
  if (!res.ok) return null;
  return res.json();
}

export function applyOAuthFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const access = params.get("access_token");
  const refresh = params.get("refresh_token");
  if (access && refresh) {
    setTokens(access, refresh);
    params.delete("access_token");
    params.delete("refresh_token");
    const q = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (q ? `?${q}` : ""));
    return true;
  }
  return false;
}
