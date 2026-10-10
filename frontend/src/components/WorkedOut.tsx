import type { ReactNode } from "react";
import { HelpLink } from "./HelpLink";

// "How this is worked out": the method behind a figure, closed by default
// (the same twisty as workedOut() in web/app.js).
export function WorkedOut({ paragraphs, helpId, children }: { paragraphs: string[]; helpId?: string; children?: ReactNode }) {
  return (
    <details className="worked-out">
      <summary><span className="twisty" aria-hidden="true" />How this is worked out</summary>
      <div className="inner">
        {paragraphs.map((t) => <p key={t}>{t}</p>)}
        {children}
        {helpId ? <p><HelpLink id={helpId} /></p> : null}
      </div>
    </details>
  );
}
