"""The deploy agent's side of the AWS Transform conversation.

While the Transform landing zone job runs, each question it asks goes to the deploy agent first.
In one model turn the agent makes exactly one decision with one of three tools:

* answer_transform_question: the approved design (scope.json) or the run context answers it. The
  reply goes through lzcore.transform_answers.send_answer, the same reservation and record path the
  UI approver uses, so a question is never answered twice and every answer is audited with the
  agent's category, rationale and design basis.
* no_reply_needed: the message only reports progress or status and asks nothing (no options, no
  question). Nothing is sent to Transform and the person is not asked; the model, not a text rule,
  decides this.
* escalate_to_human: anything else. Approval gates (deploying, creating or deleting resources),
  facts the design does not hold (emails, MAP ids), Transform tasks with their own form, and
  anything the model is unsure about. The reason and an optional suggestion are shown to the
  person in the UI next to the question.

The tools enforce structure, not judgment: the category must be one of ANSWER_CATEGORIES (there is
no approval category, so an approval can only be escalated), every basis entry must resolve in the
design or the run context, and option answers must be an offered label.

Per-question state lives in DynamoDB at RUN#<runId> / AGENTQ#<questionKey>:
    {status: deciding | answered | escalated | informational | superseded, turns, kind, title, reason, suggestion,
     category, rationale, basis, option, text, lastError, updatedAt}
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from strands import tool

from lzcore import transform_ops
from lzcore.transform_answers import AnswerExists, send_answer

import tools as base

# Model turns per question that end without a decision (or raise) before the run fails.
MAX_TURNS_PER_QUESTION = 3
# Replies the agent may send in one run; past it every question goes to a person.
MAX_AGENT_ANSWERS_PER_RUN = 40
ANSWER_CATEGORIES = ("design", "workflow")
CONVERSATION_MESSAGES = 12
SCOPE_PROMPT_LIMIT = 60_000
RATIONALE_LIMIT = 2000
NOTE_LIMIT = 1000
RUN_PURPOSE = (
    "Build the AWS landing zone in the approved design. Landing zone only: no migration planning, "
    "no network migration, no server migration."
)

# The question the current model turn is deciding (set by begin_turn, cleared by end_turn).
_turn: dict[str, Any] = {}


def question_key(pending: dict) -> str:
    if pending.get("kind") == "message" and pending.get("messageId"):
        return f"message:{pending['messageId']}"
    if pending.get("kind") == "task" and pending.get("taskId"):
        return f"task:{pending['taskId']}"
    raise RuntimeError(f"Transform question has no messageId/taskId to key it by: kind={pending.get('kind')!r}")


def _item_key(qkey: str) -> dict:
    return {"PK": f"RUN#{base._state['run']}", "SK": f"AGENTQ#{qkey}"}


def get_question(qkey: str) -> Optional[dict]:
    return base._ddb.get_item(Key=_item_key(qkey), ConsistentRead=True).get("Item")


def put_question(qkey: str, **fields) -> dict:
    item = {**_item_key(qkey), **fields, "updatedAt": int(time.time())}
    base._ddb.put_item(Item=item)
    return item


def agent_note(item: dict) -> dict:
    """What the UI shows next to an escalated question."""
    note = {"reason": item.get("reason") or "", "suggestion": item.get("suggestion") or None}
    if item.get("link"):
        note["link"] = item["link"]  # https AWS console link the person must open (connector approval)
    return note


def _answer_count() -> int:
    meta = base._ddb.get_item(Key={"PK": f"RUN#{base._state['run']}", "SK": "META"}, ConsistentRead=True).get("Item")
    if not meta:
        raise RuntimeError(f"run META item RUN#{base._state['run']} not found in {base.TABLE}")
    return int(meta.get("agentAnswerCount") or 0)


def _count_answer() -> None:
    base._ddb.update_item(
        Key={"PK": f"RUN#{base._state['run']}", "SK": "META"},
        UpdateExpression="ADD agentAnswerCount :one",
        ConditionExpression="#s = :running",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":one": 1, ":running": "RUNNING"},
    )


def effective_region(meta: dict, scope: dict) -> Optional[str]:
    """Control Tower home / connector Region: the run's targetRegion override, else the design's home Region."""
    return meta.get("targetRegion") or (scope.get("regions") or {}).get("home")


def run_context(*, meta: dict, foundation: dict, gaps: dict, scope: Optional[dict] = None) -> dict:
    """Facts the agent may cite as context:<key>, built from the run META and pre-discover output."""
    target = meta.get("deployTarget") or {}
    org = foundation.get("organization") or {}
    return {
        "runPurpose": RUN_PURPOSE,
        "deployTargetAccountId": target.get("accountId") or org.get("callerAccountId"),
        "transformRegion": transform_ops.transform_region(),
        "targetRegion": effective_region(meta, scope or {}),
        "targetRegionIsOverride": bool(meta.get("targetRegion")),
        "organization": {
            "id": org.get("id"),
            "managementAccountId": org.get("masterAccountId"),
            "deployTargetIsManagementAccount": org.get("callerIsManagementAccount"),
            "featureSet": org.get("featureSet"),
        },
        "liveOus": [o.get("path") or o.get("name") for o in foundation.get("organizationalUnits") or []],
        "liveAccounts": [
            {"name": a.get("name"), "id": a.get("id"), "isManagementAccount": a.get("isManagementAccount")}
            for a in foundation.get("accounts") or []
        ],
        "controlTowerLandingZones": len((foundation.get("controlTower") or {}).get("landingZones") or []),
        "preDeployGaps": {k: gaps.get(k) for k in ("missingOus", "missingAccountsByName", "extraOus", "extraAccountsByName")},
    }


def build_prompt(*, pending: dict, scope: dict, context: dict, conversation: list[dict], prior: Optional[dict]) -> str:
    question = {k: pending.get(k) for k in ("kind", "title", "text", "options", "messageId", "taskId")}
    scope_json = json.dumps(scope, default=str, sort_keys=True)
    if len(scope_json) > SCOPE_PROMPT_LIMIT:
        raise RuntimeError(
            f"approved design is {len(scope_json)} characters (limit {SCOPE_PROMPT_LIMIT} for the Transform conversation turn)"
        )
    parts = [
        "Decide the pending AWS Transform question below with exactly one tool call: "
        "answer_transform_question or escalate_to_human.",
        f"<pending_question>\n{json.dumps(question, default=str, indent=1)}\n</pending_question>",
        f"<recent_transform_conversation>\n{json.dumps(conversation, default=str, indent=1)}\n</recent_transform_conversation>",
        f"<run_context>\n{json.dumps(context, default=str, indent=1)}\n</run_context>",
        f"<approved_design>\n{scope_json}\n</approved_design>",
    ]
    if prior and prior.get("lastError"):
        parts.append(f"Your previous turn on this question did not finish: {prior['lastError']}")
    return "\n\n".join(parts)


def begin_turn(*, qkey: str, pending: dict, scope: dict, context: dict, turns: int) -> None:
    _turn.clear()
    _turn.update(qkey=qkey, pending=pending, scope=scope, context=context, turns=turns, decided=None)


def end_turn() -> Optional[str]:
    decided = _turn.get("decided")
    _turn.clear()
    return decided


def _resolve_pointer(doc: Any, pointer: str) -> bool:
    """RFC 6901 JSON pointer lookup; True when the path exists."""
    if not pointer.startswith("/"):
        return False
    node = doc
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                return False
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                return False
            node = node[part]
        else:
            return False
    return True


def _invalid_basis(basis: list) -> list[str]:
    bad = []
    for entry in basis:
        if not isinstance(entry, str):
            bad.append(repr(entry))
        elif entry.startswith("scope:"):
            if not _resolve_pointer(_turn["scope"], entry[len("scope:"):]):
                bad.append(entry)
        elif entry.startswith("context:"):
            if entry[len("context:"):] not in _turn["context"]:
                bad.append(entry)
        else:
            bad.append(entry)
    return bad


def _refuse_unless_open() -> Optional[str]:
    if base._state.get("mode") != "deploy" or not _turn:
        return "REFUSED: no Transform question is being decided in this turn."
    if _turn.get("decided"):
        return f"REFUSED: this question is already decided ({_turn['decided']}). Stop now."
    return None


@tool
def answer_transform_question(category: str, rationale: str, basis: list[str], option: str = "", text: str = "") -> str:
    """Send your answer to the pending AWS Transform message question.

    category: "design" when the approved design states the answer, "workflow" for a workflow choice
      that follows from the run purpose and context. Approval gates have no category: escalate them.
    rationale: why this is the answer, in one or two sentences.
    basis: entries "scope:<JSON pointer into the approved design>" or "context:<run_context key>".
    option: one of the offered option labels, exactly as given. Or text: a free-text reply
      (1-4000 characters). Give exactly one of option or text.
    """
    refused = _refuse_unless_open()
    if refused:
        return refused
    pending = _turn["pending"]
    if pending.get("kind") != "message":
        return "REFUSED: this is a Transform task with its own form; call escalate_to_human with instructions."
    if category not in ANSWER_CATEGORIES:
        return (f"REFUSED: category must be one of {list(ANSWER_CATEGORIES)}. Approval gates and anything "
                "else go to escalate_to_human.")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > RATIONALE_LIMIT:
        return f"REFUSED: rationale must be 1-{RATIONALE_LIMIT} characters."
    if not isinstance(basis, list) or not basis:
        return "REFUSED: basis must list at least one scope:<pointer> or context:<key> entry."
    bad = _invalid_basis(basis)
    if bad:
        return (f"REFUSED: these basis entries do not resolve in the approved design or run context: {bad}. "
                f"Context keys: {sorted(_turn['context'])}.")
    opt, txt = (option or None), (text or None)
    if _answer_count() >= MAX_AGENT_ANSWERS_PER_RUN:
        return (f"REFUSED: the agent has sent {MAX_AGENT_ANSWERS_PER_RUN} answers in this run, the limit. "
                "Call escalate_to_human.")
    qkey = _turn["qkey"]
    try:
        sent = send_answer(
            table=base._ddb,
            audit=base.log_tool_event,
            run_id=base._state["run"],
            pending=pending,
            option=opt,
            text=txt,
            by="agent",
            at=int(time.time()),
            send=lambda **kw: transform_ops.answer_message(**kw, workspace=pending["workspaceId"]),
            audit_extra={"by": "agent", "category": category, "rationale": rationale.strip()[:500],
                         "basis": basis[:20], "question": pending.get("title")},
        )
    except ValueError as e:
        return f"REFUSED: {e}"
    except AnswerExists:
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason="the question already had an answer (a person answered it)")
        _turn["decided"] = "superseded"
        return "REFUSED: this question already has an answer from a person. Stop now."
    except transform_ops.QuestionChanged as e:
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason=str(e)[:NOTE_LIMIT])
        _turn["decided"] = "superseded"
        return f"REFUSED: AWS Transform moved on ({e}). Stop now; the next question comes on a later poll."
    _count_answer()
    put_question(qkey, status="answered", kind=pending["kind"], title=pending.get("title"), turns=_turn.get("turns"),
                 category=category, rationale=rationale.strip(), basis=basis, option=opt, text=sent.get("text"))
    _turn["decided"] = "answered"
    return "SENT to AWS Transform. Reply with one sentence and stop."


@tool
def escalate_to_human(reason: str, suggestion: str = "") -> str:
    """Hand the pending AWS Transform question to a person.

    reason: what the person needs to decide or do, and why you did not answer (shown in the UI).
    suggestion: optional; the option or reply you would choose, or the exact console steps.
    """
    refused = _refuse_unless_open()
    if refused:
        return refused
    if not isinstance(reason, str) or not reason.strip() or len(reason) > NOTE_LIMIT:
        return f"REFUSED: reason must be 1-{NOTE_LIMIT} characters."
    if suggestion and len(suggestion) > NOTE_LIMIT:
        return f"REFUSED: suggestion must be at most {NOTE_LIMIT} characters."
    pending = _turn["pending"]
    put_question(_turn["qkey"], status="escalated", kind=pending["kind"], title=pending.get("title"),
                 turns=_turn.get("turns"), reason=reason.strip(), suggestion=(suggestion or "").strip() or None)
    base.log_tool_event(
        "transform.agent_escalated",
        {"jobId": pending.get("jobId"), "kind": pending.get("kind"), "title": pending.get("title"),
         "reason": reason.strip()[:500], "suggestion": (suggestion or "").strip()[:500] or None},
    )
    _turn["decided"] = "escalated"
    return "Handed to a person. Reply with one sentence and stop."


@tool
def no_reply_needed(reason: str) -> str:
    """Record that the pending Transform message only reports progress and needs no reply.

    Use it only for a message without options that asks nothing (for example a status update such as
    "Working on ..."). Nothing is sent to Transform. If the message asks anything, even in plain text,
    answer it or escalate it instead.
    reason: one sentence saying why no reply is needed.
    """
    refused = _refuse_unless_open()
    if refused:
        return refused
    pending = _turn["pending"]
    if pending.get("kind") != "message" or pending.get("options"):
        return "REFUSED: only a message without options can be informational. Answer it or escalate it."
    if not isinstance(reason, str) or not reason.strip() or len(reason) > NOTE_LIMIT:
        return f"REFUSED: reason must be 1-{NOTE_LIMIT} characters."
    put_question(_turn["qkey"], status="informational", kind=pending["kind"], title=pending.get("title"),
                 turns=_turn.get("turns"), reason=reason.strip())
    base.log_tool_event("transform.no_reply_needed", {"jobId": pending.get("jobId"), "messageId": pending.get("messageId"),
                                                      "reason": reason.strip()[:300]})
    _turn["decided"] = "informational"
    return "Recorded. Reply with one sentence and stop."


def converse_tools() -> list:
    return [answer_transform_question, no_reply_needed, escalate_to_human]

