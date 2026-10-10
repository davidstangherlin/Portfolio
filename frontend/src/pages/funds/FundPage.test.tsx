import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeHost } from "../../test/host";
import fixture from "./fund.fixture.json";
import { FundPage } from "./FundPage";

const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

beforeEach(() => { fakeHost(); window.scrollTo = () => undefined; vi.stubGlobal("fetch", vi.fn(async () => reply(fixture))); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("FundPage", () => {
  it("shows the fund's figures and every card", async () => {
    render(<FundPage kind="ETF" code="VAS" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Vanguard Australian Shares Index ETF" })).toBeTruthy();
    for (const title of ["Performance", "What it holds", "Growth of $10,000", "Unit price, last 12 months", "Fund facts"]) {
      expect(screen.getByRole("heading", { level: 2, name: title })).toBeTruthy();
    }
    expect(screen.getByLabelText("Reference fund")).toBeTruthy();
  });

  it("switches the growth period", async () => {
    const { container } = render(<FundPage kind="ETF" code="VAS" />);
    fireEvent.click(await screen.findByRole("button", { name: "1 year" }));
    expect(container.querySelector("button[data-period='1y']")?.getAttribute("aria-pressed")).toBe("true");
  });

  it("asks for the comparison in the address", async () => {
    render(<FundPage kind="ETF" code="VAS" />);
    const pick = await screen.findByLabelText("Reference fund");
    const other = [...pick.querySelectorAll("option")].map((o) => o.getAttribute("value")).find((v) => v !== (pick as HTMLSelectElement).value) as string;
    fireEvent.change(pick, { target: { value: other } });
    expect(location.hash).toBe(`#/etf/VAS?compare=${other}`);
  });
});
