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

from botocore.exceptions import ClientError
from strands import tool

from lzcore import transform_ops
from lzcore.transform_answers import AnswerExists, AnswerRecordFailed, send_answer

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

# The only answers the agent sends on its own: selecting one of these offered options. Both choose a workflow
# path and change nothing in AWS. Everything else (Proceed, Continue, Deploy for me, Approve proposal, any new
# label Transform introduces) is handed to a person: the list fails closed. The agent never sends typed text;
# a reply that needs text is escalated with the text as the suggestion, and a person sends it.
AGENT_ANSWERABLE_OPTIONS = frozenset({"landing zone", "custom structure"})
# Atomic per-run cap on agent answers: the slot is taken before sending and given back if the send fails.
SLOT_CONDITION = "#s = :running AND (attribute_not_exists(agentAnswerCount) OR agentAnswerCount < :max)"

# The question the current model turn is deciding (set by begin_turn, cleared by end_turn). Module-level state is
# safe because one AgentCore session runs one invoke at a time; a second concurrent invoke in the same process
# would corrupt it, so do not call these tools from threads.
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
    if item.get("informational"):
        note["informational"] = True  # shown as an update the person may still reply to, not as a question
    if item.get("link"):
        note["link"] = item["link"]  # https AWS console link the person must open (connector approval)
    return note


def _reserve_answer_slot() -> bool:
    """Take one of the run's agent-answer slots atomically. False when the cap is reached or the run is not RUNNING."""
    try:
        base._ddb.update_item(
            Key={"PK": f"RUN#{base._state['run']}", "SK": "META"},
            UpdateExpression="ADD agentAnswerCount :one",
            ConditionExpression=SLOT_CONDITION,
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":one": 1, ":running": "RUNNING", ":max": MAX_AGENT_ANSWERS_PER_RUN},
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        return False


def _release_answer_slot() -> None:
    base._ddb.update_item(
        Key={"PK": f"RUN#{base._state['run']}", "SK": "META"},
        UpdateExpression="ADD agentAnswerCount :minus",
        ExpressionAttributeValues={":minus": -1},
    )


def _json_for_prompt(obj: Any, **kw) -> str:
    """JSON that cannot close or open the prompt's XML-style blocks: Transform text is untrusted."""
    return json.dumps(obj, default=str, **kw).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


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
    scope_json = _json_for_prompt(scope, sort_keys=True)
    if len(scope_json) > SCOPE_PROMPT_LIMIT:
        raise RuntimeError(
            f"approved design is {len(scope_json)} characters (limit {SCOPE_PROMPT_LIMIT} for the Transform conversation turn)"
        )
    parts = [
        "Decide the pending AWS Transform message below with exactly one tool call: "
        "answer_transform_question, no_reply_needed or escalate_to_human.",
        f"<pending_question>\n{_json_for_prompt(question, indent=1)}\n</pending_question>",
        f"<recent_transform_conversation>\n{_json_for_prompt(conversation, indent=1)}\n</recent_transform_conversation>",
        f"<run_context>\n{_json_for_prompt(context, indent=1)}\n</run_context>",
        f"<approved_design>\n{scope_json}\n</approved_design>",
    ]
    if prior and prior.get("lastError"):
        # The error can quote Transform text (for example the offered options), so it is escaped like the rest.
        parts.append(f"<previous_turn_error>\n{_json_for_prompt(prior['lastError'])}\n</previous_turn_error>")
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
    """Select one offered option of the pending AWS Transform question.

    You may select only "Landing Zone" or "Custom structure", and only when Transform offers it (case does
    not matter). Any other option, and any typed reply, is refused: call escalate_to_human instead and put
    the exact option or reply text in suggestion, so a person can send it.
    category: "design" when the approved design states the answer, "workflow" for a workflow choice
      that follows from the run purpose and context.
    rationale: why this is the answer, in one or two sentences.
    basis: entries "scope:<JSON pointer into the approved design>" or "context:<run_context key>".
    option: the option to select.
    text: not accepted (kept so a mistaken call gets a clear refusal).
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
    if text:
        return ("REFUSED: the agent does not send typed replies. Call escalate_to_human with the exact reply text "
                "in suggestion; a person reviews and sends it.")
    if not option or option.strip().lower() not in AGENT_ANSWERABLE_OPTIONS:
        return (f"REFUSED: {option!r} is not an option the agent may select (only 'Landing Zone' or 'Custom "
                "structure'). Call escalate_to_human with the option you would choose in suggestion.")
    wanted = option.strip().lower()
    offered = [c for c in pending.get("choices") or [] if str(c.get("label", "")).strip().lower() == wanted]
    if len(offered) != 1:
        return (f"REFUSED: Transform offers {len(offered)} options named {option!r}. Call escalate_to_human.")
    # The value is what Transform receives; it must say the same thing as the label (untrusted Transform data).
    if str(offered[0].get("value") or "").strip().lower() not in ("", wanted):
        return (f"REFUSED: the option {offered[0]['label']!r} would send {offered[0].get('value')!r} to Transform, "
                "which is not the same as its label. Call escalate_to_human.")
    opt, txt = offered[0]["label"], None  # the exact label as offered
    qkey = _turn["qkey"]
    if not _reserve_answer_slot():
        return (f"REFUSED: the agent has used its {MAX_AGENT_ANSWERS_PER_RUN} answers for this run, or the run is "
                "no longer RUNNING. Call escalate_to_human.")
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
            find_reply=lambda since: transform_ops.user_reply_since(pending["jobId"], since, pending["workspaceId"]),
            audit_extra={"by": "agent", "category": category, "rationale": rationale.strip()[:500],
                         "basis": basis[:20], "question": pending.get("title")},
        )
    except ValueError as e:
        _release_answer_slot()
        return f"REFUSED: {e}"
    except AnswerExists:
        _release_answer_slot()
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason="the question already had an answer (a person answered it)")
        _turn["decided"] = "superseded"
        return "REFUSED: this question already has an answer from a person. Stop now."
    except transform_ops.QuestionChanged as e:
        _release_answer_slot()
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason=str(e)[:NOTE_LIMIT])
        _turn["decided"] = "superseded"
        return f"REFUSED: AWS Transform moved on ({e}). Stop now; the next question comes on a later poll."
    except AnswerRecordFailed:
        # The reply reached Transform: the slot stays taken and the decision is recorded, then the turn fails loudly.
        put_question(qkey, status="answered", kind=pending["kind"], title=pending.get("title"), turns=_turn.get("turns"),
                     category=category, rationale=rationale.strip(), basis=basis, option=opt,
                     reason="sent, but recording the answer failed")
        _turn["decided"] = "answered"
        raise
    except Exception:
        _release_answer_slot()  # only failures before or during the send reach here: nothing went out
        raise
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
    if pending.get("jobAwaitingInput"):
        return ("REFUSED: the Transform job reports AWAITING_HUMAN_INPUT, so it is blocked on a reply and this "
                "message is not just progress. Answer it or escalate it.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > NOTE_LIMIT:
        return f"REFUSED: reason must be 1-{NOTE_LIMIT} characters."
    put_question(_turn["qkey"], status="informational", kind=pending["kind"], title=pending.get("title"),
                 turns=_turn.get("turns"), reason=reason.strip(), informational=True)
    base.log_tool_event("transform.no_reply_needed", {"jobId": pending.get("jobId"), "messageId": pending.get("messageId"),
                                                      "reason": reason.strip()[:300]})
    _turn["decided"] = "informational"
    return "Recorded. Reply with one sentence and stop."


def converse_tools() -> list:
    return [answer_transform_question, no_reply_needed, escalate_to_human]

