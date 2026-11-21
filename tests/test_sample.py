"""End-to-end tests against the shipped ``case.json``."""

import json
import tempfile
import unittest
from pathlib import Path

from charter_tool import charter, materials, pipeline
from charter_tool import roster as roster_mod
from charter_tool.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case.json"


def load():
    return json.loads(CASE.read_text(encoding="utf-8"))


def case(name):
    envelope = load()
    for item in materials.material_cases(envelope):
        if item["name"] == name:
            return item["material"]
    raise KeyError(name)


class SampleCaseTests(unittest.TestCase):
    def test_base_signs_combined_reading(self):
        material = case("base")
        report = pipeline.analyze_case("base", material)
        self.assertTrue(report["verdict"]["signable"])
        self.assertEqual(report["verdict"]["final_articles"], {"use": "合读"})
        self.assertEqual(report["verdict"]["legal_total_orders"], 1)

    def test_recusal_makes_motion_one_fail_and_final_is_self_study(self):
        material = case("recusal")
        report = pipeline.analyze_case("recusal", material)
        self.assertTrue(report["verdict"]["signable"])
        self.assertEqual(report["verdict"]["final_articles"], {"use": "自习"})
        snap = report["roster"]["cutoffs"]["M1"]
        self.assertEqual(snap["eligible"], ["B", "C"])
        step = report["charter"]["outcomes"][0]["steps"][0]
        self.assertTrue(step["admitted"])
        self.assertEqual(step["reason"], "no_quorum")
        member_a = roster_mod.eligibility_verdict(snap, "A", "yes")
        self.assertFalse(member_a["eligible"])
        self.assertEqual(member_a["reason"], "recused")

    def test_reverse_order_signs_newspaper(self):
        material = case("reverse-order")
        report = pipeline.analyze_case("reverse-order", material)
        self.assertTrue(report["verdict"]["signable"])
        self.assertEqual(report["verdict"]["final_articles"], {"use": "报刊"})

    def test_missing_order_is_contested_with_two_legal_agendas(self):
        material = case("missing-order")
        report = pipeline.analyze_case("missing-order", material)
        self.assertFalse(report["verdict"]["signable"])
        self.assertEqual(
            [f for f in report["verdict"]["differing_finals"]],
            [{"use": "合读"}, {"use": "报刊"}],
        )
        orders = report["charter"]["motion_order_space"]["orders"]
        self.assertEqual(orders, [["M1", "M2"], ["M2", "M1"]])
        agendas = [f["agenda"] for f in report["charter"]["contested"]["differing_finals"]]
        self.assertIn(["M1", "M2"], agendas)
        self.assertIn(["M2", "M1"], agendas)

    def test_roll_only_supplement_keeps_original_cutoffs(self):
        # recusal variant only appends a roll record; ballots are untouched.
        base = case("base")
        recusal = case("recusal")
        self.assertEqual(base["cutoffs"], recusal["cutoffs"])
        self.assertEqual(base["votes"], recusal["votes"])
        self.assertEqual(len(recusal["roll"]), len(base["roll"]) + 1)

    def test_variant_application_is_isolated(self):
        envelope = load()
        cases = materials.material_cases(envelope)
        base = cases[0]["material"]
        before_len = len(base["roll"])
        materials.material_cases(envelope)  # apply again
        self.assertEqual(len(base["roll"]), before_len)


class CliTests(unittest.TestCase):
    def test_analyze_writes_reopenable_products(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = cli_main(["analyze", str(CASE), "--out", tmp])
            self.assertEqual(rc, 0)
            base_report = Path(tmp) / "base.report.json"
            signing = Path(tmp) / "base.signing.json"
            self.assertTrue(base_report.exists())
            self.assertTrue(signing.exists())
            record = pipeline.load_signing_record(signing)
            self.assertTrue(record["verified"])
            rebuilt = pipeline.analyze_case("base", case("base"))
            self.assertEqual(
                record["final_articles"], rebuilt["charter"]["final_articles"]
            )
            self.assertEqual(record["roster_seal"], rebuilt["roster"]["sealed"])

    def test_tampered_signing_record_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli_main(["charter", str(CASE), "--case", "base", "--out", tmp])
            path = Path(tmp) / "base.signing.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["final_articles"] = {"use": "伪造"}
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(Exception):
                pipeline.load_signing_record(path)

    def test_member_query_on_recusal_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = cli_main(
                [
                    "member",
                    str(CASE),
                    "A",
                    "M1",
                    "--case",
                    "recusal",
                    "--json",
                ]
            )
            self.assertEqual(rc, 0)
        self.assertEqual(rc, 0)

    def test_missing_case_choice_is_refused(self):
        rc = cli_main(["charter", str(CASE)])
        self.assertEqual(rc, 2)

    def test_unknown_case_is_refused(self):
        rc = cli_main(["charter", str(CASE), "--case", "nope"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
