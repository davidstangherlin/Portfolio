// The score wheel in a list row: five spokes, no labels (wheel() with
// labels off, in web/app.js), drawn as plain SVG.
export function MiniWheel({ scores, axes, max, size = 34 }: { scores: number[]; axes: string[]; max: number; size?: number }) {
  const n = axes.length, c = size / 2, R = size / 2 - 2;
  const angle = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i: number, frac: number) => [c + R * frac * Math.cos(angle(i)), c + R * frac * Math.sin(angle(i))];
  const total = scores.reduce((a, b) => a + b, 0);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} className="mini-wheel" role="img"
      aria-label={`Score ${total} of ${max * n}: ` + axes.map((a, i) => `${a} ${scores[i]} of ${max}`).join(", ")}>
      <title>{axes.map((a, i) => `${a} ${scores[i]}/${max}`).join("  |  ")}</title>
      <polygon points={axes.map((_, i) => pt(i, 1).join(",")).join(" ")} fill="none" stroke="var(--grid)" strokeWidth={1} />
      <polygon points={scores.map((v, i) => pt(i, Math.max(v, 0.15) / max).join(",")).join(" ")} fill="var(--s1)" fillOpacity={0.18}
        stroke="var(--s1)" strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}
