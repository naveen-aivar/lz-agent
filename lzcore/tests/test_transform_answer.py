"""answer_message: replies to the live Transform select question (POST /runs/{id}/answer).

Uses the scripted Transform boundary from test_transform_pending (FES + TCP fakes, no network).
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import transform_ops  # noqa: E402
from test_transform_pending import JOB, WS, FakeTransform, _Case, message, select  # noqa: E402

TOKEN = str(uuid.UUID(int=1))


def asking(mid="m2", labels=("Proceed", "Modify plan")):
    return [message("m1", "USER", 1, "Customer: Acme"), message(mid, "SYSTEM", 2, "Plan ready. Proceed?", [select(*labels)])]


class PendingChoices(_Case):
    def test_message_question_carries_message_id_and_values(self):
        out = self.poll(FakeTransform(messages=asking()))
        p = out["pendingHumanInput"]
        self.assertEqual(p["messageId"], "m2")
        self.assertEqual(p["options"], ["Proceed", "Modify plan"])
        self.assertEqual(p["choices"], [{"label": "Proceed", "value": "proceed"}, {"label": "Modify plan", "value": "modify plan"}])

    def test_task_question_has_no_message_id(self):
        out = self.poll(FakeTransform(tasks=[{"taskId": "t1", "status": "IN_PROGRESS", "title": "T", "createdAt": 1}]))
        self.assertIsNone(out["pendingHumanInput"]["messageId"])
        self.assertEqual(out["pendingHumanInput"]["choices"], [])


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, "aws-transform-mcp-server not installed")
class AnswerMessage(_Case):
    def answer(self, fake, **kw):
        self.install(fake)
        args = {"job_id": JOB, "message_id": "m2", "idempotency_token": TOKEN, "workspace": WS}
        args.update(kw)
        return transform_ops.answer_message(**args)

    def sent(self, fake):
        return [body for op, body in fake.calls if op == "SendMessage"]

    def test_option_is_sent_as_its_value_with_the_callers_token(self):
        fake = FakeTransform(messages=asking())
        out = self.answer(fake, option="Proceed")
        self.assertEqual(out, {"jobId": JOB, "answeredMessageId": "m2", "sentMessageId": "m-sent", "text": "proceed"})
        (body,) = self.sent(fake)
        self.assertEqual(body["text"], "proceed")
        self.assertEqual(body["idempotencyToken"], TOKEN)
        self.assertEqual(body["metadata"]["resourcesOnScreen"]["workspace"]["jobs"][0]["jobId"], JOB)

    def test_free_text_reply_is_stripped(self):
        fake = FakeTransform(messages=asking())
        self.assertEqual(self.answer(fake, text="  Use two regions  ")["text"], "Use two regions")
        self.assertEqual(self.sent(fake)[0]["text"], "Use two regions")

    def test_newer_question_raises_question_changed_and_sends_nothing(self):
        fake = FakeTransform(messages=asking(mid="m3"))
        with self.assertRaisesRegex(transform_ops.QuestionChanged, "no longer waiting on message m2; it now waits on message m3"):
            self.answer(fake, option="Proceed")
        self.assertEqual(self.sent(fake), [])

    def test_nothing_pending_raises_question_changed(self):
        fake = FakeTransform(messages=[message("m1", "USER", 1, "hi")])
        with self.assertRaisesRegex(transform_ops.QuestionChanged, "nothing is pending"):
            self.answer(fake, option="Proceed")

    def test_unknown_option_raises(self):
        fake = FakeTransform(messages=asking())
        with self.assertRaisesRegex(ValueError, "not one of the offered options"):
            self.answer(fake, option="Approve all")
        self.assertEqual(self.sent(fake), [])

    def test_option_without_value_raises(self):
        msgs = asking()
        msgs[1]["interactions"][0]["data"]["selectInteractionData"]["options"][0].pop("value")
        with self.assertRaisesRegex(RuntimeError, "has no value"):
            self.answer(FakeTransform(messages=msgs), option="Proceed")

    def test_exactly_one_of_option_or_text(self):
        with self.assertRaises(ValueError):
            transform_ops.answer_message(JOB, "m2", idempotency_token=TOKEN, option="Proceed", text="x")
        with self.assertRaises(ValueError):
            transform_ops.answer_message(JOB, "m2", idempotency_token=TOKEN)
        with self.assertRaisesRegex(ValueError, "1-4000"):
            transform_ops.answer_message(JOB, "m2", idempotency_token=TOKEN, text="   ")

    def test_send_without_message_in_response_raises(self):
        fake = FakeTransform(messages=asking())
        original = fake.call

        async def no_message(operation, request):
            if operation == "SendMessage":
                fake.calls.append((operation, {}))
                return {}
            return await original(operation, request)

        fake.call = no_message
        with self.assertRaisesRegex(RuntimeError, "returned no message"):
            self.answer(fake, option="Proceed")



class FreeTextQuestions(_Case):
    """A system message without options is a question only while the job reports AWAITING_HUMAN_INPUT."""

    def free_text(self):
        return [message("m1", "USER", 1, "Customer: Acme"),
                message("m2", "SYSTEM", 2, "What prefix and domain should account emails use?")]

    def test_awaiting_job_turns_the_newest_system_message_into_a_reply_question(self):
        p = self.poll(FakeTransform(status="AWAITING_HUMAN_INPUT", messages=self.free_text()))["pendingHumanInput"]
        self.assertEqual((p["kind"], p["messageId"], p["options"], p["choices"]), ("message", "m2", [], []))
        self.assertEqual(p["title"], "Transform is asking for a reply")

    def test_executing_job_with_a_plain_message_has_nothing_pending(self):
        self.assertIsNone(self.poll(FakeTransform(messages=self.free_text()))["pendingHumanInput"])

    def test_final_response_ends_the_turn_even_while_executing(self):
        msgs = self.free_text()
        msgs[-1]["processingInfo"] = {"messageType": "FINAL_RESPONSE"}
        p = self.poll(FakeTransform(messages=msgs))["pendingHumanInput"]
        self.assertEqual((p["kind"], p["messageId"], p["options"]), ("message", "m2", []))

    def test_thinking_message_is_not_a_question(self):
        msgs = self.free_text()
        msgs[-1]["processingInfo"] = {"messageType": "THINKING"}
        self.assertIsNone(self.poll(FakeTransform(messages=msgs))["pendingHumanInput"])

    def test_free_text_question_takes_a_text_reply(self):
        fake = self.install(FakeTransform(status="AWAITING_HUMAN_INPUT", messages=self.free_text()))
        out = transform_ops.answer_message(JOB, "m2", idempotency_token=TOKEN, text="aws-admin, acme.com", workspace=WS)
        self.assertEqual(out["text"], "aws-admin, acme.com")
        self.assertEqual([b["text"] for op, b in fake.calls if op == "SendMessage"], ["aws-admin, acme.com"])


class RecentConversation(_Case):
    def test_last_messages_oldest_first_with_options(self):
        msgs = [message(f"m{i}", "SYSTEM" if i % 2 else "USER", i, f"text {i}") for i in range(1, 6)]
        msgs.append(message("m6", "SYSTEM", 6, "x" * 3000, [select("Proceed", "Modify plan")]))
        self.install(FakeTransform(messages=msgs))

        out = transform_ops.recent_conversation(JOB, WS, limit=3)

        self.assertEqual([m["messageId"] for m in out], ["m4", "m5", "m6"])
        self.assertEqual(out[0]["origin"], "USER")
        self.assertEqual(out[-1]["options"], ["Proceed", "Modify plan"])
        self.assertEqual(len(out[-1]["text"]), transform_ops.CONVERSATION_TEXT_LIMIT)

    def test_message_without_origin_raises(self):
        msgs = [message("m1", "SYSTEM", 1, "hi")]
        msgs[0].pop("messageOrigin")
        self.install(FakeTransform(messages=msgs))
        with self.assertRaisesRegex(RuntimeError, "no messageOrigin"):
            transform_ops.recent_conversation(JOB, WS)


class QuestionPredicate(_Case):
    """poll_job and answer_message agree on what counts as a question without options."""

    def msgs(self, final):
        m = [message("m1", "USER", 1, "Customer: Acme"), message("m2", "SYSTEM", 2, "Working on it...")]
        if final:
            m[-1]["processingInfo"] = {"messageType": "FINAL_RESPONSE"}
        return m

    def answer(self, fake):
        self.install(fake)
        return transform_ops.answer_message(JOB, "m2", idempotency_token=TOKEN, text="Region is us-east-1.", workspace=WS)

    def test_pending_message_records_whether_the_job_itself_is_waiting(self):
        waiting = self.poll(FakeTransform(status="AWAITING_HUMAN_INPUT", messages=self.msgs(False)))["pendingHumanInput"]
        self.assertIs(waiting["jobAwaitingInput"], True)
        ended = self.poll(FakeTransform(status="EXECUTING", messages=self.msgs(True)))["pendingHumanInput"]
        self.assertIs(ended["jobAwaitingInput"], False)

    def test_reply_to_a_plain_message_is_refused_while_the_job_runs(self):
        with self.assertRaisesRegex(transform_ops.QuestionChanged, "nothing is pending"):
            self.answer(FakeTransform(status="EXECUTING", messages=self.msgs(False)))

    def test_reply_is_accepted_when_the_job_waits_or_the_turn_ended(self):
        self.assertEqual(self.answer(FakeTransform(status="AWAITING_HUMAN_INPUT", messages=self.msgs(False)))["answeredMessageId"], "m2")
        self.assertEqual(self.answer(FakeTransform(status="EXECUTING", messages=self.msgs(True)))["answeredMessageId"], "m2")

    def test_newest_system_message_id(self):
        self.install(FakeTransform(messages=self.msgs(True)))
        self.assertEqual(transform_ops.newest_system_message_id(JOB, WS), "m2")
        self.install(FakeTransform(messages=self.msgs(True) + [message("m3", "USER", 3, "ok")]))
        self.assertIsNone(transform_ops.newest_system_message_id(JOB, WS))
        self.install(FakeTransform(messages=[]))
        self.assertIsNone(transform_ops.newest_system_message_id(JOB, WS))


class OptionsAndReplies(_Case):
    def test_duplicate_option_labels_are_refused(self):
        msgs = [message("m1", "USER", 1, "hi"), message("m2", "SYSTEM", 2, "Pick", [select("Proceed", "Proceed")])]
        fake = self.install(FakeTransform(messages=msgs))
        with self.assertRaisesRegex(RuntimeError, "2 options labelled 'Proceed'"):
            transform_ops.answer_message(JOB, "m2", idempotency_token=TOKEN, option="Proceed", workspace=WS)
        self.assertEqual([op for op, _ in fake.calls if op == "SendMessage"], [])

    def test_user_reply_since(self):
        msgs = [message("m1", "SYSTEM", 1, "Q?"), message("m2", "USER", 5, "yes"), message("m3", "SYSTEM", 6, "ok")]
        self.install(FakeTransform(messages=msgs))
        t5 = msgs[1]["createdAt"].timestamp()
        self.assertEqual(transform_ops.user_reply_since(JOB, int(t5), WS), "m2")
        self.assertIsNone(transform_ops.user_reply_since(JOB, int(t5) + 1, WS))


if __name__ == "__main__":
    unittest.main()
