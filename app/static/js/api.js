const csrf = document.querySelector('meta[name="csrf-token"]')?.content;

export async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(csrf ? { "X-CSRFToken": csrf } : {}), ...options.headers };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

export const conversations = {
  list: (query = "", archived = false) => api(`/api/conversations?q=${encodeURIComponent(query)}&archived=${archived ? 1 : 0}&limit=50`),
  create: () => api("/api/conversations", { method: "POST", body: "{}" }),
  update: (id, body) => api(`/api/conversations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  remove: (id) => api(`/api/conversations/${id}`, { method: "DELETE" }),
  duplicate: (id) => api(`/api/conversations/${id}/duplicate`, { method: "POST", body: "{}" }),
  exportUrl: (id, format = "json") => `/api/conversations/${id}/export?format=${format}`,
  messages: (id) => api(`/api/conversations/${id}/messages?limit=100`),
};

export const messageFeedback = (id, rating, comment = "") =>
  api(`/api/messages/${id}/feedback`, {
    method: "POST",
    body: JSON.stringify({ rating, comment }),
  });

export const settings = {
  get: () => api("/api/settings"),
  update: (body) => api("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
};
