import { createContext, useContext, type HTMLAttributes, type ReactNode } from "react";

// Same markup as card() in web/app.js, so it picks up Sift's card styles.
// On the dashboard, DashLayout wraps each widget in a DashCardContext so the
// card gets its id, its pin and tools bar before the title, the title as a
// drag handle, and the width the layout chose.
export interface DashCardSlot {
  id: string; tools: ReactNode; className: string; wide: boolean | null; headProps: HTMLAttributes<HTMLHeadingElement>;
}
export const DashCardContext = createContext<DashCardSlot | null>(null);

export function Card({ title, hint, wide, className, children }:
  { title: string; hint?: string | null; wide?: boolean; className?: string; children?: ReactNode }) {
  const dash = useContext(DashCardContext);
  const isWide = dash && dash.wide !== null ? dash.wide : wide;
  const cls = ["card", isWide ? "wide" : "", className ?? "", dash ? dash.className : ""].filter(Boolean).join(" ");
  return (
    <section className={cls} data-card={dash ? dash.id : undefined}>
      {dash ? dash.tools : null}
      <h2 {...(dash ? dash.headProps : {})}>{title}</h2>
      {hint ? <p className="hint">{hint}</p> : null}
      {children}
    </section>
  );
}
