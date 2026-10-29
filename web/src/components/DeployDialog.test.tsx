import { describe, expect, it } from "vitest";
import { buildDeployRequest } from "./DeployDialog";

const base = { method: "role" as const, accountId: "710507380209", roleArn: "arn:aws:iam::710507380209:role/R", externalId: "ext",
  accessKeyId: "", secretAccessKey: "", sessionToken: "", accountEmail: "", mapAgreement: "", targetRegion: "", applyScps: true };

describe("buildDeployRequest", () => {
  it("builds a role request with the optional email and Region", () => {
    expect(buildDeployRequest({ ...base, accountEmail: " billu.naveen@aivar.tech ", targetRegion: "us-east-1" })).toEqual({
      deployTarget: { accountId: "710507380209", roleArn: "arn:aws:iam::710507380209:role/R", externalId: "ext" },
      accountEmail: "billu.naveen@aivar.tech", targetRegion: "us-east-1", applyScps: true,
    });
  });
  it("builds a keys request and only includes a session token when given", () => {
    const keys = { ...base, method: "keys" as const, accessKeyId: "AKIA", secretAccessKey: "s" };
    expect(buildDeployRequest(keys).deployTarget).toEqual({ accountId: "710507380209", accessKeyId: "AKIA", secretAccessKey: "s" });
    expect(buildDeployRequest({ ...keys, sessionToken: "t" }).deployTarget?.sessionToken).toBe("t");
  });
  it("accepts none or a full MAP tag and refuses anything else", () => {
    expect(buildDeployRequest({ ...base, mapAgreement: " none " }).mapAgreement).toBe("none");
    expect(buildDeployRequest({ ...base, mapAgreement: "migABCDE12345" }).mapAgreement).toBe("migABCDE12345");
    expect(buildDeployRequest({ ...base, mapAgreement: "" })).not.toHaveProperty("mapAgreement");
    for (const bad of ["12345", "mig", "yes", "MIG123", "mig 123", "mig-123"]) {
      expect(() => buildDeployRequest({ ...base, mapAgreement: bad })).toThrow("MAP agreement");
    }
  });
  it("sends no target for the platform account", () => {
    expect(buildDeployRequest({ ...base, method: "platform", accountId: "" })).toEqual({ applyScps: true });
  });
  it("sends the SCP choice either way, so an unticked box means skip, not unknown", () => {
    expect(buildDeployRequest({ ...base, applyScps: true }).applyScps).toBe(true);
    expect(buildDeployRequest({ ...base, applyScps: false }).applyScps).toBe(false);
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
