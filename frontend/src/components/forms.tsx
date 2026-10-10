// Form pieces shared by the portfolio and watchlist pages (field(),
// formMessage() and rowButton() in web/app.js).
import { forwardRef, type ReactNode } from "react";

export function Field({ label, hint, hidden, children }: { label: string; hint?: string | null; hidden?: boolean; children: ReactNode }) {
  return (
    <label className="field" hidden={hidden || undefined}>
      <span className="field-label">{label}</span>{children}{hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

/* A status line under a form: what happened, or what to fix (lib/forms.ts showMessage() writes it). */
export const FormMessage = forwardRef<HTMLParagraphElement>(function FormMessage(_, ref) {
  return <p className="form-msg" role="status" aria-live="polite" ref={ref} />;
});

/* A small button in a table row that doesn't open the row. */
export function RowButton({ label, cls = "", onClick }: { label: string; cls?: string; onClick: () => void }) {
  return <button type="button" className={`btn small ${cls}`} onClick={(e) => { e.stopPropagation(); onClick(); }}>{label}</button>;
}

export const todayIso = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
