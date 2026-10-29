"""The deploy agent's side of the AWS Transform conversation.

While the Transform landing zone job runs, each question it asks goes to the deploy agent first.
In one model turn the agent makes exactly one decision with one of three tools:

* answer_transform_question: select an offered option from AGENT_ANSWERABLE_OPTIONS, or type a reply to a
  message that offers no options (facts the design or run context state). Every typed reply is first
  checked by an independent reviewer model (review_reply) that refuses anything that approves an
  irreversible action; an error or a missing verdict refuses the reply too. The reply goes through
  lzcore.transform_answers.send_answer, the same reservation and record path the UI approver uses, so
  a question is never answered twice and every answer is audited with the agent's category, rationale
  and design basis.
* no_reply_needed: the message only reports progress or status and asks nothing (no options, no
  question). Nothing is sent to Transform and the person is not asked; the model, not a text rule,
  decides this.
* escalate_to_human: anything else. Approval gates (deploying, creating or deleting resources),
  facts the design does not hold (MAP ids), Transform tasks with their own form, and anything the
  model is unsure about. The reason and an optional typed suggestion are shown to the person in the UI
  next to the question. The suggestion holds only the exact reply: suggestion_type says what it is
  (option, approval, text or steps) and the tool checks it against what Transform offered.

The tools enforce the boundary in code: only AGENT_ANSWERABLE_OPTIONS can be selected, offered exactly
once with a value equal to the label; typed text only on a message without options and only after the
reply review; every basis entry must resolve in the design or the run context. Everything else is
escalated.

Per-question state lives in DynamoDB at RUN#<runId> / AGENTQ#<questionKey>:
    {status: deciding | answered | escalated | informational | superseded, turns, kind, title, reason, suggestion,
     category, rationale, basis, option, text, lastError, updatedAt}
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

from botocore.exceptions import ClientError
from strands import tool

from lzcore import transform_ops
from lzcore.transform_answers import ANSWER_TEXT_LIMIT, AnswerExists, AnswerRecordFailed, send_answer

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
# A suggestion may be the full reply a person sends (for example the design's custom structure): same limit
# as a reply.
SUGGESTION_LIMIT = ANSWER_TEXT_LIMIT
RUN_PURPOSE = (
    "Build the AWS landing zone in the approved design. Landing zone only: no migration planning, "
    "no network migration, no server migration."
)

# The options the agent selects on its own. Each only chooses a path in the design conversation and starts
# nothing in AWS: Transform deploys only after "Proceed" / "Deploy for me" and the deployment approval task.
# Everything else (Proceed, Continue, Deploy for me, Approve proposal, any new label Transform introduces) is
# handed to a person: the list fails closed. Widen it only for labels that cannot start a change in AWS.
AGENT_ANSWERABLE_OPTIONS = frozenset({
    "landing zone", "custom structure", "my own structure", "get started",
    "create a control tower landing zone (recommended)", "recommend additional scps", "none (skip)",
})
# Atomic per-run cap on agent answers: the slot is taken before sending and given back if the send fails.
SLOT_CONDITION = "#s = :running AND (attribute_not_exists(agentAnswerCount) OR agentAnswerCount < :max)"

SUGGESTION_TYPES = ("option", "approval", "text", "steps")

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
    if item.get("suggestion") and item.get("suggestionType"):
        note["suggestionType"] = item["suggestionType"]  # option | approval | text | steps
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


def _reply_in_transform(pending: dict) -> Optional[str]:
    """A USER message newer than the pending question (its own Transform createdAtMs), else None."""
    since = pending.get("createdAtMs")
    if isinstance(since, bool) or not isinstance(since, int):
        raise RuntimeError(
            f"pending Transform question {pending.get('messageId')} has no integer createdAtMs (got {since!r}); "
            "it was recorded by an older release and is refreshed on the next poll"
        )
    return transform_ops.user_reply_since(pending["jobId"], since, pending.get("workspaceId"))


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
    email = {"accountEmailBase": meta["accountEmailBase"]} if meta.get("accountEmailBase") else {}
    map_agreement = {"mapAgreement": meta["mapAgreement"]} if meta.get("mapAgreement") else {}
    return {
        **email,  # present only when the operator supplied it: "prefix@domain", Transform adds "+account-name"
        **map_agreement,  # present only when supplied: "none" (no MAP agreement) or the full MAP tag value
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
        "Make exactly one decision on the pending AWS Transform message below, with one of "
        "answer_transform_question, no_reply_needed or escalate_to_human. If a call is REFUSED, make a "
        "corrected call (usually escalate_to_human); stop after one call succeeds.",
        f"<pending_question>\n{_json_for_prompt(question, indent=1)}\n</pending_question>",
        f"<recent_transform_conversation>\n{_json_for_prompt(conversation, indent=1)}\n</recent_transform_conversation>",
        f"<run_context>\n{_json_for_prompt(context, indent=1)}\n</run_context>",
        f"<approved_design>\n{scope_json}\n</approved_design>",
    ]
    if prior and prior.get("lastError"):
        # The error can quote Transform text (for example the offered options), so it is escaped like the rest.
        parts.append(f"<previous_turn_error>\n{_json_for_prompt(prior['lastError'])}\n</previous_turn_error>")
    return "\n\n".join(parts)


def begin_turn(*, qkey: str, pending: dict, scope: dict, context: dict, turns: int,
               conversation: Optional[list] = None) -> None:
    _turn.clear()
    _turn.update(qkey=qkey, pending=pending, scope=scope, context=context, turns=turns, decided=None,
                 conversation=conversation or [])


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
    """Answer the pending AWS Transform question: select one offered option, or type a reply. Send exactly one.

    option: an offered option from the allowed list in your instructions (case does not matter). Any other
      option is refused: call escalate_to_human with the option as the suggestion.
    text: a typed reply, only for a message that offers no options, and only with facts the approved design or
      run context state. It must never approve, authorize or start anything; an independent reviewer checks it.
    category: "design" when the approved design states the answer, "workflow" for a choice that follows from
      the run purpose and context.
    rationale: why this is the answer, in one or two sentences.
    basis: entries "scope:<JSON pointer into the approved design>" or "context:<run_context key>".
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
    if bool(option) == bool(text):
        return "REFUSED: send exactly one of option or text."
    if text:
        if pending.get("options") or pending.get("choices"):
            return ("REFUSED: this message offers options, so a typed reply is not accepted. Select an allowed "
                    "option, or call escalate_to_human with the option to choose as the suggestion.")
        if not isinstance(text, str) or not 0 < len(text.strip()) <= ANSWER_TEXT_LIMIT:
            return f"REFUSED: text must be 1-{ANSWER_TEXT_LIMIT} characters."
        refusal = review_reply(pending, text.strip())
        if refusal:
            return refusal
        opt, txt = None, text.strip()
    else:
        if option.strip().lower() not in AGENT_ANSWERABLE_OPTIONS:
            return (f"REFUSED: {option!r} is not an option the agent may select (allowed: "
                    f"{sorted(AGENT_ANSWERABLE_OPTIONS)}). Call escalate_to_human with the option you would choose "
                    "in suggestion (suggestion_type 'option', or 'approval' if it starts or approves something).")
        wanted = option.strip().lower()
        offered = [c for c in pending.get("choices") or [] if str(c.get("label", "")).strip().lower() == wanted]
        if len(offered) != 1:
            return (f"REFUSED: Transform offers {len(offered)} options named {option!r}. Call escalate_to_human.")
        # The value is what Transform receives; it must say the same thing as the label (untrusted Transform
        # data). An option without a value cannot be sent at all (answer_message refuses it).
        if str(offered[0].get("value") or "").strip().lower() != wanted:
            return (f"REFUSED: the option {offered[0]['label']!r} would send {offered[0].get('value')!r} to "
                    "Transform, which is not the same as its label. Call escalate_to_human.")
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
            find_reply=lambda: _reply_in_transform(pending),
            audit_extra={"by": "agent", "category": category, "rationale": rationale.strip()[:500],
                         "basis": basis[:20], "question": pending.get("title")},
        )
    except ValueError as e:
        _release_answer_slot()
        return f"REFUSED: {e}"
    except AnswerExists:
        _release_answer_slot()
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason="the question already has an answer, sent or being sent")
        _turn["decided"] = "superseded"
        return "REFUSED: this question already has an answer (sent or being sent). Stop now."
    except transform_ops.QuestionChanged as e:
        _release_answer_slot()
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason=str(e)[:NOTE_LIMIT])
        _turn["decided"] = "superseded"
        return f"REFUSED: AWS Transform moved on ({e}). Stop now; the next question comes on a later poll."
    except AnswerRecordFailed as e:
        # The reply is in Transform: the slot stays taken and nothing is resent. The tool returns (Strands would
        # turn a raise into a tool result anyway) and the failure is audited here, where it happens.
        _turn["decided"] = "answered"
        base.log_tool_event("transform.answer_record_failed", {
            "jobId": pending.get("jobId"), "messageId": pending.get("messageId"), "option": opt,
            "text": (txt or "")[:500] or None, "sentMessageId": e.sent_message_id, "error": str(e.cause)[:500]})
        try:
            put_question(qkey, status="answered", kind=pending["kind"], title=pending.get("title"),
                         turns=_turn.get("turns"), category=category, rationale=rationale.strip(), basis=basis,
                         option=opt, text=txt, reason="sent, but recording the answer failed")
        except Exception as e2:  # noqa: BLE001 - audited; the ANSWER# lease makes a later turn recover the reply
            base.log_tool_event("transform.answer_record_failed", {
                "messageId": pending.get("messageId"), "stage": "recording the decision",
                "error": f"{type(e2).__name__}: {e2}"[:500]})
        return "SENT to AWS Transform, but recording it failed (audited). Do not answer again. Reply with one sentence and stop."
    except Exception:
        _release_answer_slot()  # only failures before or during the send reach here: nothing went out
        raise
    if sent.get("recovered") and sent.get("by") != "agent":
        # Someone else's earlier reply had already reached Transform; ours was not sent, so the slot goes back.
        _release_answer_slot()
        put_question(qkey, status="superseded", kind=pending["kind"], title=pending.get("title"),
                     turns=_turn.get("turns"), reason=f"an earlier reply by {sent.get('by')} had already reached Transform")
        _turn["decided"] = "superseded"
        return "REFUSED: an earlier reply to this question had already reached AWS Transform. Stop now."
    put_question(qkey, status="answered", kind=pending["kind"], title=pending.get("title"), turns=_turn.get("turns"),
                 category=category, rationale=rationale.strip(), basis=basis, option=opt, text=txt)
    _turn["decided"] = "answered"
    return "SENT to AWS Transform. Reply with one sentence and stop."


