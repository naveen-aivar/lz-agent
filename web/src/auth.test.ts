import { describe, expect, it } from "vitest";
import { canAnswerTransform, groupsOf, isExpired } from "./auth";

describe("auth claims", () => {
  it("reads groups as an array or as the HTTP API string form", () => {
    expect(groupsOf({ "cognito:groups": ["a", "transform-approvers"] })).toEqual(["a", "transform-approvers"]);
    expect(groupsOf({ "cognito:groups": "[admins transform-approvers]" })).toEqual(["admins", "transform-approvers"]);
    expect(groupsOf({})).toEqual([]);
  });
  it("lets only approver-group members answer", () => {
    expect(canAnswerTransform({ "cognito:groups": ["transform-approvers"] })).toBe(true);
    expect(canAnswerTransform({ "cognito:groups": ["other"] })).toBe(false);
    expect(canAnswerTransform({})).toBe(false);
  });
  it("treats a token that expires within 30 s, or has no exp, as expired", () => {
    const now = 1_000_000_000_000;
    expect(isExpired({ exp: now / 1000 + 3600 }, now)).toBe(false);
    expect(isExpired({ exp: now / 1000 + 10 }, now)).toBe(true);
    expect(isExpired({}, now)).toBe(true);
  });
});
