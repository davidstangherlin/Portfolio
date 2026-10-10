import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeHost } from "../../test/host";
import { DashboardPage } from "./DashboardPage";
import fixture from "./dashboard.fixture.json";

const reply = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const order = (c: HTMLElement) => [...c.querySelectorAll(".cards.dash > [data-card]")].map((x) => (x as HTMLElement).dataset.card);
let calls: [string, RequestInit | undefined][] = [];

beforeEach(() => {
  fakeHost(); window.scrollTo = () => undefined; calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => { calls.push([url, init]); return reply(url === "/api/dashboard" ? structuredClone(fixture) : {}); }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("DashboardPage", () => {
  it("shows every widget in the default order, pinned", async () => {
    const { container } = render(<DashboardPage />);
    expect(await screen.findByRole("heading", { level: 2, name: "Needs attention" })).toBeTruthy();
    expect(order(container).slice(0, 2)).toEqual(["attention", "changes"]);
    expect(container.querySelectorAll(".dl-pin[aria-pressed=true]").length).toBe(order(container).length);
    expect(container.querySelector(".dl-reset")).toBeNull();
  });

  it("moves, hides and shows a widget, and saves the layout", async () => {
    const { container } = render(<DashboardPage />);
    await screen.findByRole("heading", { level: 2, name: "Needs attention" });
    fireEvent.click(screen.getByRole("button", { name: "Unpin Needs attention" }));
    fireEvent.click(screen.getByRole("button", { name: "Move down: Needs attention" }));
    expect(order(container).slice(0, 2)).toEqual(["changes", "attention"]);
    fireEvent.click(screen.getByRole("button", { name: "Hide: Needs attention" }));
    expect(order(container)).not.toContain("attention");
    expect(screen.getByRole("button", { name: "Show Needs attention" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reset to default layout" })).toBeTruthy();
    await Promise.resolve();
    expect(calls.some(([url, init]) => url === "/api/dashboard/layout" && init?.method === "PUT")).toBe(true);
  });
});
