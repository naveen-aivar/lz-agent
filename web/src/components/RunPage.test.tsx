import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Client } from "../api/client";
import { message, run } from "../test/fixtures";
import { RunPage } from "./RunPage";

const fake = (r: ReturnType<typeof run>) => ({
  getRun: vi.fn().mockResolvedValue({ run: r }),
  getAudit: vi.fn().mockResolvedValue({ audit: [{ SK: "AUDIT#001793248712#abc", action: "transform.answer_sent", actor: "agent", detail: JSON.stringify({ option: "Landing Zone" }) }] }),
  getScope: vi.fn().mockResolvedValue({ scope: { regions: { home: "us-east-1" }, ous: [{ name: "Security" }], accounts: [{ name: "Audit" }] }, sha: "s", orgDiagram: "graph TD" }),
  stopRun: vi.fn().mockResolvedValue({ runId: "r", status: "FAILED" }),
  answerQuestion: vi.fn(), decideTask: vi.fn(),
}) as unknown as Client & { getRun: ReturnType<typeof vi.fn>; stopRun: ReturnType<typeof vi.fn> };

describe("RunPage", () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); });
  afterEach(() => { vi.useRealTimers(); });

  it("shows the status, the waiting question and the activity", async () => {
    const api = fake(run(message()));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={1000} />);
    expect(await screen.findByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AWS Transform needs your input" })).toBeInTheDocument();
    expect(screen.getByText("transform.answer_sent")).toBeInTheDocument();
    expect(screen.getByText("deploy agent")).toBeInTheDocument();
  });

  it("polls while the run is RUNNING and stops once it is done", async () => {
    const api = fake(run(message()));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={1000} />);
    await screen.findByText("RUNNING");
    const calls = api.getRun.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(api.getRun.mock.calls.length).toBeGreaterThan(calls);
    api.getRun.mockResolvedValue({ run: run(undefined, { status: "DELIVERED" }) });
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(await screen.findByText("DELIVERED")).toBeInTheDocument();
    const settled = api.getRun.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(api.getRun.mock.calls.length).toBe(settled);
  });

  it("stops a run only after a second click", async () => {
    const api = fake(run());
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={60000} />);
    (await screen.findByRole("button", { name: "Stop run" })).click();
    expect(api.stopRun).not.toHaveBeenCalled();
    (await screen.findByRole("button", { name: "Yes, stop it" })).click();
    await vi.waitFor(() => expect(api.stopRun).toHaveBeenCalledWith("r"));
  });

  it("shows the error when the run cannot be loaded", async () => {
    const api = fake(run());
    api.getRun.mockRejectedValue(new Error("not found"));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={60000} />);
    expect(await screen.findByText("not found")).toBeInTheDocument();
  });
});
