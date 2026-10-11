/**
 * Account client — signup, login, logout, current researcher.
 *
 * The session lives in an httpOnly cookie that JavaScript cannot read. Every
 * call sends credentials: "include" so the browser attaches it; without that
 * the server never sees who is signed in.
 */

const BASE = "/api/auth";

/** Error carrying the HTTP status, so callers can tell 401 from a dead server. */
export class AuthError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** FastAPI returns detail as a string, or a list of field errors on a 422. */
function readDetail(body, fallback) {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) {
    return d.map((e) => e.msg).filter(Boolean).join(" ") || fallback;
  }
  return fallback;
}

async function request(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      credentials: "include",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new AuthError("Can't reach the analysis server. Is the backend running?", 0);
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* empty or non-JSON body */
  }
  if (!res.ok) {
    throw new AuthError(readDetail(data, `${res.status} ${res.statusText}`), res.status);
  }
  return data;
}

export function signup({ email, displayName, password, institution }) {
  return request("/signup", {
    method: "POST",
    body: {
      email,
      display_name: displayName,
      password,
      institution: institution || null,
    },
  });
}

export function login({ email, password }) {
  return request("/login", { method: "POST", body: { email, password } });
}

export function logout() {
  return request("/logout", { method: "POST" });
}

/** The signed-in researcher, or null when nobody is. Other failures throw. */
export async function me() {
  try {
    return await request("/me");
  } catch (err) {
    if (err.status === 401) return null;
    throw err;
  }
}
