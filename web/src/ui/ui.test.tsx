import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NewRunPage } from "../components/NewRunPage";
import { RunsPage } from "../components/RunsPage";
import type { Client, RunSummary } from "../api/client";
import { Markdown, safeUrl } from "./Markdown";
import { ToastProvider, useToast } from "./Toasts";
describe("Markdown", () => {
  it("keeps only https links", () => {
    expect(safeUrl("https://a.example")).toBe("https://a.example");
    for (const u of ["http://a", "javascript:alert(1)", "data:text/html,x", "//a.example"]) expect(safeUrl(u)).toBe("");
  });
  it("skips raw HTML", () => {
    render(<Markdown text={"<script>alert(1)</script>\n\n**hi**"} />);
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText("hi")).toBeInTheDocument();
  });
});
describe("Toasts", () => {
  it("shows a message and removes it", async () => {
    const T = () => { const n = useToast(); return <button type="button" onClick={() => n("Saved")}>go</button>; };
    render(<ToastProvider ms={30}><T /></ToastProvider>);
    await userEvent.click(screen.getByText("go"));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Saved")).toBeNull());
  });
});
describe("NewRunPage", () => {
  it("shows what is wrong before sending anything", async () => {
    const api = { createRun: vi.fn(), startRun: vi.fn() };
    render(<NewRunPage api={api} onStarted={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Start the analysis" }));
    expect(screen.getByRole("alert")).toHaveTextContent("customer's name");
    expect(api.createRun).not.toHaveBeenCalled();
  });
  it("creates, uploads, starts and opens the run", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    const api = { createRun: vi.fn().mockResolvedValue({ runId: "r1", upload: { url: "https://s3.example", fields: { key: "k" } } }), startRun: vi.fn().mockResolvedValue({ runId: "r1" }) };
    const onStarted = vi.fn();
    render(<NewRunPage api={api} onStarted={onStarted} />);
    await userEvent.type(screen.getByLabelText(/Customer name/), "Moon Trades");
    await userEvent.upload(document.querySelector("input[type=file]")!, new File(["x"], "sow.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Start the analysis" }));
    await waitFor(() => expect(onStarted).toHaveBeenCalledWith("r1"));
    expect(api.createRun).toHaveBeenCalledWith({ customerId: "moon-trades", requirements: undefined, fileName: "sow.pdf" });
    expect(fetchMock).toHaveBeenCalledWith("https://s3.example", expect.objectContaining({ method: "POST" }));
    vi.unstubAllGlobals();
  });
  it("names a missing upload link instead of starting", async () => {
    const api = { createRun: vi.fn().mockResolvedValue({ runId: "r1", upload: null }), startRun: vi.fn() };
    render(<NewRunPage api={api} onStarted={() => {}} />);
    await userEvent.type(screen.getByLabelText(/Customer name/), "Moon Trades");
    await userEvent.upload(document.querySelector("input[type=file]")!, new File(["x"], "sow.pdf"));
    await userEvent.click(screen.getByRole("button", { name: "Start the analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no upload link");
    expect(api.startRun).not.toHaveBeenCalled();
  });
});
describe("RunsPage filters", () => {
  const runs: RunSummary[] = [
    { runId: "a".repeat(32), customerId: "alpha", status: "RUNNING", createdAt: 1, runKind: "deploy", error: "", awaitingHitl: true },
    { runId: "b".repeat(32), customerId: "beta", status: "FAILED", createdAt: 1, runKind: "deploy", error: "x" },
  ];
  it("filters by chip and by search text", async () => {
    render(<RunsPage api={{ listRuns: vi.fn().mockResolvedValue({ runs, total: 2 }) } as unknown as Client} onOpen={() => {}} />);
    await screen.findByText("Alpha");
    await userEvent.click(screen.getByRole("button", { name: /Failed/ }));
    expect(screen.queryByText("Alpha")).toBeNull();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^All/ }));
    await userEvent.type(screen.getByLabelText("Search runs"), "alp");
    expect(screen.queryByText("Beta")).toBeNull();
    await userEvent.clear(screen.getByLabelText("Search runs"));
    await userEvent.type(screen.getByLabelText("Search runs"), "zzz");
    expect(screen.getByText("No runs match these filters.")).toBeInTheDocument();
  });
});
