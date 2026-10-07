/* Table filters for Sift's list views (docs/AS_BUILT.md §30): a search box
   over every column, a condition builder behind the pink "Filter" button,
   removable chips, and right-click (press and hold on a phone) "Show
   matching" / "Filter out" on any cell.

   Ported from the user's filter_component.py design, with the review's
   fixes: numbers typed as text are compared as numbers ("20", "20%",
   "$1.2B"), "between" takes two values, comma-separated values are a list,
   a blank cell matches with "is empty", "Show matching" replaces only a
   lone AND condition on that column, and search looks at the text as
   shown.

   Conditions are data, applied top to bottom with no brackets: A AND B OR C
   means (A AND B) OR C. A condition still being typed (no usable value) is
   skipped rather than emptying the table. Each table keeps its own filters
   until the page reloads (TF_STATES).

   The first part is pure (no page needed) so tests can run it in Node; the
   second builds the controls with app.js's h(). */

/* ---------- filtering (pure) ---------- */

const TF_OPS = [
  { id: "=", label: "equals", chip: "=", types: ["text", "num"] },
  { id: "!=", label: "does not equal", chip: "≠", types: ["text", "num"] },
  { id: "contains", label: "contains", chip: "contains", types: ["text", "num"] },
  { id: "not_contains", label: "does not contain", chip: "doesn't contain", types: ["text", "num"] },
  { id: ">", label: "greater than", chip: ">", types: ["num"] },
  { id: "<", label: "less than", chip: "<", types: ["num"] },
  { id: "between", label: "between", chip: "between", types: ["num"] },
  { id: "is_empty", label: "is empty", chip: "is empty", types: ["text", "num"] },
  { id: "is_not_empty", label: "is not empty", chip: "is not empty", types: ["text", "num"] },
];
const TF_NO_VALUE = new Set(["is_empty", "is_not_empty"]);
const TF_SCALE = { k: 1e3, m: 1e6, b: 1e9, t: 1e12 };

/* "20", "20%", "-1.5", "$1,234.50", "1.2B", "300k" as numbers; null if not a number. */
function tfNumber(text) {
  if (typeof text === "number") return Number.isFinite(text) ? text : null;
  if (text === null || text === undefined) return null;
  const m = String(text).trim().replace(/[,\s]/g, "").match(/^([+-]?)\$?([+-]?)(\d*\.?\d+)([kmbt]?)%?$/i);
  if (!m) return null;
  const sign = m[1] === "-" || m[2] === "-" ? -1 : 1;
  return sign * parseFloat(m[3]) * (m[4] ? TF_SCALE[m[4].toLowerCase()] : 1);
}
/* "BHP, RIO" as ["BHP", "RIO"]. */
const tfTerms = (value) => String(value ?? "").split(",").map((s) => s.trim()).filter(Boolean);
/* A value picked by right-click is one value even if it has a comma in it. */
const tfCondTerms = (cond) => (cond.exact ? [String(cond.value ?? "")].filter((t) => t.trim()) : tfTerms(cond.value));
const tfBlank = (v) => v === null || v === undefined || String(v).trim() === "";
const tfLower = (v) => String(v ?? "").toLowerCase();
const tfGet = (field, row) => field.get(row);
const tfText = (field, row) => (field.text ? field.text(row) : String(field.get(row) ?? ""));

/* Whether a condition has what it needs to filter yet. */
function tfReady(cond, field) {
  if (!field) return false;
  if (TF_NO_VALUE.has(cond.op)) return true;
  if (cond.op === "between") {
    const [lo, hi] = Array.isArray(cond.value) ? cond.value : [];
    return tfNumber(lo) !== null || tfNumber(hi) !== null;
  }
  const terms = tfCondTerms(cond);
  if (!terms.length) return false;
  if (field.type === "num" && [">", "<", "=", "!="].includes(cond.op)) return terms.every((t) => tfNumber(t) !== null);
  return true;
}

