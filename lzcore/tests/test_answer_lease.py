"""send_answer: an abandoned "sending" reservation can be taken over (with its token); a live one cannot."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore.transform_answers import (  # noqa: E402
    RECOVERY_CONDITION, RESERVATION_CONDITION, SENDING_LEASE_SECONDS, AnswerExists, AnswerRecordFailed,
    SendOutcomeUnknown, existing_answer, send_answer)

RUN, MID = "run1", "m-1"
PENDING = {"kind": "message", "jobId": "job-1", "messageId": MID, "options": ["Landing Zone"], "workspaceId": "ws"}


class Table:
    def __init__(self):
        self.items = {}
        self.updates = []

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        cur, v = self.items.get((Item["PK"], Item["SK"])), ExpressionAttributeValues
        if ConditionExpression == RECOVERY_CONDITION:
            free = (cur is not None and cur["status"] == v[":sending"] and cur["idempotencyToken"] == v[":tok"]
                    and cur["leaseUntil"] == v[":lease"])
        else:
            assert ConditionExpression == RESERVATION_CONDITION
            free = (cur is None or cur["status"] == v[":failed"]
                    or (cur["status"] == v[":sending"] and int(cur.get("leaseUntil") or 0) < v[":now"]))
        if not free:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")
        self.items[(Item["PK"], Item["SK"])] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None, ExpressionAttributeNames=None):
        self.updates.append((Key, UpdateExpression))
        item = self.items.setdefault((Key["PK"], Key["SK"]), dict(Key))
        if "#st = :s" in UpdateExpression:
            item["status"] = ExpressionAttributeValues[":s"]
            item["sentMessageId"] = ExpressionAttributeValues[":m"]
        elif "#st = :f" in UpdateExpression:
            item["status"] = "failed"
            item["error"] = ExpressionAttributeValues[":msg"]


class Lease(unittest.TestCase):
    def send(self, table, at, tokens, already=None, audits=None, send_error=None, find_reply=None, by="agent"):
        def fake(**kw):
            tokens.append(kw["idempotency_token"])
            if send_error is not None:
                raise send_error
            return {"sentMessageId": "sent-1"}
        return send_answer(table=table, audit=lambda a, d: (audits if audits is not None else []).append((a, d)),
                           run_id=RUN, pending=PENDING, option="Landing Zone", text=None, by=by, at=at,
                           send=fake, find_reply=find_reply or (lambda: already))

    def stuck(self, table, leased_at, token="tok-1"):
        table.items[(f"RUN#{RUN}", f"ANSWER#{MID}")] = {
            "PK": f"RUN#{RUN}", "SK": f"ANSWER#{MID}", "status": "sending", "idempotencyToken": token,
            "leaseUntil": leased_at + SENDING_LEASE_SECONDS}

    def test_live_reservation_blocks_a_second_sender(self):
        t = Table(); self.stuck(t, leased_at=1000)
        with self.assertRaises(AnswerExists):
            self.send(t, at=1000 + SENDING_LEASE_SECONDS - 1, tokens=[])

    def test_abandoned_reservation_is_taken_over_with_the_same_token(self):
        t = Table(); self.stuck(t, leased_at=1000, token="tok-original")
        tokens = []
        out = self.send(t, at=1000 + SENDING_LEASE_SECONDS + 1, tokens=tokens)
        self.assertEqual(tokens, ["tok-original"])
        self.assertEqual(out["status"], "sent")

    def test_takeover_records_an_answer_that_already_reached_transform_instead_of_resending(self):
        t = Table(); self.stuck(t, leased_at=1000)
        t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")].update(at=990, option="Landing Zone", jobId="job-1", messageId=MID)
        tokens, audits = [], []
        out = self.send(t, at=1000 + SENDING_LEASE_SECONDS + 1, tokens=tokens, already="user-msg-9", audits=audits)
        self.assertEqual(tokens, [])  # nothing sent again
        self.assertEqual((out["status"], out["sentMessageId"]), ("sent", "user-msg-9"))
        self.assertEqual(t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]["status"], "sent")
        self.assertTrue(audits[-1][1]["recovered"])

    def test_recovered_reply_keeps_the_original_sender_and_choice(self):
        t = Table(); self.stuck(t, leased_at=1000)
        t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")].update(
            at=990, option=None, text="Custom: two OUs", by="user-sub-1", jobId="job-1", messageId=MID)
        audits = []
        out = self.send(t, at=1000 + SENDING_LEASE_SECONDS + 1, tokens=[], already="user-msg-9", audits=audits,
                        by="agent")
        item = t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]
        for rec in (out, item):
            self.assertEqual((rec["by"], rec["option"], rec["text"], rec["at"]),
                             ("user-sub-1", None, "Custom: two OUs", 990))
            self.assertTrue(rec["recovered"])
            self.assertEqual(rec["sentMessageId"], "user-msg-9")
        self.assertEqual(audits[-1][0], "transform.answer_sent")
        self.assertEqual(audits[-1][1]["originalSender"], "user-sub-1")

    def test_takeover_when_find_reply_fails_marks_the_reservation_failed(self):
        t = Table(); self.stuck(t, leased_at=1000)
        audits, tokens = [], []

        def broken():
            raise RuntimeError("ListMessages throttled")

        with self.assertRaises(RuntimeError):
            self.send(t, at=1000 + SENDING_LEASE_SECONDS + 1, tokens=tokens, audits=audits, find_reply=broken)
        item = t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]
        self.assertEqual(item["status"], "failed")
        self.assertIn("ListMessages throttled", item["error"])
        self.assertEqual(tokens, [])
        self.assertEqual(audits[-1][0], "transform.answer_failed")
        # Released: a later sender can reserve again.
        self.assertIsNone(existing_answer(t, RUN, MID, now=10**9))

    def test_unknown_outcome_with_the_reply_in_transform_is_recorded_sent(self):
        t, audits = Table(), []
        out = self.send(t, at=500, tokens=[], audits=audits, send_error=SendOutcomeUnknown("read timeout"),
                        already="user-msg-7")
        self.assertEqual((out["status"], out["sentMessageId"]), ("sent", "user-msg-7"))
        self.assertEqual(t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]["status"], "sent")
        self.assertEqual(audits[-1][0], "transform.answer_sent")
        self.assertIn("read timeout", audits[-1][1]["confirmedAfterError"])

    def test_unknown_outcome_without_a_reply_is_marked_failed_and_reraised(self):
        t, audits = Table(), []
        with self.assertRaises(SendOutcomeUnknown):
            self.send(t, at=500, tokens=[], audits=audits, send_error=SendOutcomeUnknown("connection closed"))
        self.assertEqual(t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]["status"], "failed")
        self.assertEqual(audits[-1][0], "transform.answer_failed")

    def test_unknown_outcome_when_the_check_also_fails_is_marked_failed(self):
        t, audits = Table(), []

        def broken():
            raise RuntimeError("ListMessages down")

        with self.assertRaises(SendOutcomeUnknown):
            self.send(t, at=500, tokens=[], audits=audits, send_error=SendOutcomeUnknown("timeout"),
                      find_reply=broken)
        item = t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]
        self.assertEqual(item["status"], "failed")
        self.assertIn("ListMessages down", item["error"])

    def test_refused_send_never_looks_for_a_reply(self):
        t, calls = Table(), []

        def spy():
            calls.append(1)
            return "user-msg-1"

        with self.assertRaises(PermissionError):
            self.send(t, at=500, tokens=[], send_error=PermissionError("AccessDenied"), find_reply=spy)
        self.assertEqual(calls, [])
        self.assertEqual(t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]["status"], "failed")

    def test_recovery_record_failure_is_answer_record_failed(self):
        class Broken(Table):
            def update_item(self, Key, UpdateExpression, **kw):
                if Key["SK"] == "META":
                    raise RuntimeError("DynamoDB down")
                return super().update_item(Key, UpdateExpression, **kw)
        t = Broken(); self.stuck(t, leased_at=1000)
        with self.assertRaises(AnswerRecordFailed) as ctx:
            self.send(t, at=1000 + SENDING_LEASE_SECONDS + 1, tokens=[], already="user-msg-9")
        self.assertEqual(ctx.exception.sent_message_id, "user-msg-9")

    def test_record_failure_after_the_send_is_reported_as_sent(self):

        class Broken(Table):
            def update_item(self, Key, UpdateExpression, **kw):
                if "#st = :s" in UpdateExpression:
                    raise RuntimeError("DynamoDB down")
                return super().update_item(Key, UpdateExpression, **kw)

        t, tokens = Broken(), []
        with self.assertRaises(AnswerRecordFailed) as ctx:
            self.send(t, at=500, tokens=tokens)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(ctx.exception.sent_message_id, "sent-1")
        self.assertIn("was sent", str(ctx.exception))

    def test_existing_answer_ignores_an_abandoned_reservation_but_not_a_live_or_sent_one(self):
        t = Table(); self.stuck(t, leased_at=1000)
        self.assertIsNone(existing_answer(t, RUN, MID, now=1000 + SENDING_LEASE_SECONDS + 1))
        self.assertIsNotNone(existing_answer(t, RUN, MID, now=1000 + 5))
        t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]["status"] = "sent"
        self.assertIsNotNone(existing_answer(t, RUN, MID, now=10**9))

    def test_new_reservation_gets_a_fresh_token_and_a_lease(self):
        t = Table(); tokens = []
        self.send(t, at=500, tokens=tokens)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(t.items[(f"RUN#{RUN}", f"ANSWER#{MID}")]["leaseUntil"], 500 + SENDING_LEASE_SECONDS)


if __name__ == "__main__":
    unittest.main()
