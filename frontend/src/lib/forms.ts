// A status line under a form (formMessage() and showMessage() in web/app.js):
// only the latest outcome stays on screen, so an earlier "Recorded" never
// sits above a new error.
export function showMessage(el: HTMLElement | null, text: string, ok: boolean): void {
  if (!el) return;
  for (const other of document.querySelectorAll<HTMLElement>(".form-msg")) if (other !== el) other.textContent = "";
  el.textContent = text; el.className = `form-msg ${ok ? "ok" : "bad"}`;
}
