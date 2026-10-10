// A label's explanation from web/knowledge.json: shown on mouse hover and
// keyboard focus, and from a small "i" button on touch screens (withHelp()
// in web/app.js).
import type { FocusEvent, MouseEvent, PointerEvent, ReactNode } from "react";
import { h } from "../lib/dom";
import { host } from "../lib/host";
import { hideTip, placeTipBelow, showTip } from "../lib/tooltip";

const nodes = (label: string, text: string) => [h("div", { class: "t-title", text: label }), h("div", { text })];

/* Props that make an element show `label`'s explanation, and the "i" to put inside it. */
export function useFieldHelp(label: string, text: string | null = host().fieldHelp(label)) {
  if (!text) return { props: {}, info: null as ReactNode };
  const props = {
    className: "has-help",
    onPointerMove: (e: PointerEvent) => { if (e.pointerType !== "touch") showTip(e, nodes(label, text)); },
    onPointerLeave: hideTip,
    onFocus: (e: FocusEvent) => placeTipBelow(e.currentTarget, nodes(label, text)),
    onBlur: hideTip,
  };
  const info = (
    <button type="button" className="info" aria-label={`What is ${label}?`}
      onClick={(e: MouseEvent) => { e.stopPropagation(); placeTipBelow(e.currentTarget, nodes(label, text)); }}
      onKeyDown={(e) => e.stopPropagation()}>i</button>
  );
  return { props, info };
}

/* A table heading with its explanation, if web/knowledge.json has one. */
export function HelpTh({ label, className }: { label: string; className?: string }) {
  const { props, info } = useFieldHelp(label);
  const cls = [className, (props as { className?: string }).className].filter(Boolean).join(" ") || undefined;
  return <th {...props} className={cls}>{label}{info}</th>;
}
