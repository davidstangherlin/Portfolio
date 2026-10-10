// Pass, fail or no data, as checklist() in web/app.js.
export function Checklist({ items }: { items: { label: string; passed: boolean | null; title?: string }[] }) {
  return (
    <ul className="checklist">
      {items.map((c) => {
        const [cls, mark] = c.passed === true ? ["pass", "✓"] : c.passed === false ? ["fail", "✕"] : ["na", "–"];
        return (
          <li key={c.label} title={c.title}>
            <span className={`mark ${cls}`} aria-hidden="true">{mark}</span>
            <span>{c.label + (c.passed === null ? " (no data)" : "")}</span>
          </li>
        );
      })}
    </ul>
  );
}
