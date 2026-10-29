import { describe, expect, it } from "vitest";
import { statusTone } from "./status";

describe("statusTone", () => {
  it("colours the known statuses", () => {
    expect(["DELIVERED", "RUNNING", "AWAITING_INPUT", "FAILED"].map(statusTone)).toEqual(["green", "blue", "amber", "red"]);
  });
  it("shows anything else neutral, never green", () => {
    expect(statusTone("SOMETHING_NEW")).toBe("muted");
    expect(statusTone("")).toBe("muted");
  });
});
