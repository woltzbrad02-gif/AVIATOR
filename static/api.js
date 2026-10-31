/* Shared demo/real API helpers — included by index.html */
async function aviatorApi(path, opts = {}) {
    const res = await fetch(path, {
        credentials: "include",
        headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
        ...opts
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
        throw new Error(data.error || "Request failed");
    }
    return data;
}
