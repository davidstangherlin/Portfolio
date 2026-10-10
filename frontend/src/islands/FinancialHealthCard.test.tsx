import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Health } from "../lib/types";
import { FinancialHealthCard } from "./FinancialHealthCard";

const base: Health = {
  fiscal_year: 2026, excluded_reason: null, f_score: 8, f_checks: 9, f_level: "STRONG", f_words: "Strong",
  f_detail: [
    { key: "profit", label: "Made a profit", rule: "r", passed: true },
    { key: "margin_up", label: "Gross margin improved", rule: "r", passed: false },
    { key: "no_new_shares", label: "No new shares issued", rule: "r", passed: null },
  ],
  z_score: 3.42, z_zone: "SAFE", z_words: "Safe zone", z_meaning: "Low risk of financial distress on these figures.", z_parts: {},
};

afterEach(cleanup);

describe("FinancialHealthCard", () => {
  it("leads with the score and its word, then each check", () => {
    render(<FinancialHealthCard code="GEM" health={base} />);
    expect(screen.getByText("Strong")).toBeTruthy();
    expect(screen.getByText(/GEM passed 8 of the 9 checks/)).toBeTruthy();
    expect(screen.getByText("No new shares issued (no data)")).toBeTruthy();
    expect(screen.getByText("Safe zone")).toBeTruthy();
    expect(screen.getByText("GEM 3.4")).toBeTruthy();
  });

  it("says plainly when there isn't enough data", () => {
    render(<FinancialHealthCard code="NEW" health={{ ...base, f_level: "NOT_ENOUGH", f_words: "Not enough data yet", f_checks: 4, z_zone: null, z_score: null }} />);
    expect(screen.getByText(/Not enough data yet: Sift could make 4 of the 9 checks/)).toBeTruthy();
    expect(screen.getByText(/Needs current assets/)).toBeTruthy();
  });

  it("explains why banks aren't scored", () => {
    render(<FinancialHealthCard code="CBA" health={{ ...base, excluded_reason: "banks, insurers and other financial companies" }} />);
    expect(screen.getByText(/weren't designed for banks/)).toBeTruthy();
  });

  it("marks the distress zone as a warning", () => {
    const { container } = render(<FinancialHealthCard code="KNF" health={{ ...base, z_score: 1.2, z_zone: "DISTRESS", z_words: "Distress zone" }} />);
    expect(container.querySelector(".vpill.bad")?.textContent).toContain("Distress zone");
    expect(container.querySelector(".zone-scale li.here")?.textContent).toContain("KNF 1.2");
  });
});