function tfEqualsNumber(field, row, n) {
  const v = tfGet(field, row);
  if (v === null || v === undefined) return false;
  if (Math.abs(v - n) <= 1e-9 * Math.max(1, Math.abs(n))) return true;
  return tfNumber(tfText(field, row)) === n;  // "23" matches a value shown as 23% but stored as 23.4
}

function tfTest(row, cond, field) {
  const v = tfGet(field, row);
  switch (cond.op) {
    case "is_empty": return tfBlank(v);
    case "is_not_empty": return !tfBlank(v);
    case "contains":
    case "not_contains": {
      const text = tfLower(tfText(field, row));
      const hit = tfCondTerms(cond).some((t) => text.includes(t.toLowerCase()));
      return cond.op === "contains" ? hit : !hit;
    }
    case "=":
    case "!=": {
      const hit = field.type === "num"
        ? tfCondTerms(cond).some((t) => tfEqualsNumber(field, row, tfNumber(t)))
        : tfCondTerms(cond).some((t) => tfLower(v).trim() === t.trim().toLowerCase());
      return cond.op === "=" ? hit : !hit;
    }
    case ">": return v !== null && v !== undefined && v > tfNumber(cond.value);
    case "<": return v !== null && v !== undefined && v < tfNumber(cond.value);
    case "between": {
      if (v === null || v === undefined) return false;
      const [lo, hi] = cond.value.map(tfNumber);
      return (lo === null || v >= lo) && (hi === null || v <= hi);
    }
    default: return true;
  }
}

/* The rows that pass the conditions (top to bottom) and the search text.
   `fields` is {key: {label, type, get, text}}. */
function tfApply(rows, state, fields, extraSearch) {
  const conds = state.conditions.filter((c) => tfReady(c, fields[c.field]));
  const q = (state.q || "").trim().toLowerCase();
  if (!conds.length && !q) return rows;
  const keys = Object.keys(fields);
  return rows.filter((row) => {
    let ok = null;
    for (const c of conds) {
      const hit = tfTest(row, c, fields[c.field]);
      ok = ok === null ? hit : c.join === "OR" ? ok || hit : ok && hit;
    }
    if (ok === false) return false;
    if (!q) return true;
    const text = keys.map((k) => tfText(fields[k], row)).concat(extraSearch ? [extraSearch(row)] : []).join("  ").toLowerCase();
    return text.includes(q);
  });
}

/* "Show matching" / "Filter out": replace a lone AND condition on the
   column, otherwise add one, so an OR chain is never rewritten. */
function tfUpsert(state, field, op, value, shown) {
  const same = state.conditions.filter((c) => c.field === field);
  const cond = { field, op, value, shown, join: "AND", exact: true };
  if (same.length === 1 && (same[0].join === "AND" || state.conditions[0] === same[0])) {
    const i = state.conditions.indexOf(same[0]);
    cond.join = same[0].join;
    state.conditions[i] = cond;
  } else {
    state.conditions.push(cond);
  }
}

if (typeof module !== "undefined") module.exports = { TF_OPS, tfNumber, tfTerms, tfReady, tfTest, tfApply, tfUpsert, tableFilter, filterableTable };

/* ---------- controls (browser only; uses h() from app.js) ---------- */

const TF_STATES = {};  // table key -> {conditions, q, open}: kept until the page reloads
const tfState = (key) => (TF_STATES[key] ||= { conditions: [], q: "", open: false });
const tfOp = (id) => TF_OPS.find((o) => o.id === id);
const tfValueText = (c) => (c.op === "between"
  ? `${c.value[0] || "…"} and ${c.value[1] || "…"}` : TF_NO_VALUE.has(c.op) ? "" : (c.shown ?? c.value));
let tfMenuEl = null, tfMenuOpenedAt = 0;

