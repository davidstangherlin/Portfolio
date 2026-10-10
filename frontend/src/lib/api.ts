// Calls to gui.py's JSON API, as getJSON() in web/app.js: every answer
// carries the page files' version, so a tab left open after an update
// reloads on its next page change.
import { host } from "./host";

async function failure(res: Response): Promise<Error> {
  const body = await res.json().catch(() => ({}));
  return new Error((body as { detail?: string }).detail || `Request failed (${res.status})`);
}

export async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  host().noteVersion(res);
  if (!res.ok) throw await failure(res);
  return res.json() as Promise<T>;
}

/* Every change carries the X-Sift header: gui.py refuses changes without
   it, so another website's page can't make them with a saved password. */
export async function send<T = Record<string, unknown>>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method, headers: { "Content-Type": "application/json", Accept: "application/json", "X-Sift": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data as T;
}
