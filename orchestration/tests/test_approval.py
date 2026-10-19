import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from common import verify_approval  # noqa: E402

GOOD = {"sha": "abc", "expires": 2000, "approver": "u2"}


class ApprovalTests(unittest.TestCase):
    def test_missing_approval_denied(self):
        self.assertFalse(verify_approval(None, "abc", 1000)[0])

    def test_sha_mismatch_denied(self):
        ok, reason = verify_approval(GOOD, "different", 1000)
        self.assertFalse(ok)
        self.assertIn("changed", reason)

    def test_expired_denied(self):
        self.assertFalse(verify_approval(GOOD, "abc", 2000)[0])

    def test_self_approval_denied(self):
        self.assertFalse(verify_approval(GOOD, "abc", 1000, requester="u2")[0])

    def test_valid_approval_allowed(self):
        self.assertEqual(verify_approval(GOOD, "abc", 1000, requester="u1"), (True, "ok"))


if __name__ == "__main__":
    unittest.main()
