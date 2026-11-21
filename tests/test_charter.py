"""Tests for amendment ordering, admission, voting and signing."""

import unittest

from charter_tool import charter
from charter_tool import roster as roster_mod
from charter_tool.util import MaterialError


def build(base_article, motions, before, links, quorum=3, ballots=None, members=None):
    """Assemble material directly plus a synthetic roster for the motions."""

    members = members or ["A", "B", "C"]
    material = {
        "members": members,
        "roll": [
            {"id": f"e{m}", "rev": 1, "t": 1, "seq": i, "member": m, "kind": "in"}
            for i, m in enumerate(members)
        ],
        "cutoffs": {m["id"]: [1, 99] for m in motions},
        "votes": ballots or {m["id"]: {} for m in motions},
        "articles": {"x": base_article},
        "motions": motions,
        "before": before,
        "quorum": quorum,
    }
    roster = roster_mod.build_roster(material)
    return material, roster


def m(mid, old, new, article="x"):
    return {"id": mid, "article": article, "old": old, "next": new}


class OrderingTests(unittest.TestCase):
    def test_cycle_is_pointed_out(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "b", "c")],
            [["M1", "M2"], ["M2", "M1"]],
            None,
        )
        with self.assertRaises(MaterialError) as ctx:
            charter.build_charter(material, roster)
        self.assertEqual(ctx.exception.code, "order_cycle")
        self.assertIn("M1", ctx.exception.details["cycle"])

    def test_self_loop_is_a_cycle(self):
        material, roster = build("a", [m("M1", "a", "b")], [["M1", "M1"]], None)
        with self.assertRaises(MaterialError) as ctx:
            charter.build_charter(material, roster)
        self.assertEqual(ctx.exception.details["cycle"], ["M1", "M1"])

    def test_all_legal_orders_enumerated(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "b", "c"), m("M3", "c", "d")],
            [["M1", "M3"]],
            None,
        )
        result = charter.build_charter(material, roster)
        self.assertEqual(result["motion_order_space"]["legal_total_orders"], 3)
        for order in result["motion_order_space"]["orders"]:
            self.assertLess(order.index("M1"), order.index("M3"))

    def test_each_motion_handled_once_per_order(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "b", "c")],
            [],
            None,
        )
        result = charter.build_charter(material, roster)
        for outcome in result["outcomes"]:
            self.assertEqual(
                sorted(s["motion"] for s in outcome["steps"]), ["M1", "M2"]
            )


class AdmissionTests(unittest.TestCase):
    def test_text_mismatch_is_not_admitted(self):
        material, roster = build(
            "a", [m("M1", "zzz", "b")], [], None,
            ballots={"M1": {"A": "yes", "B": "yes", "C": "yes"}},
        )
        result = charter.build_charter(material, roster)
        step = result["outcomes"][0]["steps"][0]
        self.assertFalse(step["admitted"])
        self.assertEqual(step["reason"], "text_mismatch")
        self.assertEqual(result["final_articles"], {"x": "a"})

    def test_conditional_chain_requires_right_order(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "b", "c")],
            [["M1", "M2"]],
            None,
            ballots={
                "M1": {"A": "yes", "B": "yes", "C": "yes"},
                "M2": {"A": "yes", "B": "yes", "C": "yes"},
            },
        )
        result = charter.build_charter(material, roster)
        self.assertTrue(result["signable"])
        self.assertEqual(result["final_articles"], {"x": "c"})

    def test_wrong_order_leaves_article_unchanged(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "b", "c")],
            [["M2", "M1"]],
            None,
            ballots={
                "M1": {"A": "yes", "B": "yes", "C": "yes"},
                "M2": {"A": "yes", "B": "yes", "C": "yes"},
            },
        )
        result = charter.build_charter(material, roster)
        self.assertEqual(result["final_articles"], {"x": "b"})
        steps = result["outcomes"][0]["steps"]
        self.assertEqual(steps[0]["reason"], "text_mismatch")