function tfCloseMenu() {
  if (tfMenuEl) { tfMenuEl.remove(); tfMenuEl = null; }
}
if (typeof document !== "undefined") {
  document.addEventListener("click", (e) => { if (tfMenuEl && !tfMenuEl.contains(e.target)) tfCloseMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") tfCloseMenu(); });
  window.addEventListener("scroll", tfCloseMenu, { passive: true });
  window.addEventListener("hashchange", tfCloseMenu);
}

/* One table's filter controls. `fields` is {key: {label, type, get, text}};
   `allRows()` supplies values for the builder's suggestions; `onChange()`
   redraws the table. Returns the pieces to place, apply(rows) and
   attachMenu(table, columnFields, shownRows). */
function tableFilter(key, fields, allRows, onChange, { placeholder = "Search all columns", extraSearch } = {}) {
  const state = tfState(key);
  const keys = Object.keys(fields);
  const search = h("input", { type: "search", class: "tf-search", placeholder, value: state.q, "aria-label": placeholder,
    oninput: (e) => { state.q = e.target.value; onChange(); } });
  const toggle = h("button", { type: "button", class: "tf-toggle", "aria-expanded": String(state.open),
    title: "Filter by any column", onclick: () => { state.open = !state.open; draw(); } });
  const chips = h("div", { class: "tf-chips", role: "group", "aria-label": "Active filters" });
  const builder = h("div", { class: "tf-builder" });
  const changed = (redrawBuilder = true) => { draw(redrawBuilder); onChange(); };

  function distinct(fieldKey) {
    const f = fields[fieldKey], seen = new Set();
    for (const r of allRows()) { const v = f.get(r); if (!tfBlank(v)) seen.add(String(v)); if (seen.size > 300) break; }
    return [...seen].sort((a, b) => a.localeCompare(b));
  }

  function draw(redrawBuilder = true) {
    const active = state.conditions.filter((c) => tfReady(c, fields[c.field])).length;
    toggle.replaceChildren(...[h("span", { "aria-hidden": "true", text: "☰ " }), "Filter", active ? h("span", { class: "tf-n", text: active }) : null].filter(Boolean));
    toggle.setAttribute("aria-expanded", String(state.open));
    toggle.classList.toggle("on", active > 0);
    chips.replaceChildren(...state.conditions.map((c, i) => {
      const f = fields[c.field], ready = tfReady(c, f);
      const label = `${i ? c.join + " " : ""}${f ? f.label : c.field} ${tfOp(c.op).chip} ${tfValueText(c)}`.trim();
      return h("button", { type: "button", class: `tf-chip${ready ? "" : " pending"}`, title: ready ? "Remove this filter" : "Not applied yet: finish it in the filter builder",
        "aria-label": `Remove filter: ${label}`, onclick: () => { state.conditions.splice(i, 1); changed(); } },
      label, h("span", { "aria-hidden": "true", class: "x", text: " ✕" }));
    }), ...(state.conditions.length ? [h("button", { type: "button", class: "link-btn tf-clear", text: "Clear all",
      onclick: () => { state.conditions = []; changed(); } })] : []));
    chips.hidden = !state.conditions.length;
    builder.hidden = !state.open;
    if (state.open && redrawBuilder) drawBuilder();
  }

  function drawBuilder() {
    const listId = (k) => `tf-${key.replace(/[^a-z0-9]/gi, "-")}-${k}`;
    const rows = state.conditions.map((c, i) => {
      const f = fields[c.field] || fields[keys[0]];
      const ops = TF_OPS.filter((o) => o.types.includes(f.type));
      const join = i ? h("select", { class: "tf-join", "aria-label": "Join", onchange: (e) => { c.join = e.target.value; changed(false); } },
        ["AND", "OR"].map((j) => h("option", { value: j, selected: c.join === j, text: j }))) : h("span", { class: "tf-join where", text: "Where" });
      const fieldSel = h("select", { "aria-label": "Column", onchange: (e) => {
        c.field = e.target.value; if (!TF_OPS.find((o) => o.id === c.op).types.includes(fields[c.field].type)) c.op = "=";
        if (c.op === "between" && !Array.isArray(c.value)) c.value = ["", ""];
        delete c.shown; delete c.exact; changed(); } },
      keys.map((k) => h("option", { value: k, selected: k === c.field, text: fields[k].label })));
      const opSel = h("select", { "aria-label": "Condition", onchange: (e) => {
        const was = c.op; c.op = e.target.value;
        if (c.op === "between") c.value = ["", ""]; else if (was === "between") c.value = "";
        delete c.shown; delete c.exact; changed(); } },
      ops.map((o) => h("option", { value: o.id, selected: o.id === c.op, text: o.label })));
      const input = (value, onValue, label) => h("input", { class: "tf-value", value: value ?? "", "aria-label": label,
        placeholder: f.type === "num" ? "e.g. 20" : "e.g. BHP, RIO", list: f.type === "text" ? listId(c.field) : null,
        inputmode: f.type === "num" ? "decimal" : null, oninput: (e) => { onValue(e.target.value); delete c.shown; delete c.exact; changed(false); } });
      let value = null;
      if (c.op === "between") {
        value = h("span", { class: "tf-between" }, input(c.value[0], (v) => { c.value[0] = v; }, "From"), " and ",
          input(c.value[1], (v) => { c.value[1] = v; }, "To"));
      } else if (!TF_NO_VALUE.has(c.op)) {
        value = input(c.shown ?? c.value, (v) => { c.value = v; }, "Value");
      }
      return h("div", { class: "tf-cond" }, join, fieldSel, opSel, value,
        h("button", { type: "button", class: "icon-x", "aria-label": "Remove this condition", text: "✕",
          onclick: () => { state.conditions.splice(i, 1); changed(); } }));
    });
    const textKeys = [...new Set(state.conditions.map((c) => c.field).filter((k) => fields[k] && fields[k].type === "text"))];
    builder.replaceChildren(
      ...rows,
      ...textKeys.map((k) => h("datalist", { id: listId(k) }, distinct(k).map((v) => h("option", { value: v })))),
      h("div", { class: "tf-actions" },
        h("button", { type: "button", class: "btn small", text: "+ Add condition", onclick: () => {
          state.conditions.push({ field: keys[0], op: fields[keys[0]].type === "num" ? ">" : "contains", value: "", join: "AND" }); changed();
          const inputs = builder.querySelectorAll(".tf-value"); if (inputs.length) inputs[inputs.length - 1].focus(); } }),
        ...(state.conditions.length ? [h("button", { type: "button", class: "btn small", text: "Clear all",
          onclick: () => { state.conditions = []; changed(); } })] : []),
        h("span", { class: "hint", text: "Applied top to bottom: A AND B OR C means (A AND B) OR C. Separate several values with commas. " },
          helpLink("table-filters"))));
  }

  function openMenu(x, y, f, row) {
    tfCloseMenu();
    const v = f.get(row), shown = f.type === "num" ? tfText(f, row) : String(v ?? "");  // numbers as shown, text as matched
    const add = (op, value, label) => h("button", { type: "button", role: "menuitem", text: label, onclick: () => {
      tfUpsert(state, Object.keys(fields).find((k) => fields[k] === f), op, value, op === "between" || TF_NO_VALUE.has(op) ? undefined : shown);
      tfCloseMenu(); changed();
    } });
    const value = f.type === "num" ? String(v) : String(v ?? "");
    const short = shown.length > 40 ? shown.slice(0, 39) + "…" : shown;
    const items = tfBlank(v)
      ? [add("is_empty", null, `Show only rows with no ${f.label}`), add("is_not_empty", null, `Hide rows with no ${f.label}`)]
      : [add("=", value, `Show matching: ${f.label} = ${short}`), add("!=", value, `Filter out: ${f.label} ≠ ${short}`),
        f.type === "num" ? add(">", value, `${f.label} greater than ${short}`) : null,
        f.type === "num" ? add("<", value, `${f.label} less than ${short}`) : null];
    tfMenuEl = h("div", { class: "tf-menu", role: "menu", "aria-label": `Filter by ${f.label}` }, items.filter(Boolean));
    document.body.append(tfMenuEl);
    const r = tfMenuEl.getBoundingClientRect();
    tfMenuEl.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`;
    tfMenuEl.style.top = `${Math.max(8, y + r.height > innerHeight - 8 ? y - r.height : y)}px`;
    tfMenuOpenedAt = Date.now();
    tfMenuEl.querySelector("button").focus();
  }

  /* Right-click (or press and hold) a cell. `columnFields[i]` is the field
     key for the table's i-th column (null: not filterable); `shownRows()`
     the rows in the order they're drawn. */
  function attachMenu(table, columnFields, shownRows) {
    const target = (el) => {
      const tr = el.closest("tr");
      if (!tr || !table.tBodies[0] || tr.parentElement !== table.tBodies[0]) return null;
      const td = el.closest("td");
      const k = td ? columnFields[td.cellIndex] : columnFields.find(Boolean);  // keyboard menu key on a row: first column
      const row = shownRows()[tr.sectionRowIndex];
      return k && fields[k] && row ? { f: fields[k], row } : null;
    };
    table.addEventListener("contextmenu", (e) => {
      const t = target(e.target);
      if (!t) return;
      e.preventDefault();
      if (Date.now() - tfMenuOpenedAt < 700) return;  // a phone's long press already opened it
      const box = e.target.getBoundingClientRect();
      openMenu(e.clientX || box.left, e.clientY || box.bottom, t.f, t.row);
    });
    let timer = null, longPressed = false;
    table.addEventListener("touchstart", (e) => {
      const t = target(e.target);
      if (!t || e.touches.length !== 1) return;
      const { clientX, clientY } = e.touches[0];
      longPressed = false;
      timer = setTimeout(() => { longPressed = true; openMenu(clientX, clientY, t.f, t.row); }, 550);
    }, { passive: true });
    const cancel = () => { clearTimeout(timer); timer = null; };
    table.addEventListener("touchmove", cancel, { passive: true });
    table.addEventListener("touchend", cancel);
    table.addEventListener("click", (e) => {  // the tap that ends a long press doesn't open the row
      if (longPressed) { e.preventDefault(); e.stopPropagation(); longPressed = false; }
    }, true);
  }

  draw();
  return { search, toggle, chips, builder, state, attachMenu,
    apply: (rows) => tfApply(rows, state, fields, extraSearch),
    active: () => !!state.q.trim() || state.conditions.some((c) => tfReady(c, fields[c.field])) };
}

/* A whole filterable table for pages that draw a table once (watchlists,
   portfolios): the controls, then `render(rows)`'s table, redrawn on every
   change. `columns` lists each column's field key in order (null: none). */
function filterableTable(key, fields, columns, rows, render, opts) {
  let shown = rows;
  const slot = h("div"), count = h("span", { class: "count" });
  const tf = tableFilter(key, fields, () => rows, draw, opts);
  function draw() {
    shown = tf.apply(rows);
    const el = render(shown);
    slot.replaceChildren(...[el, !shown.length && rows.length ? h("p", { class: "hint tf-none", text: "No rows match these filters." }) : null].filter(Boolean));
    const table = el.querySelector ? el.querySelector("table") : null;
    if (table) tf.attachMenu(table, columns, () => shown);
    count.textContent = tf.active() ? `${shown.length} of ${rows.length}` : "";
  }
  draw();
  const controls = h("div", { class: "controls tf-controls" }, tf.search, tf.toggle, count);
  controls.hidden = rows.length < 2 && !tf.active();  // nothing to filter in a one-row table
  return h("div", { class: "tf-wrap" }, controls, tf.chips, tf.builder, slot);
}
