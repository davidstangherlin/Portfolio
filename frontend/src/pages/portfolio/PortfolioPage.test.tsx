import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeHost } from "../../test/host";
import { PortfolioPage } from "./PortfolioPage";
import fixture from "./portfolio.fixture.json";

const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
let posted: unknown[] = [];

beforeEach(() => {
  fakeHost(); window.scrollTo = () => undefined; Element.prototype.scrollIntoView = () => undefined; posted = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") { posted.push([url, JSON.parse(String(init.body))]); return reply({ units: 10, asx_code: "BHP", cost_base: 455, discount_from: "2027-10-11" }); }
    return reply(fixture);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("PortfolioPage", () => {
  it("shows holdings by kind and the parcels", async () => {
    render(<PortfolioPage id="x" />);
    expect(await screen.findByRole("heading", { level: 1, name: "My portfolio" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Shares" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "ETFs" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "Open parcels" })).toBeTruthy();
  });

  it("records a buy and says what was recorded", async () => {
    const { container } = render(<PortfolioPage id="x" />);
    await screen.findByRole("heading", { level: 1, name: "My portfolio" });
    const form = container.querySelector(".card form") as HTMLFormElement;
    fireEvent.change(form.querySelector("input[name=asx_code]")!, { target: { value: "BHP" } });
    fireEvent.change(form.querySelector("input[name=units]")!, { target: { value: "10" } });
    fireEvent.submit(form);
    expect(await screen.findByText(/Recorded: 10 BHP, cost base \$455.00/)).toBeTruthy();
    expect(posted[0]).toEqual(["/api/portfolios/7981c813-92a4-4793-8cac-7f6c378e7991/buys", expect.objectContaining({ asx_code: "BHP", units: "10", method: "PURCHASE" })]);
  });

  it("offers only held shares to sell", async () => {
    render(<PortfolioPage id="x" />);
    fireEvent.click(await screen.findByRole("button", { name: "Sell" }));
    const pick = screen.getByRole("button", { name: "Record sale" }).closest("form")!.querySelector("select[name=asx_code]") as HTMLSelectElement;
    expect([...pick.options].map((o) => o.value)).toEqual(fixture.positions.map((p) => p.asx_code));
  });
});
