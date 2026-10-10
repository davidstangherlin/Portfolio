import type { ReactNode } from "react";

// Same markup as card() in web/app.js, so it picks up Sift's card styles.
export function Card({ title, hint, wide, className, children }:
  { title: string; hint?: string | null; wide?: boolean; className?: string; children?: ReactNode }) {
  const cls = ["card", wide ? "wide" : "", className ?? ""].filter(Boolean).join(" ");
  return (
    <section className={cls}>
      <h2>{title}</h2>
      {hint ? <p className="hint">{hint}</p> : null}
      {children}
    </section>
  );
}
