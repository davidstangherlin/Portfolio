/* Dashboard layout (docs/AS_BUILT.md §20): your widget order, hidden widgets
   and widths, saved in Sift's database so every browser shows the same.
   Every widget starts pinned. Its pin unlocks it: drag it by its title bar
   (mouse or finger), or use the arrows, switch it between half and full
   width, or hide it. Click the pin again to lock it.

   The first part is pure (no page), for tests/js/dash_layout.test.js; the
   rest uses app.js's h(), s() and send(). */

/* `primary` in its own order, then each id of `reference` it lacks, placed
   straight after the nearest id before it in `reference` (or first). Keeps
   new widgets, and ones not shown today, where they belong. */
function dlMerge(primary, reference) {
  const out = [...new Set(primary)];
  reference.forEach((id, i) => {
    if (out.includes(id)) return;
    let at = 0;
    for (let j = i - 1; j >= 0; j--) {
      const k = out.indexOf(reference[j]);
      if (k >= 0) { at = k + 1; break; }
    }
    out.splice(at, 0, id);
  });
  return out;
}

/* One entry per known widget, in the saved order (widgets Sift no longer
   has are dropped; new ones take their default place). */
function dlArrange(saved, defaults) {
  const byId = new Map();
  for (const c of (saved && saved.cards) || []) if (defaults.includes(c.id) && !byId.has(c.id)) byId.set(c.id, c);
  return dlMerge([...byId.keys()], defaults).map((id) => ({ hidden: false, wide: null, ...(byId.get(id) || {}), id }));
}

if (typeof module !== "undefined") module.exports = { dlMerge, dlArrange };

/* ---------- on the page ---------- */
const dlPinIcon = () => s("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2,
  "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" },
  s("line", { x1: 12, x2: 12, y1: 17, y2: 22 }),
  s("path", { d: "M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z" }));

/* The dashboard's widgets, arranged. `specs` lists each widget in its
   default order: { id, title, build() } where build returns its card, or
   null when it has nothing to show today. Returns [grid, footer]. */
