import { useLayoutEffect, useRef } from "react";

// A chart drawn at its real on-screen width, so text keeps its size on a
// phone and a wide monitor alike, and redrawn when the width changes (as
// chartSlot() in web/app.js). `draw` builds the SVG for a width.
export function ChartSlot({ draw }: { draw: (width: number) => Node }) {
  const ref = useRef<HTMLDivElement>(null);
  const drawRef = useRef(draw);
  drawRef.current = draw;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let last = -1;
    const paint = (force = false) => {
      const w = Math.max(260, Math.floor(el.clientWidth));
      if (!force && w === last) return;
      last = w;
      el.replaceChildren(drawRef.current(w));
    };
    paint(true);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const later = () => { clearTimeout(timer); timer = setTimeout(() => paint(), 150); };
    // Printing redraws at the paper's width and in print colours, then back (web/app.js, printing).
    const reprint = () => paint(true);
    // Inside a closed twisty the chart can't be measured: draw it again when it opens.
    const twisty = el.parentElement?.closest("details");
    const opened = () => paint();
    twisty?.addEventListener("toggle", opened);
    window.addEventListener("resize", later);
    window.addEventListener("beforeprint", reprint);
    window.addEventListener("afterprint", reprint);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", later);
      window.removeEventListener("beforeprint", reprint);
      window.removeEventListener("afterprint", reprint);
      twisty?.removeEventListener("toggle", opened);
    };
  }, [draw]);
  return <div className="chart-slot" ref={ref} />;
}
