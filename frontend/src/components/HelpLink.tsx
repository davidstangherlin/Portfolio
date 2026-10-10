import type { MouseEvent } from "react";
import { host } from "../lib/host";

// The pink "?" that opens a help article in a new tab, as helpLink() in
// web/app.js does. Renders nothing for an unknown article.
export function HelpLink({ id }: { id: string }) {
  const entry = host().helpEntry(id);
  if (!entry) return null;
  const href = `#/help/${id}`;
  const open = (ev: MouseEvent<HTMLAnchorElement>) => {
    ev.stopPropagation();
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button !== 0) return;
    ev.preventDefault();
    host().openHelp(id);
  };
  return (
    <a className="help-link" href={href} target="_blank" rel="noopener" onClick={open}
      title={`Help: ${entry.title} (opens in a new tab)`} aria-label={`Help: ${entry.title}, opens in a new tab`}>?</a>
  );
}