function dashboardLayout(d, specs) {
  const defaults = specs.map((x) => x.id);
  const title = (id) => specs.find((x) => x.id === id).title;
  let entries = dlArrange(d.layout, defaults);
  const unlocked = new Set();  // unpinned this visit; every widget is pinned when the page loads
  const cards = new Map();
  for (const x of specs) {
    const el = x.build();
    if (!el) continue;
    el.dataset.card = x.id;
    el.dataset.defaultWide = el.classList.contains("wide");
    addTools(el, x.id);
    cards.set(x.id, el);
  }
  const grid = h("div", { class: "cards dash" });
  const msg = h("span", { class: "form-msg", role: "status", "aria-live": "polite" });
  const foot = h("div", { class: "dl-foot" });
  let saving = Promise.resolve();

  function save() {
    const layout = { cards: entries.map(({ id, hidden, wide }) => ({ id, hidden, wide })) };
    d.layout = layout;
    saving = saving.then(() => send("PUT", "/api/dashboard/layout", layout))
      .then(() => { msg.textContent = ""; })
      .catch((err) => showMessage(msg, `Layout not saved: ${err.message}`, false));
  }
  const entry = (id) => entries.find((e) => e.id === id);
  const shownIds = () => [...grid.children].map((c) => c.dataset.card);
  function reorder(visible) {
    const ids = dlMerge(visible, entries.map((e) => e.id));
    entries = ids.map(entry);
  }

  function addTools(el, id) {
    const pin = h("button", { type: "button", class: "dl-btn dl-pin" }, dlPinIcon());
    const btn = (cls, text, label, fn) => h("button", { type: "button", class: `dl-btn ${cls}`, text, title: label, "aria-label": `${label}: ${title(id)}`, onclick: fn });
    const width = btn("dl-width", "", "", () => {
      const e = entry(id);
      e.wide = !el.classList.contains("wide");
      save(); paint(); el.querySelector(".dl-width").focus();
    });
    const bar = h("div", { class: "dl-bar" },
      h("span", { class: "dl-grip", "aria-hidden": "true", text: "⠿ Drag to move" }),
      btn("dl-up", "↑", "Move up", () => move(id, -1)), btn("dl-down", "↓", "Move down", () => move(id, 1)),
      width, btn("dl-hide", "Hide", "Hide", () => { entry(id).hidden = true; unlocked.delete(id); save(); paint(); }));
    pin.addEventListener("click", () => {
      unlocked.has(id) ? unlocked.delete(id) : unlocked.add(id);
      state(el, id);
    });
    for (const handle of [bar, el.querySelector("h2")]) handle && handle.addEventListener("pointerdown", (e) => drag(e, el, id));
    el.prepend(pin, bar);
  }
  function state(el, id) {
    const open = unlocked.has(id), wide = el.classList.contains("wide");
    el.classList.toggle("dl-open", open);
    const pin = el.querySelector(".dl-pin");
    pin.setAttribute("aria-pressed", String(!open));
    pin.title = open ? "Unlocked: drag to move. Click to pin it in place." : "Pinned. Click to unlock and move, resize or hide.";
    pin.setAttribute("aria-label", `${open ? "Pin" : "Unpin"} ${title(id)}`);
    const w = el.querySelector(".dl-width");
    w.textContent = wide ? "Half width" : "Full width";
    w.title = wide ? "Make it half width" : "Make it full width";
    w.setAttribute("aria-label", `${w.title}: ${title(id)}`);
  }
  function move(id, step) {
    const ids = shownIds(), i = ids.indexOf(id), j = i + step;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder(ids); save(); paint();
    cards.get(id).querySelector(step < 0 ? ".dl-up" : ".dl-down").focus();
  }
  function drag(e, el, id) {
    if (!unlocked.has(id) || e.button > 0 || e.target.closest("button, a, input, select")) return;
    e.preventDefault();
    // Followed on the window, not the title bar: moving the widget in the page
    // ends the browser's capture of the pointer, which would stop the drag.
    const pointer = e.pointerId, before = shownIds().join();
    el.classList.add("dl-dragging");
    document.documentElement.classList.add("dl-drag-on");
    const onMove = (ev) => {
      if (ev.pointerId !== pointer) return;
      const over = document.elementsFromPoint(ev.clientX, ev.clientY)
        .map((x) => x.closest && x.closest(".cards.dash > .card")).find((c) => c && c !== el);
      if (over) {
        const kids = [...grid.children], top = el.getBoundingClientRect().top;
        kids.indexOf(over) > kids.indexOf(el) ? over.after(el) : over.before(el);
        const shift = el.getBoundingClientRect().top - top;  // keep it under the pointer: the page moves, not the widget
        if (shift) scrollBy(0, shift);
      }
      if (ev.clientY < 70) scrollBy(0, -14); else if (ev.clientY > innerHeight - 50) scrollBy(0, 14);
    };
    const onUp = (ev) => {
      if (ev.pointerId !== pointer) return;
      removeEventListener("pointermove", onMove);
      removeEventListener("pointerup", onUp);
      removeEventListener("pointercancel", onUp);
      el.classList.remove("dl-dragging");
      document.documentElement.classList.remove("dl-drag-on");
      if (shownIds().join() !== before) { reorder(shownIds()); save(); paint(); }
    };
    addEventListener("pointermove", onMove);
    addEventListener("pointerup", onUp);
    addEventListener("pointercancel", onUp);
  }

  function paint() {
    const shown = entries.filter((e) => !e.hidden && cards.has(e.id));
    for (const e of shown) {
      const el = cards.get(e.id);
      el.classList.toggle("wide", e.wide === null ? el.dataset.defaultWide === "true" : e.wide);
      state(el, e.id);
    }
    grid.replaceChildren(...shown.map((e) => cards.get(e.id)));
    const hidden = entries.filter((e) => e.hidden && cards.has(e.id));
    foot.replaceChildren(
      h("span", { text: "Layout: click a widget's pin to move, resize or hide it." }),
      hidden.length ? h("span", { class: "dl-hidden" }, "Hidden: ", hidden.map((e) =>
        h("button", { type: "button", class: "dl-btn dl-show", text: `Show ${title(e.id)}`,
          onclick: () => { e.hidden = false; save(); paint(); } }))) : null,
      d.layout ? h("button", { type: "button", class: "dl-btn dl-reset", text: "Reset to default layout", onclick: async () => {
        if (!confirm("Put the dashboard back to its default order, widths and widgets?")) return;
        try {
          await saving;
          await send("DELETE", "/api/dashboard/layout");
          d.layout = null; entries = dlArrange(null, defaults); unlocked.clear(); paint();
        } catch (err) { showMessage(msg, err.message, false); }
      } }) : null,
      msg);
  }
  paint();
  return [grid, foot];
}
