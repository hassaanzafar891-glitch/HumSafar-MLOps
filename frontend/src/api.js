let token = null;
let expired = () => {};
export function setSession(value, onExpired) {
  token = value;
  if (onExpired) expired = onExpired;
}
export function errorMessage(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => `${e.loc?.slice(1).join(" › ") || "Request"}: ${e.msg}`)
      .join("; ");
  return (
    detail?.message || detail?.code || "Something went wrong. Please try again."
  );
}
export async function api(path, { method = "GET", body, form, signal } = {}) {
  const usedToken = token;
  const headers = {};
  if (usedToken) headers.Authorization = `Bearer ${usedToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: form
      ? new URLSearchParams(form)
      : body === undefined
        ? undefined
        : JSON.stringify(body),
    signal,
    cache: "no-store",
  });
  if (response.status === 401 && usedToken && token === usedToken) {
    setSession(null);
    expired();
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(
      errorMessage(data.detail) || `Request failed (${response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}
