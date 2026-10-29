"""One answer per AWS Transform question, whoever sends it (the UI approver or the deploy agent).

Both the API Lambda (POST /runs/{runId}/answer) and the deploy agent runtime answer through
send_answer, so they share one record of what was sent:

* ANSWER#<messageId> (under RUN#<runId>) is reserved with a conditional put before anything is
  sent. A second answer to the same question, from either side, raises AnswerExists. A failed
  send marks the reservation failed (so it can be retried) and re-raises the cause.
* On success the item is marked sent, META.pendingAnswer is set (the UI shows "Sent ..." while
  Transform catches up), and transform.answer_sent is audited.

The table and the audit writer are injected; the Transform call is injected as ``send`` (the
caller passes lzcore.transform_ops.answer_message or a test fake).
"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from botocore.exceptions import ClientError

ANSWER_TEXT_LIMIT = 4000
AUDIT_TEXT_LIMIT = 500
# A reservation in "sending" older than this is treated as abandoned (the sender died before it finished) and
# may be taken over. The takeover reuses the stored idempotency token, so Transform drops a duplicate send.
SENDING_LEASE_SECONDS = 120
RESERVATION_CONDITION = (
    "attribute_not_exists(PK) OR #st = :failed OR (#st = :sending AND leaseUntil < :now)"
)


class AnswerExists(RuntimeError):
    """The question already has an answer (sent or being sent)."""


class AnswerRecordFailed(RuntimeError):
    """Transform accepted the reply but recording it failed. The answer is out: never retry or release it."""

    def __init__(self, message_id: str, sent_message_id: Optional[str], cause: Exception):
        self.message_id, self.sent_message_id, self.cause = message_id, sent_message_id, cause
        super().__init__(
            f"the reply to Transform message {message_id} was sent (Transform message {sent_message_id}) but "
            f"recording it failed: {type(cause).__name__}: {cause}"
        )


def answer_key(run_id: str, message_id: str) -> dict:
    return {"PK": f"RUN#{run_id}", "SK": f"ANSWER#{message_id}"}


def _is_stale_sending(item: Optional[dict], now: int) -> bool:
    return bool(item) and item.get("status") == "sending" and int(item.get("leaseUntil") or 0) < now


def existing_answer(table, run_id: str, message_id: str, now: int) -> Optional[dict]:
    """The ANSWER# item when the question has been answered or an answer is being sent right now.

    None when absent, failed, or stuck in "sending" past its lease (abandoned: it may be retried)."""
    item = table.get_item(Key=answer_key(run_id, message_id), ConsistentRead=True).get("Item")
    if item and item.get("status") == "sent":
        return item
    if item and item.get("status") == "sending" and not _is_stale_sending(item, now):
        return item
    return None


def validate_reply(pending: dict, option: Optional[str], text: Optional[str]) -> Optional[str]:
    """Shape checks shared by both callers. Returns the stripped text (or None for an option)."""
    if not isinstance(pending, dict) or pending.get("kind") != "message" or not pending.get("messageId"):
        raise ValueError("only Transform message questions (kind=message with a messageId) can be answered here")
    if (option is None) == (text is None):
        raise ValueError("send exactly one of option or text")
    if option is not None:
        if option not in (pending.get("options") or []):
            raise ValueError(f"option must be one of {pending.get('options')}")
        return None
    if not isinstance(text, str) or not 0 < len(text.strip()) <= ANSWER_TEXT_LIMIT:
        raise ValueError(f"text must be 1-{ANSWER_TEXT_LIMIT} characters")
    return text.strip()


def send_answer(
    *,
    table,
    audit: Callable[[str, dict], None],
    run_id: str,
    pending: dict,
    option: Optional[str],
    text: Optional[str],
    by: str,
    at: int,
    send: Callable[..., dict],
    find_reply: Callable[[int], Optional[str]],
    audit_extra: Optional[dict] = None,
) -> dict[str, Any]:
    """Reserve, send and record one answer to ``pending``. Returns the recorded answer.

    ``find_reply(since)`` returns the Transform message id of a USER reply in the job created at or after
    epoch ``since``, else None. It is used only when taking over an abandoned reservation: if the earlier
    sender's reply already reached Transform, that reply is recorded as sent and nothing is sent again.

    Raises ValueError for a malformed reply, AnswerExists when the question already has an answer,
    AnswerRecordFailed when Transform accepted the reply but recording it failed, and re-raises whatever
    ``send`` raised (QuestionChanged, TransformAccessDenied, ...) after marking the reservation failed and
    auditing transform.answer_failed.
    """
    reply_text = validate_reply(pending, option, text)
    message_id, job_id = pending["messageId"], pending["jobId"]
    key = answer_key(run_id, message_id)
    previous = table.get_item(Key=key, ConsistentRead=True).get("Item")
    takeover = _is_stale_sending(previous, at)
    token = previous["idempotencyToken"] if takeover else str(uuid.uuid4())
    answer = {"jobId": job_id, "messageId": message_id, "option": option, "text": reply_text, "by": by, "at": at}
    try:
        table.put_item(
            Item={**key, **answer, "status": "sending", "idempotencyToken": token,
                  "leaseUntil": at + SENDING_LEASE_SECONDS},
            ConditionExpression=RESERVATION_CONDITION,
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":failed": "failed", ":sending": "sending", ":now": at},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise AnswerExists(f"Transform message {message_id} already has an answer") from e

    if takeover:
        # The earlier sender died after reserving. If its reply reached Transform, record that reply as sent
        # instead of sending another one (the live re-check would refuse a second send anyway).
        already = find_reply(int(previous.get("at") or 0))
        if already:
            recovered = {**{k: previous.get(k) for k in ("jobId", "messageId", "option", "text", "by", "at")},
                         "status": "sent", "sentMessageId": already}
            _record_sent(table, audit, run_id, key, recovered, {"recovered": True, **(audit_extra or {})})
            return recovered

    try:
        sent = send(job_id=job_id, message_id=message_id, idempotency_token=token, option=option, text=reply_text)
    except Exception as e:  # noqa: BLE001 - recorded, released for retry and re-raised, never swallowed
        error = f"{type(e).__name__}: {e}"[:AUDIT_TEXT_LIMIT]
        table.update_item(
            Key=key,
            UpdateExpression="SET #st = :f, #e = :msg",
            ExpressionAttributeNames={"#st": "status", "#e": "error"},
            ExpressionAttributeValues={":f": "failed", ":msg": error},
        )
        audit("transform.answer_failed", {"jobId": job_id, "messageId": message_id, "error": error})
        raise

    # From here on the reply is out. A failure is reported as AnswerRecordFailed so no caller releases or
    # retries it as if nothing had been sent.
    sent_id = sent.get("sentMessageId") if isinstance(sent, dict) else None
    try:
        if not sent_id:
            raise RuntimeError(f"Transform returned no sentMessageId: {sent!r}")
        recorded = {**answer, "status": "sent", "sentMessageId": sent_id}
        _record_sent(table, audit, run_id, key, recorded, audit_extra or {})
    except Exception as e:  # noqa: BLE001 - converted to a named error that says the reply was sent
        raise AnswerRecordFailed(message_id, sent_id, e) from e
    return recorded


def _record_sent(table, audit: Callable[[str, dict], None], run_id: str, key: dict, recorded: dict, extra: dict) -> None:
    table.update_item(
        Key=key,
        UpdateExpression="SET #st = :s, sentMessageId = :m",
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={":s": "sent", ":m": recorded["sentMessageId"]},
    )
    table.update_item(
        Key={"PK": f"RUN#{run_id}", "SK": "META"},
        UpdateExpression="SET pendingAnswer = :a",
        ExpressionAttributeValues={":a": recorded},
    )
    audit(
        "transform.answer_sent",
        {
            "jobId": recorded["jobId"],
            "messageId": recorded["messageId"],
            "option": recorded.get("option"),
            "text": (recorded.get("text") or "")[:AUDIT_TEXT_LIMIT] or None,
            **extra,
        },
    )
