import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeHost } from "../../test/host";
import { CompanyPage } from "./CompanyPage";
import fixture from "./fixture.json";

// A trimmed answer from the development database: a heavily shorted SELL in
// the Altman distress zone, with one ASX notice.
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

beforeEach(() => { fakeHost(); window.scrollTo = () => undefined; });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("CompanyPage", () => {
  it("leads with the name, action, valuation and caution", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(fixture)));
    const { container } = render(<CompanyPage code="KNF" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Falling Knife Retail Ltd" })).toBeTruthy();
    expect(container.querySelector(".co-head .badge")?.textContent).toBe("SELL");
    expect(container.querySelector(".co-head .pill.under")?.textContent).toBe("Undervalued");
    expect(container.querySelector(".co-head .caution-tag.high")).toBeTruthy();
    expect(screen.getByText(/of KNF's shares are sold short: professional investors are betting/)).toBeTruthy();
  });

  it("draws every card, with the charts and the four value tests", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(fixture)));
    const { container } = render(<CompanyPage code="KNF" />);
    await screen.findByText("Four value tests");
    for (const title of ["Score", "Price against estimated value", "Score breakdown", "Quality and trend markers", "Key ratios",
      "Revenue and net profit", "Financial health", "Short selling", "Director and substantial holder notices", "Workings and what-if"]) {
      expect(screen.getByRole("heading", { level: 2, name: title })).toBeTruthy();
    }
    expect(screen.getByText("Margin of safety: 80.2% (needs above 20%)")).toBeTruthy();
    expect(container.querySelector(".chart.wheel")).toBeTruthy();
    expect(container.querySelectorAll(".chart-slot svg").length).toBeGreaterThan(3);
  });

  it("expands and collapses every spoke of the score", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply(fixture)));
    const { container } = render(<CompanyPage code="KNF" />);
    fireEvent.click(await screen.findByRole("button", { name: "Expand all" }));
    expect([...container.querySelectorAll("details.axis-block:not(.workings-toggle)")].every((d) => (d as HTMLDetailsElement).open)).toBe(true);
    expect(screen.getByRole("button", { name: "Collapse all" })).toBeTruthy();
  });

  it("says what went wrong for an unknown code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reply({ detail: "No company ZZZ" }, 404)));
    render(<CompanyPage code="ZZZ" />);
    expect(await screen.findByText("No company ZZZ")).toBeTruthy();
  });

  it("sends a fund's code to its ETF or LIC page", async () => {
    const replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
    fakeHost({ fundHref: (code) => (code === "VAS" ? "#/etf/VAS" : null) });
    vi.stubGlobal("fetch", vi.fn(async () => reply(fixture)));
    render(<CompanyPage code="VAS" />);
    expect(replace).toHaveBeenCalledWith("#/etf/VAS");
  });
});
