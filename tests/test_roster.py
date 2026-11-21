"""Tests for the attested roster product and per-member eligibility."""

import unittest

from charter_tool import roster
from charter_tool.util import MaterialError


def material(roll_records, cutoffs=None, votes=None, motions=None):
    return {
        "members": ["A", "B", "C", "D"],
        "roll": roll_records,
        "cutoffs": cutoffs or {"M1": [10, 0]},
        "votes": votes if votes is not None else {"M1": {"A": "yes", "B": "no"}},
        "motions": motions or [{"id": "M1", "article": "x", "old": "old", "next": "new"}],
        "articles": {"x": "old"},
        "before": [],
        "quorum": 2,
    }


def r(rid, t, seq, member, kind, motion=None, rev=1):
    row = {"id": rid, "rev": rev, "t": t, "seq": seq, "member": member, "kind": kind}
    if motion:
        row["motion"] = motion
    return row


class RosterTests(unittest.TestCase):
    def test_sealed_snapshot_separates_absent_and_recused(self):
        rows = [
            r("a", 1, 0, "A", "in"),
            r("b", 1, 1, "B", "in"),
            r("rb", 2, 0, "B", "recuse", "M1"),
        ]
        product = roster.build_roster(material(rows))
        snap = product["cutoffs"]["M1"]
        self.assertEqual(snap["eligible"], ["A"])
        reasons = {e["member"]: e["reason"] for e in snap["excluded"]}
        self.assertEqual(reasons, {"B": "recused", "C": "absent", "D": "absent"})
        recused = next(e for e in snap["excluded"] if e["member"] == "B")
        self.assertTrue(recused["present"])
        self.assertEqual(recused["recusal"]["record"]["id"], "rb")

    def test_missing_ballot_is_abstain_not_ineligible(self):
        rows = [r("a", 1, 0, "A", "in"), r("b", 1, 1, "B", "in")]
        product = roster.build_roster(
            material(rows, votes={})  # ballot never recorded for M1
        )
        snap = product["cutoffs"]["M1"]
        verdict = roster.eligibility_verdict(snap, "A", None)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["counted"], "abstain")
        self.assertEqual(verdict["explanation"], "ballot_not_recorded")
        tally = roster.tally(snap)
        self.assertEqual(tally["abstain"], ["A", "B"])
        self.assertEqual(tally["yes_count"], 0)

    def test_eligible_but_no_hand_raised_is_abstain(self):
        rows = [r("a", 1, 0, "A", "in"), r("b", 1, 1, "B", "in")]
        product = roster.build_roster(material(rows, votes={"M1": {"A": "yes"}}))
        snap = product["cutoffs"]["M1"]
        verdict = roster.eligibility_verdict(snap, "B", None)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["explanation"], "no_hand_raised")

    def test_ineligible_member_with_stray_ballot_is_not_counted(self):
        rows = [
            r("a", 1, 0, "A", "in"),
            r("b", 1, 1, "B", "in"),
            r("rb", 2, 0, "B", "recuse", "M1"),
        ]
        product = roster.build_roster(
            material(rows, votes={"M1": {"A": "yes", "B": "yes"}})
        )
        snap = product["cutoffs"]["M1"]
        verdict = roster.eligibility_verdict(snap, "B", "yes")
        self.assertFalse(verdict["eligible"])
        self.assertIsNone(verdict["counted"])
        tally = roster.tally(snap)
        self.assertEqual(tally["ineligible_ballots"], ["B"])
        self.assertEqual(tally["yes_count"], 1)

    def test_roster_carries_concrete_basis_records(self):
        rows = [
            r("a1", 1, 0, "A", "in"),
            r("a2", 5, 0, "A", "out"),
            r("a3", 6, 0, "A", "in"),
        ]
        product = roster.build_roster(material(rows, cutoffs={"M1": [5, 0]}))
        excluded = {
            e["member"]: e for e in product["cutoffs"]["M1"]["excluded"]
        }
        self.assertEqual(excluded["A"]["reason"], "absent")
        self.assertEqual(excluded["A"]["basis"]["id"], "a2")

    def test_missing_cutoff_refused(self):
        rows = [r("a", 1, 0, "A", "in")]
        with self.assertRaises(MaterialError) as ctx:
            roster.build_roster(material(rows, cutoffs={"M9": [1, 0]}))
        self.assertEqual(ctx.exception.code, "missing_cutoff")

    def test_bad_vote_value_refused(self):
        rows = [r("a", 1, 0, "A", "in")]
        with self.assertRaises(MaterialError) as ctx:
            roster.build_roster(material(rows, votes={"M1": {"A": "maybe"}}))
        self.assertEqual(ctx.exception.code, "bad_vote")

    def test_seal_is_deterministic(self):
        rows = [r("a", 1, 0, "A", "in")]
        first = roster.build_roster(material(rows))
        second = roster.build_roster(material(rows))
        self.assertEqual(first["sealed"], second["sealed"])


if __name__ == "__main__":
    unittest.main()