@tool
def escalate_to_human(reason: str, suggestion: str = "", suggestion_type: str = "") -> str:
    """Hand the pending AWS Transform question to a person.

    reason: what the person needs to decide or do, and why you did not answer (shown in the UI). Put every
      explanation here, never in suggestion.
    suggestion: optional; ONLY the exact reply, nothing else: an offered option label, the typed reply text, or
      console steps. No commentary.
    suggestion_type: required with a suggestion. "option": an offered option label that changes nothing in AWS.
      "approval": an offered option label that approves, starts or applies something (the person confirms it).
      "text": the exact typed reply, for a message that offers no options. "steps": instructions for a task.
    """
    refused = _refuse_unless_open()
    if refused:
        return refused
    if not isinstance(reason, str) or not reason.strip() or len(reason) > NOTE_LIMIT:
        return f"REFUSED: reason must be 1-{NOTE_LIMIT} characters."
    pending = _turn["pending"]
    sug, stype = (suggestion or "").strip(), (suggestion_type or "").strip().lower()
    if len(sug) > SUGGESTION_LIMIT:
        return f"REFUSED: suggestion must be at most {SUGGESTION_LIMIT} characters."
    if sug and stype not in SUGGESTION_TYPES:
        return f"REFUSED: a suggestion needs suggestion_type, one of {list(SUGGESTION_TYPES)}."
    if stype and not sug:
        return "REFUSED: suggestion_type was given without a suggestion."
    if stype in ("option", "approval"):
        labels = [o for o in pending.get("options") or [] if isinstance(o, str)]
        match = [o for o in labels if o.strip().lower() == sug.lower()]
        if pending.get("kind") != "message" or len(match) != 1:
            return (f"REFUSED: suggestion_type {stype!r} needs the suggestion to be exactly one of the offered "
                    f"options {labels}. Put explanations in reason.")
        sug = match[0]  # the label exactly as offered
    elif stype == "text" and (pending.get("kind") != "message" or pending.get("options")):
        return ("REFUSED: suggestion_type 'text' is for a message that offers no options. For an option use "
                "'option' or 'approval' with the exact label.")
    put_question(_turn["qkey"], status="escalated", kind=pending["kind"], title=pending.get("title"),
                 turns=_turn.get("turns"), reason=reason.strip(), suggestion=sug or None,
                 suggestionType=stype or None)
    base.log_tool_event(
        "transform.agent_escalated",
        {"jobId": pending.get("jobId"), "kind": pending.get("kind"), "title": pending.get("title"),
         "reason": reason.strip()[:500], "suggestion": sug[:500] or None, "suggestionType": stype or None},
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


# ---- independent review of typed replies -------------------------------------------------------------------
# A typed reply to a free-text question cannot be checked by a list of labels, so a second, separate model call
# reads the question and the reply and says whether the reply approves an irreversible action. It must say no
# for the reply to be sent. A reviewer error, a missing verdict or an unsure verdict refuses the reply (the agent
# then escalates it): there is no default verdict.

def _reviewer_not_configured(prompt: str):
    raise RuntimeError("no reply reviewer is configured: agent.app sets one with set_reply_reviewer()")


_reply_reviewer = _reviewer_not_configured
_review_state: dict[str, Any] = {"open": False, "verdict": None}


def set_reply_reviewer(run_review: Callable[[str], object]) -> None:
    """Install the function that runs one reviewer model turn on a prompt (it must call report_reply_review)."""
    global _reply_reviewer
    _reply_reviewer = run_review


@tool
def report_reply_review(approves_irreversible_action: bool, reason: str) -> str:
    """Report the verdict on the proposed reply. Call exactly once.

    approves_irreversible_action: true when the reply approves, authorizes, confirms or starts anything that
      creates, changes or deletes AWS resources or accounts, accepts costs, or cannot be undone, however it is
      worded; also true when you are unsure. False only when it just gives requested facts or confirms facts.
    reason: one or two sentences.
    """
    if not _review_state["open"] or _review_state["verdict"] is not None:
        return "REFUSED: no reply review is open."
    if not isinstance(approves_irreversible_action, bool) or not isinstance(reason, str) or not reason.strip():
        return "REFUSED: approves_irreversible_action must be a boolean and reason a non-empty string."
    _review_state["verdict"] = {"approves": approves_irreversible_action, "reason": reason.strip()[:500]}
    return "Recorded. Stop now."


def reviewer_tools() -> list:
    return [report_reply_review]


def review_reply(pending: dict, text: str) -> Optional[str]:
    """None when the independent reviewer says the typed reply approves nothing irreversible, else a REFUSED text."""
    prompt = "\n\n".join([
        "Review the proposed reply to the pending AWS Transform message. Call report_reply_review once.",
        f"<pending_question>\n{_json_for_prompt({k: pending.get(k) for k in ('title', 'text', 'options')}, indent=1)}\n</pending_question>",
        f"<recent_transform_conversation>\n{_json_for_prompt(_turn.get('conversation') or [], indent=1)}\n</recent_transform_conversation>",
        f"<proposed_reply>\n{_json_for_prompt(text)}\n</proposed_reply>",
    ])
    _review_state.update(open=True, verdict=None)
    try:
        _reply_reviewer(prompt)
        verdict = _review_state["verdict"]
    except Exception as e:  # noqa: BLE001 - audited and refused: no reply goes out unreviewed
        base.log_tool_event("transform.reply_review_failed", {
            "jobId": pending.get("jobId"), "messageId": pending.get("messageId"), "error": f"{type(e).__name__}: {e}"[:500]})
        return (f"REFUSED: the independent reply review failed ({type(e).__name__}: {str(e)[:200]}), so the reply "
                "was not sent. Call escalate_to_human with the reply as a 'text' suggestion.")
    finally:
        _review_state.update(open=False, verdict=None)
    if verdict is None:
        base.log_tool_event("transform.reply_review_failed", {
            "jobId": pending.get("jobId"), "messageId": pending.get("messageId"), "error": "no verdict reported"})
        return ("REFUSED: the independent reply review gave no verdict, so the reply was not sent. Call "
                "escalate_to_human with the reply as a 'text' suggestion.")
    base.log_tool_event("transform.reply_reviewed", {
        "jobId": pending.get("jobId"), "messageId": pending.get("messageId"),
        "approvesIrreversibleAction": verdict["approves"], "reason": verdict["reason"], "replyChars": len(text)})
    if verdict["approves"]:
        return ("REFUSED: the independent reviewer says this reply approves or starts something irreversible "
                f"({verdict['reason']}). Call escalate_to_human; a person must give it.")
    return None

