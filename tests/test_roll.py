"""Tests for revision arbitration and roster folding."""

import unittest

from charter_tool import roll
from charter_tool.util import MaterialError

MEMBERS = ["A", "B", "C"]


def rec(rid, rev, t, seq, member, kind, motion=None, **extra):
    row = {"id": rid, "rev": rev, "t": t, "seq": seq, "member": member, "kind": kind}
    if motion is not None:
        row["motion"] = motion
    row.update(extra)
    return row


class ArbitrationTests(unittest.TestCase):
    def test_highest_revision_wins(self):
        ledger = roll.build_ledger(
            MEMBERS,
            [
                rec("e", 1, 1, 0, "A", "out"),
                rec("e", 2, 1, 0, "A", "in"),
            ],
        )
        self.assertEqual([r["rev"] for r in ledger.records], [2])
        self.assertEqual(ledger.records[0]["kind"], "in")

    def test_cancel_retracts_whole_record(self):
        ledger = roll.build_ledger(
            MEMBERS,
            [
                rec("eA", 1, 1, 0, "A", "in"),
                {"id": "eA", "rev": 2, "kind": "cancel"},
            ],
        )
        self.assertEqual(ledger.records, [])
        self.assertEqual(ledger.cancels[0]["id"], "eA")
        snap = roll.eligible_at(ledger, MEMBERS, "M1", 99, 99)
        self.assertEqual(snap["eligible"], [])

    def test_lower_revision_is_ignored(self):
        ledger = roll.build_ledger(
            MEMBERS,
            [
                rec("eA", 2, 2, 0, "A", "in"),
                rec("eA", 1, 1, 0, "A", "out"),  # obsolete, never applied
            ],
        )
        self.assertEqual(len(ledger.records), 1)
        self.assertEqual(ledger.records[0]["t"], 2)

    def test_conflicting_same_revision_refused(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(
                MEMBERS,
                [
                    rec("e", 1, 1, 0, "A", "in"),
                    rec("e", 1, 1, 0, "A", "out"),
                ],
            )
        self.assertEqual(ctx.exception.code, "conflicting_revision")

    def test_identical_same_revision_deduplicated(self):
        ledger = roll.build_ledger(
            MEMBERS,
            [
                rec("e", 1, 1, 0, "A", "in"),
                rec("e", 1, 1, 0, "A", "in"),
            ],
        )
        self.assertEqual(len(ledger.records), 1)

    def test_duplicate_order_key_refused(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(
                MEMBERS,
                [
                    rec("x", 1, 5, 0, "A", "in"),
                    rec("y", 1, 5, 0, "B", "in"),
                ],
            )
        self.assertEqual(ctx.exception.code, "duplicate_order_key")

    def test_recuse_requires_motion(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(MEMBERS, [rec("r", 1, 1, 0, "A", "recuse")])
        self.assertEqual(ctx.exception.code, "missing_motion")

    def test_unknown_kind_refused(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(MEMBERS, [rec("r", 1, 1, 0, "A", "sleep")])
        self.assertEqual(ctx.exception.code, "bad_kind")

    def test_unknown_member_refused(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(MEMBERS, [rec("r", 1, 1, 0, "Z", "in")])
        self.assertEqual(ctx.exception.code, "unknown_member")

    def test_revision_must_be_positive(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(MEMBERS, [rec("r", 0, 1, 0, "A", "in")])
        self.assertEqual(ctx.exception.code, "bad_number")

    def test_booleans_are_not_integers(self):
        with self.assertRaises(MaterialError) as ctx:
            roll.build_ledger(MEMBERS, [rec("r", True, 1, 0, "A", "in")])
        self.assertEqual(ctx.exception.code, "bad_number")

    def test_initial_state_everybody_out(self):
        ledger = roll.build_ledger(MEMBERS, [])
        snap = roll.eligible_at(ledger, MEMBERS, "M1", 0, 0)
        self.assertEqual(snap["eligible"], [])
        self.assertEqual([e["reason"] for e in snap["excluded"]], ["absent"] * 3)


class FoldingTests(unittest.TestCase):
    def test_recusal_survives_departure_and_arrival(self):
        rows = [
            rec("eA1", 1, 1, 0, "A", "in"),
            rec("rA", 1, 2, 0, "A", "recuse", "M1"),
            rec("eA2", 1, 3, 0, "A", "out"),
            rec("eA3", 1, 4, 0, "A", "in"),
        ]
        ledger = roll.build_ledger(MEMBERS, rows)
        state = roll.replay_to(ledger, 4, 0)["A"]
        self.assertTrue(state.present)
        self.assertIn("M1", state.recused)

    def test_unrecuse_restores_eligibility(self):
        rows = [
            rec("eA", 1, 1, 0, "A", "in"),
            rec("rA", 1, 2, 0, "A", "recuse", "M1"),
            rec("uA", 1, 3, 0, "A", "unrecuse", "M1"),
        ]
        ledger = roll.build_ledger(MEMBERS, rows)
        snap = roll.eligible_at(ledger, MEMBERS, "M1", 3, 0)
        self.assertIn("A", snap["eligible"])
        basis = roll._recusal_basis(ledger, "A", "M1", 3, 0)
        self.assertFalse(basis["active"])
        self.assertEqual(basis["record"]["id"], "uA")

    def test_recusal_only_affects_named_motion(self):
        rows = [
            rec("eA", 1, 1, 0, "A", "in"),
            rec("rA", 1, 2, 0, "A", "recuse", "M1"),
        ]
        ledger = roll.build_ledger(MEMBERS, rows)
        self.assertNotIn("A", roll.eligible_at(ledger, MEMBERS, "M1", 2, 0)["eligible"])
        self.assertIn("A", roll.eligible_at(ledger, MEMBERS, "M2", 2, 0)["eligible"])

    def test_cutoff_is_inclusive_and_time_ordered(self):
        rows = [
            rec("eA", 1, 1, 0, "A", "in"),
            rec("eB", 1, 2, 0, "B", "in"),
            rec("eC", 1, 3, 0, "C", "in"),
        ]
        ledger = roll.build_ledger(MEMBERS, rows)
        self.assertEqual(roll.eligible_at(ledger, MEMBERS, "M1", 2, 0)["eligible"], ["A", "B"])
        self.assertEqual(
            roll.eligible_at(ledger, MEMBERS, "M1", 3, 0)["eligible"], ["A", "B", "C"]
        )

    def test_same_time_uses_seq(self):
        rows = [
            rec("late", 1, 1, 5, "B", "in"),
            rec("early", 1, 1, 1, "A", "in"),
        ]
        ledger = roll.build_ledger(MEMBERS, rows)
        snap = roll.eligible_at(ledger, MEMBERS, "M1", 1, 1)
        self.assertEqual(snap["eligible"], ["A"])
        snap2 = roll.eligible_at(ledger, MEMBERS, "M1", 1, 5)
        self.assertEqual(snap2["eligible"], ["A", "B"])

    def test_in_and_out_states_are_independent(self):
        rows = [
            rec("eA", 1, 1, 0, "A", "in"),
            rec("rA", 1, 2, 0, "A", "recuse", "M1"),
            rec("oA", 1, 3, 0, "A", "out"),
        ]
        ledger = roll.build_ledger(MEMBERS, rows)
        state = roll.replay_to(ledger, 3, 0)["A"]
        self.assertFalse(state.present)
        self.assertTrue(state.recused)


if __name__ == "__main__":
    unittest.main()
