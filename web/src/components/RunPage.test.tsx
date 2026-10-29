import React from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Client } from "../api/client";
import { SCOPE, message, run } from "../test/fixtures";
import { ToastProvider } from "../ui/Toasts";
import { RunPage as Page } from "./RunPage";
const RunPage = (p: React.ComponentProps<typeof Page>) => <ToastProvider><Page {...p} /></ToastProvider>;

const fake = (r: ReturnType<typeof run>) => ({
  getRun: vi.fn().mockResolvedValue({ run: r }),
  getAudit: vi.fn().mockResolvedValue({ audit: [{ SK: "AUDIT#001793248712#abc", ts: 1793248712, action: "transform.answer_sent", actor: "agent", detail: JSON.stringify({ option: "Landing Zone" }) }] }),
  getScope: vi.fn().mockResolvedValue({ scope: SCOPE, sha: "s", orgDiagram: "graph TD" }),
  stopRun: vi.fn().mockResolvedValue({ runId: "r", status: "FAILED" }),
  answerQuestion: vi.fn(), decideTask: vi.fn(),
}) as unknown as Client & { getRun: ReturnType<typeof vi.fn>; stopRun: ReturnType<typeof vi.fn> };

describe("RunPage", () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }); });
  afterEach(() => { vi.useRealTimers(); });

  it("shows the status, the waiting question and the activity", async () => {
    const api = fake(run(message()));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={1000} />);
    expect(await screen.findByText("In progress")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AWS Transform needs your input" })).toBeInTheDocument();
    expect(screen.getByText("Progress")).toBeInTheDocument();
    expect(screen.getByText("Build with AWS Transform")).toBeInTheDocument();
    expect(screen.getAllByText("Deploy agent answered “Landing Zone”").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "← Projects" })).toHaveAttribute("href", "#/runs");
  });

  it("polls while the run is RUNNING and stops once it is done", async () => {
    const api = fake(run(message()));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={1000} />);
    await screen.findByText("In progress");
    const calls = api.getRun.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(api.getRun.mock.calls.length).toBeGreaterThan(calls);
    api.getRun.mockResolvedValue({ run: run(undefined, { status: "DELIVERED" }) });
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(await screen.findByText("Ready to download")).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
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

  it("tells the page the name of the run for the breadcrumb", async () => {
    const onCrumb = vi.fn();
    render(<RunPage runId="r" api={fake(run(undefined, { customerId: "getsetyo-tech" }))} canAnswer userSub="me" pollMs={60000} onCrumb={onCrumb} />);
    await screen.findByText("Getsetyo Tech");
    expect(onCrumb).toHaveBeenCalledWith("Getsetyo Tech deploy");
  });

  it("says Reconnecting when a refresh fails after the page loaded", async () => {
    const api = fake(run(message()));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={1000} />);
    await screen.findByText("Live");
    api.getRun.mockRejectedValue(new Error("network down"));
    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    expect(await screen.findByText("Reconnecting…")).toBeInTheDocument();
  });

  it("shows the error when the run cannot be loaded", async () => {
    const api = fake(run());
    api.getRun.mockRejectedValue(new Error("not found"));
    render(<RunPage runId="r" api={api} canAnswer userSub="me" pollMs={60000} />);
    expect(await screen.findByText("not found")).toBeInTheDocument();
  });
});
