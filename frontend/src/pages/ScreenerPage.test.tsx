import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invalidate } from "../lib/cache";
import { fakeHost } from "../test/host";
import fixture from "./screener.fixture.json";
import { ScreenerPage } from "./ScreenerPage";

const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const codes = (c: HTMLElement) => [...c.querySelectorAll("tbody .code")].map((x) => x.textContent);

beforeEach(() => { fakeHost(); invalidate(); vi.stubGlobal("fetch", vi.fn(async () => reply(fixture))); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ScreenerPage", () => {
  it("lists every company, sorted by action, with a count", async () => {
    const { container } = render(<ScreenerPage query="" />);
    expect(await screen.findByText("6 shown")).toBeTruthy();
    expect(codes(container)[0]).toBe("KNF");  // SELL comes first in the actions' order
  });

  it("opens with just the actions a link asks for", async () => {
    const { container } = render(<ScreenerPage query="action=INVESTIGATE" />);
    expect(await screen.findByText("2 shown")).toBeTruthy();
    expect(codes(container).sort()).toEqual(["NZP", "REI"]);
  });

  it("searches any column and sorts by a heading", async () => {
    const { container } = render(<ScreenerPage query="" />);
    fireEvent.change(await screen.findByLabelText("Search any column"), { target: { value: "utilities" } });
    expect(codes(container)).toEqual(["NZP"]);
    fireEvent.change(screen.getByLabelText("Search any column"), { target: { value: "" } });
    fireEvent.click(container.querySelector("th[data-sort=asx_code]") as Element);
    expect(codes(container)).toEqual(["BNK", "GEM", "KNF", "MNR", "NZP", "REI"]);
    expect(container.querySelector("th[data-sort=asx_code]")?.getAttribute("aria-sort")).toBe("ascending");
  });

  it("filters by a condition from the builder", async () => {
    const { container } = render(<ScreenerPage query="" />);
    fireEvent.click(await screen.findByRole("button", { name: /Filter/ }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add condition" }));
    fireEvent.change(screen.getByLabelText("Column"), { target: { value: "action" } });
    fireEvent.change(screen.getByLabelText("Condition"), { target: { value: "=" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "BUY, SELL" } });
    expect(codes(container).sort()).toEqual(["KNF", "MNR"]);
    expect(screen.getByRole("button", { name: /Remove filter: Action = BUY, SELL/ })).toBeTruthy();
  });
});
