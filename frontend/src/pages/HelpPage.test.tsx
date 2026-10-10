import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fakeHost } from "../test/host";
import { HelpPage } from "./HelpPage";

const kb = {
  categories: [{ id: "valuation", name: "Valuation" }, { id: "track", name: "Track record" }],
  entries: [
    { id: "mos", title: "Margin of safety", category: "valuation", definition: "How far below value.", hover: "Passes above {margin_of_safety}%.",
      body: ["First paragraph."], related: ["luck"], links: [{ text: "A paper", href: "https://example.org" }], aliases: ["mos"] },
    { id: "luck", title: "Is each rule working?", category: "track", definition: "More than luck?" },
  ],
};

beforeEach(() => { fakeHost({}, kb); window.scrollTo = () => undefined; });
afterEach(cleanup);

describe("HelpPage", () => {
  it("groups entries by topic and counts them", () => {
    render(<HelpPage query="" />);
    expect(screen.getByText("2 of 2")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Valuation" })).toBeTruthy();
  });

  it("searches, opens a short list of results and fills in thresholds", () => {
    const { container } = render(<HelpPage query="q=margin" />);
    expect(screen.getByText("1 of 2")).toBeTruthy();
    expect(container.querySelector("details.help-entry")?.hasAttribute("open")).toBe(true);
    expect(screen.getByText("Passes above 20%.")).toBeTruthy();
    expect(screen.getByText("A paper ↗").getAttribute("target")).toBe("_blank");
  });

  it("filters by topic chip", () => {
    render(<HelpPage query="" />);
    fireEvent.click(screen.getByRole("button", { name: "Track record" }));
    expect(screen.getByText("1 of 2")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search help"), { target: { value: "zzz" } });
    expect(screen.getByText(/Nothing matches "zzz"/)).toBeTruthy();
  });
});
