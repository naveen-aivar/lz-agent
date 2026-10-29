import { describe, expect, it } from "vitest";
import { buildDeployRequest } from "./DeployDialog";

const base = { method: "role" as const, accountId: "710507380209", roleArn: "arn:aws:iam::710507380209:role/R", externalId: "ext",
  accessKeyId: "", secretAccessKey: "", sessionToken: "", accountEmail: "", targetRegion: "" };

describe("buildDeployRequest", () => {
  it("builds a role request with the optional email and Region", () => {
    expect(buildDeployRequest({ ...base, accountEmail: " billu.naveen@aivar.tech ", targetRegion: "us-east-1" })).toEqual({
      deployTarget: { accountId: "710507380209", roleArn: "arn:aws:iam::710507380209:role/R", externalId: "ext" },
      accountEmail: "billu.naveen@aivar.tech", targetRegion: "us-east-1",
    });
  });
  it("builds a keys request and only includes a session token when given", () => {
    const keys = { ...base, method: "keys" as const, accessKeyId: "AKIA", secretAccessKey: "s" };
    expect(buildDeployRequest(keys).deployTarget).toEqual({ accountId: "710507380209", accessKeyId: "AKIA", secretAccessKey: "s" });
    expect(buildDeployRequest({ ...keys, sessionToken: "t" }).deployTarget?.sessionToken).toBe("t");
  });
  it("sends no target for the platform account", () => {
    expect(buildDeployRequest({ ...base, method: "platform", accountId: "" })).toEqual({});
  });
  it("names what is wrong", () => {
    expect(() => buildDeployRequest({ ...base, accountId: "123" })).toThrow("12 digits");
    expect(() => buildDeployRequest({ ...base, roleArn: "" })).toThrow("Role ARN");
    expect(() => buildDeployRequest({ ...base, externalId: "" })).toThrow("External ID");
    expect(() => buildDeployRequest({ ...base, method: "keys" })).toThrow("Access key ID and secret");
    for (const bad of ["billu+audit@aivar.tech", "no-at", "a@b"]) {
      expect(() => buildDeployRequest({ ...base, accountEmail: bad })).toThrow("Account email");
    }
  });
});
