import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { run } from "../test/fixtures";
import { buildResumeRequest, ResumePanel } from "./ResumePanel";

const failed = (over = {}) => run(undefined, { status: "FAILED", error: "Stopped by user.", resumable: true,
  deployTarget: { mode: "keys", accountId: "710507380209" }, ...over });

describe("buildResumeRequest", () => {
  it("sends nothing for a role or platform run and new keys for a keys run", () => {
    expect(buildResumeRequest({ mode: "role", accountId: "1" }, { accessKeyId: "", secretAccessKey: "", sessionToken: "" })).toEqual({});
    expect(buildResumeRequest(null, { accessKeyId: "", secretAccessKey: "", sessionToken: "" })).toEqual({});
    expect(buildResumeRequest({ mode: "keys", accountId: "710507380209" }, { accessKeyId: " AK ", secretAccessKey: " s ", sessionToken: "" }))
      .toEqual({ deployTarget: { accountId: "710507380209", accessKeyId: "AK", secretAccessKey: "s" } });
  });
  it("names what is missing", () => {
    expect(() => buildResumeRequest({ mode: "keys", accountId: "1" }, { accessKeyId: "", secretAccessKey: "", sessionToken: "" })).toThrow("deleted when the run stopped");
    expect(() => buildResumeRequest({ mode: "keys" }, { accessKeyId: "a", secretAccessKey: "b", sessionToken: "" })).toThrow("target account");
  });
});

describe("ResumePanel", () => {
  it("asks for new keys for the recorded account and resumes the same run", async () => {
    const api = { resumeRun: vi.fn().mockResolvedValue({ runId: "x" }) };
    const onResumed = vi.fn();
    render(<ResumePanel run={failed()} api={api} onResumed={onResumed} />);
    expect(screen.getByText("710507380209")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Resume run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Access key ID and secret are required");
    expect(api.resumeRun).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Access key ID"), "AKIAX");
    await user.type(screen.getByLabelText("Secret access key"), "sekret");
    await user.click(screen.getByRole("button", { name: "Resume run" }));
    await waitFor(() => expect(api.resumeRun).toHaveBeenCalledWith(failed().runId, {
      deployTarget: { accountId: "710507380209", accessKeyId: "AKIAX", secretAccessKey: "sekret" } }));
    expect(onResumed).toHaveBeenCalled();
  });

  it("resumes a role run with one click and no key fields", async () => {
    const api = { resumeRun: vi.fn().mockResolvedValue({ runId: "x" }) };
    render(<ResumePanel run={failed({ deployTarget: { mode: "role", accountId: "1" } })} api={api} onResumed={() => {}} />);
    expect(screen.queryByLabelText("Access key ID")).toBeNull();
    await userEvent.setup().click(screen.getByRole("button", { name: "Resume run" }));
    await waitFor(() => expect(api.resumeRun).toHaveBeenCalledWith(failed().runId, {}));
  });

  it("shows the API's reason when the resume is refused", async () => {
    const api = { resumeRun: vi.fn().mockRejectedValue(new Error("run is no longer FAILED (it may already have been resumed)")) };
    render(<ResumePanel run={failed({ deployTarget: { mode: "role", accountId: "1" } })} api={api} onResumed={() => {}} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Resume run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already have been resumed");
  });

  it("shows nothing when the API does not say whether the run can continue", () => {
    const { container } = render(<ResumePanel run={failed({ resumable: undefined })} api={{ resumeRun: vi.fn() }} onResumed={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says there is nothing to continue when the run recorded no progress", () => {
    render(<ResumePanel run={failed({ resumable: false })} api={{ resumeRun: vi.fn() }} onResumed={() => {}} />);
    expect(screen.getByTestId("not-resumable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resume run" })).toBeNull();
  });
});
