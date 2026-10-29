import { useState } from "react";
import type { Client, PendingHumanInput, Run } from "../api/client";
import {
  ANSWER_LIMIT, answeredPending, canDecideHere, consoleLink, decidedPending, isUpdateOnly, optionIndex,
  suggestionAction, suggestionLabel,
} from "../logic/question";

interface Props {
  run: Run;
  pending: PendingHumanInput;
  /** The signed-in person is in the approver group. */
  canAnswer: boolean;
  userSub: string;
  api: Pick<Client, "answerQuestion" | "decideTask">;
  /** Called after a send so the page reloads the run. */
  onChanged: () => void;
}

const when = (ts: number): string => new Date(ts * 1000).toLocaleString();

/** What AWS Transform is waiting on, the deploy agent's note, and the ways a person can respond. */
export function QuestionPanel({ run, pending, canAnswer, userSub, api, onChanged }: Props) {
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [replyOpen, setReplyOpen] = useState(false);
  const [confirmDecision, setConfirmDecision] = useState<"approve" | "reject" | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const note = pending.agentNote;
  const answered = answeredPending(run, pending);
  const decided = decidedPending(run, pending);
  const update = isUpdateOnly(pending);
  const action = suggestionAction(pending, canAnswer);
  const link = consoleLink(note);
  const showReply = replyOpen || (pending.kind === "message" && pending.options.length === 0);

  async function send(fn: () => Promise<unknown>) {
    setSending(true);
    setError("");
    try {
      await fn();
      setSelected(null);
      setDraft("");
      setConfirmDecision(null);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }

  const sendOption = () =>
    selected !== null &&
    send(() => api.answerQuestion(run.runId, { jobId: pending.jobId, messageId: pending.messageId ?? "", option: selected }));
  const sendText = () =>
    draft.trim() &&
    send(() => api.answerQuestion(run.runId, { jobId: pending.jobId, messageId: pending.messageId ?? "", text: draft.trim() }));
  const sendDecision = (decision: "approve" | "reject") =>
    send(() => api.decideTask(run.runId, { jobId: pending.jobId, taskId: pending.taskId ?? "", decision }));

  function useSuggestion() {
    if (action.kind === "select") {
      setSelected(pending.options[action.optionIndex] ?? null);
      setReplyOpen(false);
    } else if (action.kind === "reply") {
      setDraft(action.text.slice(0, ANSWER_LIMIT));
      setSelected(null);
      setReplyOpen(true);
    }
  }

  const heading = answered ? "Answer sent to AWS Transform" : decided ? "Decision sent to AWS Transform" : update ? "Update from AWS Transform" : "AWS Transform needs your input";

  return (
    <section className="hitl" aria-labelledby="hitl-heading">
      <h2 id="hitl-heading">{heading}</h2>
      {pending.kind === "task" && <p><strong>{pending.title}</strong></p>}
      {pending.text && <div className="hitl-text" data-testid="question-text">{pending.text}</div>}

      {note && !answered && !decided && (
        <div className="agent-note" role="note">
          <strong>{update ? "Deploy agent (no reply needed):" : "Deploy agent:"}</strong> {note.reason}
          {note.suggestion && (
            <div className="hint" data-testid="suggestion">
              {suggestionLabel(note.suggestionType)}: {note.suggestion}
            </div>
          )}
          {action.kind !== "none" && (
            <div className="row">
              <button
                type="button"
                className={`btn btn-sm${action.kind === "select" && action.approval ? " btn-primary" : ""}`}
                onClick={useSuggestion}
              >
                {action.kind === "reply" ? "Use this as my reply" : action.approval ? "Select this option to approve" : "Select this option"}
              </button>
              <span className="hint">
                {action.kind === "reply" ? "You can edit it before sending." : action.approval ? "This approves or starts something in AWS. You confirm before it is sent." : "You confirm before it is sent."}
              </span>
            </div>
          )}
          {link && (
            <div className="row">
              <a className="btn btn-sm btn-primary" href={link} target="_blank" rel="noopener noreferrer">Approve in the AWS console ↗</a>
            </div>
          )}
        </div>
      )}

      {answered && (
        <div className="sent" role="status">
          Sent {answered.option ? `“${answered.option}”` : answered.by === "agent" ? "a reply" : "your message"} to AWS Transform
          {answered.by === "agent" ? " (by the deploy agent)" : answered.by === userSub ? "" : " (by another user)"} · {when(answered.at)}
          {answered.text && <blockquote>{answered.text}</blockquote>}
          <div className="hint">Waiting for Transform to continue. This page updates on its own.</div>
        </div>
      )}

      {decided && (
        <div className="sent" role="status">
          {decided.decision === "approve" ? "Approved" : "Rejected"} “{pending.title}” in AWS Transform
          {decided.by === userSub ? "" : " (by another user)"} · {when(decided.at)}
          <div className="hint">Waiting for Transform to continue. This page updates on its own.</div>
        </div>
      )}

      {!answered && !decided && pending.kind === "message" && pending.messageId && canAnswer && (
        <div className="actions">
          {pending.options.length > 0 && (
            <div className="choices" role="group" aria-label="Choose an answer">
              {pending.options.map((o) => (
                <button key={o} type="button" className="choice" aria-pressed={selected === o} disabled={sending}
                  onClick={() => setSelected(selected === o ? null : o)}>{o}</button>
              ))}
            </div>
          )}
          {selected !== null && (
            <div className="confirm" role="group" aria-label="Confirm answer">
              <span>Send <strong>“{selected}”</strong> to AWS Transform?</span>
              <button type="button" className="btn btn-primary btn-sm" disabled={sending} onClick={sendOption}>{sending ? "Sending…" : "Send answer"}</button>
              <button type="button" className="btn btn-sm" disabled={sending} onClick={() => setSelected(null)}>Cancel</button>
            </div>
          )}
          {showReply ? (
            <div className="reply">
              <label htmlFor="answer-text">Your reply to Transform</label>
              <textarea id="answer-text" maxLength={ANSWER_LIMIT} rows={3} value={draft} disabled={sending}
                onChange={(e) => setDraft(e.target.value)} />
              <div className="reply-foot">
                <span className="hint">{draft.trim().length}/{ANSWER_LIMIT}</span>
                {pending.options.length > 0 && <button type="button" className="btn btn-sm" onClick={() => setReplyOpen(false)}>Close</button>}
                <button type="button" className="btn btn-primary btn-sm" disabled={sending || !draft.trim()} onClick={sendText}>Send reply</button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn-link" onClick={() => setReplyOpen(true)}>Reply with a message instead</button>
          )}
        </div>
      )}

      {!answered && !decided && canDecideHere(pending, canAnswer) && (
        <div className="actions">
          <p className="hint">Approving makes AWS Transform apply this to the target account. It is recorded under your name.</p>
          {confirmDecision === null ? (
            <div className="row">
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setConfirmDecision("approve")}>Approve in this app</button>
              <button type="button" className="btn btn-sm" onClick={() => setConfirmDecision("reject")}>Reject</button>
            </div>
          ) : (
            <div className="confirm" role="group" aria-label="Confirm decision">
              <span>{confirmDecision === "approve" ? "Approve" : "Reject"} <strong>“{pending.title}”</strong> in AWS Transform?</span>
              <button type="button" className="btn btn-primary btn-sm" disabled={sending} onClick={() => sendDecision(confirmDecision)}>
                {sending ? "Sending…" : `Yes, ${confirmDecision}`}
              </button>
              <button type="button" className="btn btn-sm" disabled={sending} onClick={() => setConfirmDecision(null)}>Cancel</button>
            </div>
          )}
        </div>
      )}

      {!answered && !decided && !canAnswer && pending.kind === "message" && (
        <p className="hint">Only members of the approver group can answer from here. Ask an administrator to add you, or answer in AWS Transform.</p>
      )}
      {!answered && !decided && pending.kind === "task" && !canDecideHere(pending, canAnswer) && !link && (
        <p className="hint">This is a Transform task with its own form. Open it in AWS Transform to complete it.</p>
      )}

      {error && <p className="error" role="alert">{error}</p>}
      <p className="hint">
        Transform job <code>{pending.jobId}</code>.{" "}
        {/^https:\/\//.test(pending.consoleUrl) && (
          <a href={pending.consoleUrl} target="_blank" rel="noopener noreferrer">Open in AWS Transform ↗</a>
        )}
      </p>
      {selected !== null && optionIndex(pending, selected) < 0 && <p className="error" role="alert">That option is no longer offered.</p>}
    </section>
  );
}
