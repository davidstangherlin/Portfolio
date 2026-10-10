// Help: Sift's knowledge base (web/knowledge.json), searchable and filtered
// by topic. #/help, #/help?q=words, #/help/{entry} (opens and scrolls to it).
import { Fragment, useEffect, useRef, useState } from "react";
import { PageHead } from "../components/bits";
import { host, type KnowledgeEntry } from "../lib/host";
import { searchKnowledge } from "../lib/knowledge";

const remembered = { q: "", category: "" };   // kept between visits, as before

function HelpEntry({ e, open }: { e: KnowledgeEntry; open: boolean }) {
  const kb = host().knowledge(), fill = host().fillThresholds;
  const cat = kb.categories.find((c) => c.id === e.category);
  const inSift = e.hover && e.hover !== e.definition ? fill(e.hover) : null;
  const related = (e.related || []).map((id) => kb.entries.find((x) => x.id === id)).filter((r): r is KnowledgeEntry => Boolean(r));
  return (
    <details className="help-entry" id={`help-${e.id}`} open={open || undefined}>
      <summary>
        <span className="twisty" aria-hidden="true" />
        <span className="help-title">{e.title}</span>
        <span className="help-def">{fill(e.definition || "")}</span>
      </summary>
      <div className="help-body">
        {cat ? <span className="tag muted sm">{cat.name}</span> : null}
        {e.full && e.abbreviation ? <p><strong>{e.abbreviation}</strong> stands for {e.full}.</p> : null}
        {inSift ? <p><strong>In Sift: </strong>{inSift}</p> : null}
        {(e.body || []).map((para, i) => <p key={i}>{fill(para)}</p>)}
        {related.length ? (
          <p className="help-related">Related: {related.map((r, i) => <Fragment key={r.id}>{i ? ", " : ""}<a href={`#/help/${r.id}`}>{r.title}</a></Fragment>)}</p>
        ) : null}
        {(e.links || []).length ? (
          <p className="help-links">{(e.links || []).map((l, i) => (
            <Fragment key={l.href + i}>{i ? "  |  " : ""}{/^https?:/.test(l.href)
              ? <a href={l.href} target="_blank" rel="noopener noreferrer">{`${l.text} ↗`}</a>
              : <a href={l.href}>{`${l.text} →`}</a>}</Fragment>
          ))}</p>
        ) : null}
      </div>
    </details>
  );
}

export function HelpPage({ query, focusId }: { query?: string; focusId?: string }) {
  if (query !== undefined) remembered.q = new URLSearchParams(query).get("q") || "";
  if (focusId) { remembered.q = ""; remembered.category = ""; }
  const [q, setQ] = useState(remembered.q);
  const [category, setCategory] = useState(remembered.category);
  const search = useRef<HTMLInputElement>(null);
  const kb = host().knowledge();

  useEffect(() => {
    const target = focusId && document.getElementById(`help-${focusId}`);
    if (target) target.scrollIntoView({ block: "start" }); else window.scrollTo(0, 0);
    if (!focusId && window.matchMedia?.("(hover: hover)").matches) search.current?.focus();
  }, [focusId]);

  const words = q.trim();
  let list = words ? searchKnowledge(kb.entries, words) : kb.entries;
  if (category) list = list.filter((e) => e.category === category);
  const open = (e: KnowledgeEntry) => e.id === focusId || (words !== "" && list.length <= 3);
  const pick = (id: string) => { const next = category === id ? "" : id; remembered.category = next; setCategory(next); };

  let results;
  if (!list.length) results = <p className="empty">Nothing matches "{words}". Try a shorter word, or clear the topic filter.</p>;
  else if (words) results = <div className="card">{list.map((e) => <HelpEntry key={e.id} e={e} open={open(e)} />)}</div>;
  else results = kb.categories.map((c) => {
    const items = list.filter((e) => e.category === c.id);
    return items.length ? (
      <section className="card help-group" key={c.id}><h2>{c.name}</h2>{items.map((e) => <HelpEntry key={e.id} e={e} open={open(e)} />)}</section>
    ) : null;
  });

  return (
    <>
      <PageHead title="Help" sub="Terms, rules and how Sift works" />
      <div className="controls">
        <input ref={search} type="search" className="page-search" value={q} placeholder="Search terms, rules and how-tos"
          aria-label="Search help" autoComplete="off" onChange={(e) => { remembered.q = e.target.value; setQ(e.target.value); }} />
        <span className="count">{`${list.length} of ${kb.entries.length}`}</span>
      </div>
      <div className="chips" role="group" aria-label="Filter by topic">
        {[{ id: "", name: "All topics" }, ...kb.categories].map((c) => (
          <button key={c.id} type="button" className="chip" data-cat={c.id} aria-pressed={String(c.id === category) as "true" | "false"}
            onClick={() => pick(c.id)}>{c.name}</button>
        ))}
      </div>
      <div className="help-results">{results}</div>
    </>
  );
}