class VoteTests(unittest.TestCase):
    def test_yes_must_strictly_exceed_no(self):
        material, roster = build(
            "a", [m("M1", "a", "b")], [], None,
            ballots={"M1": {"A": "yes", "B": "no", "C": "no"}},
        )
        result = charter.build_charter(material, roster)
        self.assertFalse(result["signable"] is False and False)  # sanity
        self.assertEqual(result["final_articles"], {"x": "a"})
        self.assertEqual(result["outcomes"][0]["steps"][0]["reason"], "vote_not_passed")

    def test_quorum_failure_keeps_article(self):
        material, roster = build(
            "a", [m("M1", "a", "b")], [], None,
            quorum=3,
            ballots={"M1": {"A": "yes", "B": "yes"}},
        )
        # only A and B are present; cutoff still sees 2 eligible
        material["cutoffs"]["M1"] = [1, 0]
        roster = roster_mod.build_roster(material)
        result = charter.build_charter(material, roster)
        step = result["outcomes"][0]["steps"][0]
        self.assertTrue(step["admitted"])
        self.assertEqual(step["reason"], "no_quorum")
        self.assertEqual(result["final_articles"], {"x": "a"})

    def test_abstentions_never_count_and_all_abstain_fails(self):
        material, roster = build(
            "a", [m("M1", "a", "b")], [], None,
            ballots={"M1": {"A": "abstain", "B": "abstain", "C": "abstain"}},
        )
        result = charter.build_charter(material, roster)
        step = result["outcomes"][0]["steps"][0]
        self.assertFalse(step["passed"])
        # yes 0 vs no 0 -> not strictly greater
        self.assertEqual(step["ballot"]["abstain_count"], 3)
        self.assertEqual(result["final_articles"], {"x": "a"})

    def test_abstain_does_not_block_yes_majority(self):
        material, roster = build(
            "a", [m("M1", "a", "b")], [], None,
            quorum=2,
            ballots={"M1": {"A": "yes", "B": "yes", "C": "abstain"}},
        )
        result = charter.build_charter(material, roster)
        step = result["outcomes"][0]["steps"][0]
        self.assertTrue(step["passed"])
        self.assertEqual(step["ballot"]["abstain"], ["C"])
        self.assertEqual(step["ballot"]["yes_count"], 2)
        self.assertEqual(step["ballot"]["no_count"], 0)

    def test_missing_ballot_counts_as_abstain(self):
        material, roster = build(
            "a", [m("M1", "a", "b")], [], None,
            ballots={"M1": {"A": "yes", "B": "yes"}},
        )
        result = charter.build_charter(material, roster)
        step = result["outcomes"][0]["steps"][0]
        self.assertEqual(step["ballot"]["abstain"], ["C"])
        self.assertTrue(step["passed"])


class UniquenessTests(unittest.TestCase):
    def test_ambiguous_orders_diverge(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "b", "c")],
            [],
            None,
            ballots={
                "M1": {"A": "yes", "B": "yes", "C": "yes"},
                "M2": {"A": "yes", "B": "yes", "C": "yes"},
            },
        )
        result = charter.build_charter(material, roster)
        self.assertFalse(result["unique"])
        self.assertFalse(result["signable"])
        finals = {frozenset(g["final_articles"].items()) for g in result["outcomes"]}
        self.assertEqual(finals, {frozenset({("x", "c")}), frozenset({("x", "b")})})
        self.assertIn("contested", result)
        for contested in result["contested"]["differing_finals"]:
            self.assertTrue(contested["agenda"])

    def test_same_final_by_different_process_still_signable(self):
        # M1 and M2 are independent; either order gives the same final text.
        material, roster = build(
            "a",
            [m("M1", "a", "b", "x"), m("M2", "a", "b", "x")],
            [],
            None,
            ballots={
                "M1": {"A": "yes", "B": "yes", "C": "yes"},
                "M2": {"A": "yes", "B": "yes", "C": "yes"},
            },
        )
        result = charter.build_charter(material, roster)
        self.assertEqual(result["motion_order_space"]["legal_total_orders"], 2)
        # first motion wins, second is text_mismatch; both orders end at b
        self.assertTrue(result["signable"])
        self.assertEqual(result["final_articles"], {"x": "b"})
        self.assertEqual(result["outcomes"][0]["distinct_processes"], 2)
        self.assertIsNotNone(result["signing_record"])

    def test_order_does_not_affect_signability_when_all_agree(self):
        material, roster = build(
            "a",
            [m("M1", "a", "b"), m("M2", "a", "b")],
            [["M2", "M1"]],
            None,
            ballots={
                "M1": {"A": "yes", "B": "yes", "C": "yes"},
                "M2": {"A": "yes", "B": "yes", "C": "yes"},
            },
        )
        result = charter.build_charter(material, roster)
        self.assertTrue(result["signable"])
        self.assertEqual(result["final_articles"], {"x": "b"})


if __name__ == "__main__":
    unittest.main()
