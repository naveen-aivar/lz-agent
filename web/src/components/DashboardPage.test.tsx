import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Client, RunSummary } from "../api/client";
import { DashboardPage } from "./DashboardPage";
import { RunsPage } from "./RunsPage";
import { RunsTable } from "./RunsTable";

const now = Date.now() / 1000;
const runs: RunSummary[] = [
  { runId: "a".repeat(32), customerId: "getsetyo-tech", status: "RUNNING", createdAt: now - 900, runKind: "deploy", error: "" },
  { runId: "b".repeat(32), customerId: "getsetyo-tech", status: "FAILED", createdAt: now - 9000, runKind: "deploy", error: "Stopped by user." },
  { runId: "c".repeat(32), customerId: "getsetyo-five", status: "DELIVERED", createdAt: now - 90000, runKind: null, error: "" },
];
const api = (r: RunSummary[] = runs) => ({ listRuns: vi.fn().mockResolvedValue({ runs: r }) }) as unknown as Client;

describe("RunsTable", () => {
  it("words state and type and links every run", () => {
    render(<RunsTable runs={runs} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("In progress")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Deploy")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Getsetyo Tech")).toHaveAttribute("href", `#/run/${"a".repeat(32)}`);
    expect(within(rows[1]!).getByText("Failed")).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Stopped by user/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Ready to download")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Design")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("cccccccc")).toBeInTheDocument();
  });
  it("offers Deploy only for a delivered design run", async () => {
    const onDeploy = vi.fn();
    render(<RunsTable runs={runs} onDeploy={onDeploy} />);
    const buttons = screen.getAllByRole("button", { name: "Deploy" });
    expect(buttons).toHaveLength(1);
    await userEvent.setup().click(buttons[0]!);
    expect(onDeploy).toHaveBeenCalledWith("c".repeat(32));
  });
  it("says so when there are no runs", () => {
    render(<RunsTable runs={[]} />);
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument();
  });
});

describe("DashboardPage", () => {
  it("shows the counts, the success rate and the latest runs", async () => {
    render(<DashboardPage api={api()} />);
    expect(await screen.findByText("Runs (30 days)")).toBeInTheDocument();
    expect(screen.getByText("1 delivered · 1 failed")).toBeInTheDocument();
    expect(screen.getByText("50.0%")).toBeInTheDocument();
    expect(screen.getByText("Recent runs")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All runs →" })).toHaveAttribute("href", "#/runs");
  });
  it("shows a dash before any run has finished", async () => {
    render(<DashboardPage api={api([runs[0]!])} />);
    expect(await screen.findByText("–")).toBeInTheDocument();
  });
  it("shows why the runs could not be loaded", async () => {
    const failing = { listRuns: vi.fn().mockRejectedValue(new Error("forbidden")) } as unknown as Client;
    render(<DashboardPage api={failing} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("forbidden");
  });
});

describe("RunsPage", () => {
  it("is the run history", async () => {
    render(<RunsPage api={api()} onOpen={() => {}} />);
    expect(await screen.findByRole("heading", { name: "Runs" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });
});

describe("RunsPage paging", () => {
  const many: RunSummary[] = Array.from({ length: 60 }, (_, i) => ({
    runId: String(i).padStart(32, "0"), customerId: "acme", status: "DELIVERED", createdAt: now - i * 60, runKind: null, error: "",
  }));
  const big = () => ({ listRuns: vi.fn().mockResolvedValue({ runs: many, total: 60 }) }) as unknown as Client;

  it("shows 25 runs, then 25 more on request, and says how many there are", async () => {
    render(<RunsPage api={big()} onOpen={() => {}} />);
    expect(await screen.findByTestId("run-count")).toHaveTextContent("Showing 25 of 60 matching runs (60 in total)");
    expect(screen.getAllByRole("row")).toHaveLength(26);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Show 25 more" }));
    expect(screen.getByTestId("run-count")).toHaveTextContent("Showing 50 of 60 matching runs (60 in total)");
    await user.click(screen.getByRole("button", { name: "Show 10 more" }));
    expect(screen.getByTestId("run-count")).toHaveTextContent("Showing 60 of 60 matching runs (60 in total)");
    expect(screen.getAllByRole("row")).toHaveLength(61);
    expect(screen.queryByRole("button", { name: /Show .* more/ })).toBeNull();
  });

  it("says when the API list is shorter than the number of runs", async () => {
    const cut = { listRuns: vi.fn().mockResolvedValue({ runs: many.slice(0, 30), total: 900 }) } as unknown as Client;
    render(<RunsPage api={cut} onOpen={() => {}} />);
    expect(await screen.findByTestId("run-count")).toHaveTextContent("Showing 25 of 30 matching runs (900 in total); only the newest 30 can be listed");
  });

  it("counts the dashboard over every run, not the first page", async () => {
    render(<DashboardPage api={big()} />);
    expect(await screen.findByText("60 delivered · 0 failed")).toBeInTheDocument();
  });
});
