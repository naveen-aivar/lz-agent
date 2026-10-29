import { describe, expect, it } from "vitest";
import { ago, isDone, pretty, stateOf } from "./format";

describe("format", () => {
  it("words the known states as the UI words them", () => {
    expect(["DELIVERED", "RUNNING", "AWAITING_INPUT", "FAILED"].map((s) => stateOf(s))).toEqual([
      ["green", "Ready to download"], ["amber", "In progress"], ["blue", "Starting"], ["red", "Failed"]]);
  });
  it("shows an unknown state as is and neutral, never green", () => {
    expect(stateOf("SOMETHING_NEW")).toEqual(["muted", "SOMETHING_NEW"]);
  });
  it("capitalises customer ids", () => {
    expect(pretty("getsetyo-tech")).toBe("Getsetyo Tech");
    expect(pretty(null)).toBe("");
  });
  it("words elapsed time", () => {
    const now = 1_000_000_000_000;
    const at = (s: number) => now / 1000 - s;
    expect([30, 90, 7200, 200000].map((s) => ago(at(s), now))).toEqual(["just now", "1 min ago", "2 h ago", "2d ago"]);
  });
  it("knows which statuses are final", () => {
    expect([isDone("DELIVERED"), isDone("FAILED"), isDone("RUNNING")]).toEqual([true, true, false]);
  });
});
