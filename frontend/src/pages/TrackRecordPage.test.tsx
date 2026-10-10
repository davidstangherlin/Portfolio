import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TrackRecord } from "../lib/types";
import { fakeHost } from "../test/host";
import { TrackRecordPage } from "./TrackRecordPage";

const test = { kind: "BEATING", label: "Beating the average", intended: true, low: 1.2, high: 9.8, t: 3.1, p_value: 0.002, q_value: 0.01, luck: "about a 1 in 100 chance", min_calls: 30, level: 0.99 };
const d: TrackRecord = {
  horizons: [1, 3],
  verdict: {
    1: { actions: [], order: { status: "too early" } },
    3: { actions: [{ action: "BUY", signals: 120, avg_excess: 5.5, beat_rate: 64, test }], order: { status: "in order" } },
  },
  monthly: [{ month: "2026-06-01", action: "BUY", horizon_months: 3, avg_excess: 4.25, signals: 12 }],
  status: { first_date: "2026-01-01", days_recorded: 200, signals_recorded: 5000, results_due: [{ months: 1, date: "2026-02-01" }] },
  rules: { too_early_below: 30, solid_above: 100, margin_of_safety: 20, purchase_window_days: 30, missed_excess: 10 },
  actionable: { new: [{ asx_code: "GEM", company_name: "G8", action: "BUY", price_then: 2, price_now: 2.5, value_then: 3, margin_of_safety_now: 25, watchlists: ["Core"] }], open: [], moved_on: [] },
  proven: { proven: false, horizon: 3, actions: ["BUY"] },
  missed: [], saved: [], version: null,
};

beforeEach(() => {
  fakeHost();
  window.scrollTo = () => undefined;
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(d), { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("TrackRecordPage", () => {
  it("shows each action's verdict in words, at 3 months by default", async () => {
    render(<TrackRecordPage />);
    expect(await screen.findByText(/BUY calls beat the average screened share by 5.5 points over 3 months; 64% of 120 beat it/)).toBeTruthy();
    expect(screen.getByText("Beating the average")).toBeTruthy();
    expect(screen.getByText(/In order: BUY beat WATCH/)).toBeTruthy();
    expect(screen.getByText("+4.3 (12)")).toBeTruthy();
    expect(screen.getByText("New this week (1)")).toBeTruthy();
    expect(screen.getByTitle("On watchlist: Core")).toBeTruthy();
  });

  it("switches period", async () => {
    render(<TrackRecordPage />);
    fireEvent.click(await screen.findByRole("button", { name: "1 month" }));
    expect(screen.getByText(/Results start once signals|First 1-month results/)).toBeTruthy();
  });

  it("shows admins the exact figures", async () => {
    fakeHost({ isAdmin: () => true });
    render(<TrackRecordPage />);
    fireEvent.click(await screen.findByRole("button", { name: "3 months" }));  // the period is remembered between visits
    expect(screen.getByText(/Admin: BUY t = 3.10, p = 0.002, adjusted 0.010, 99.0% \+1.2 pts to \+9.8 pts/)).toBeTruthy();
  });
});
