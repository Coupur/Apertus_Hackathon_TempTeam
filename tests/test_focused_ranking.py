"""Ranking behavior, provenance, migration, and evaluation metric regressions."""
import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from navigator.focused.crawl import consolidate
from navigator.focused.evaluate import metrics, ranking_metrics, wilson
from navigator.focused.models import Document
from navigator.focused.ranking import WEIGHTS, assess_evidence, rank, ranking_summary
from navigator.focused.selection import evaluate, validate_findings
from navigator.focused.store import Store, read_highlights, refresh_evaluations

SIMPLE = "The Atlas Research Platform provides validated measurement services for external research projects, including microscopy of tissue samples under standardized conditions."
RICH = "The Atlas Research Platform provides validated measurement services for external research projects, with independent validation against reference measurements."


def assess(text):
    return assess_evidence([{"quote": text, "source_url": "https://example.invalid/evidence"}])


def selected(text=SIMPLE, name="Atlas Research Platform", url="https://unibe.ch/research/atlas"):
    doc = Document(url, name, text, "www", "University of Bern", "2026-10-18")
    records, rejected = validate_findings(evaluate(doc), doc)
    assert records and not rejected, rejected
    return records[0]


class EvidenceCriteriaTests(unittest.TestCase):
    def test_assertions_have_scores_reasons_and_exact_source_quotes(self):
        text = "A randomized controlled study of 240 participants reduced error by 18 percent (95% confidence interval: 12 to 24)."
        evaluation = assess(text)
        self.assertEqual(evaluation["criteria"]["methodology"]["score"], 4)
        self.assertEqual(evaluation["criteria"]["quantitative"]["score"], 4)
        for detail in evaluation["criteria"].values():
            if detail["score"]:
                self.assertIn(detail["quote"], text)
                self.assertEqual(detail["source_url"], "https://example.invalid/evidence")
                self.assertTrue(detail["reason"])
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_future_and_negated_signals_do_not_raise_scores(self):
        cases = ["We plan independent validation and a randomized controlled study of 240 patients.",
                 "The device has not been licensed to 12 commercial manufacturers.",
                 "The platform offers no access for external research projects.",
                 "The team claims independent validation and a 96 percent accuracy.",
                 "Eine randomisierte kontrollierte Studie mit 240 Patienten ist geplant.",
                 "Die Plattform wurde nicht validiert und bietet keinen Zugang für externe Forschungspartner."]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(assess(text)["score"], 0)

    def test_negative_result_can_still_have_strong_methodology(self):
        result = assess("A randomized controlled study of 120 participants found no significant difference.")
        self.assertEqual(result["criteria"]["methodology"]["score"], 4)
        self.assertEqual(result["criteria"]["quantitative"]["score"], 1)

    def test_negative_prefixes_do_not_masquerade_as_validation_or_randomization(self):
        result = assess("A non-randomized controlled study of 120 participants reduced error by 15 percent.")
        self.assertEqual(result["criteria"]["methodology"]["score"], 3)
        self.assertEqual(assess("The unvalidated platform offers a research service.")["score"], 0)

    def test_dates_budgets_and_marketing_are_not_quantitative_results(self):
        text = "The world-leading institute received CHF 40 million in 2026 and celebrated 150 years of outstanding innovation."
        self.assertEqual(assess(text)["score"], 0)

    def test_support_for_validation_does_not_claim_completed_validation(self):
        text = "These resources enable the development, validation and gradual translation of new technologies towards real-world application."
        self.assertEqual(assess(text)["criteria"]["validation"]["score"], 0)

    def test_german_design_and_quantitative_interval(self):
        result = assess("Eine randomisierte kontrollierte Studie mit 240 Patienten zeigte, dass die Plattform den Fehler um 18 Prozent reduziert (95% Konfidenzintervall: 12 bis 24).")
        self.assertEqual(result["criteria"]["methodology"]["score"], 4)
        self.assertEqual(result["criteria"]["quantitative"]["score"], 4)

    def test_each_criterion_uses_maximum_not_mention_count(self):
        item = {"quote": RICH, "source_url": "https://unibe.ch/a"}
        self.assertEqual(assess_evidence([item]), assess_evidence([item] * 20))

    def test_unrelated_assertions_cannot_complete_a_design(self):
        result = assess("The trial was randomized. Another experiment used a control group.")
        self.assertEqual(result["criteria"]["methodology"]["score"], 3)

    def test_non_numeric_confidence_statement_does_not_count_as_interval(self):
        result = assess("The study reduced error by 18 percent with high confidence in the findings.")
        self.assertEqual(result["criteria"]["quantitative"]["score"], 2)

    def test_phrases_in_authored_fields_and_keywords_earn_no_score(self):
        item = selected()
        baseline = assess_evidence(item["evidence"])
        item.update(summary="Randomized controlled study of 240 participants.",
                    keywords=["clinical trials"], identifiers=[{"kind": "doi", "value": "10.1234/invented"}])
        self.assertEqual(assess_evidence(item["evidence"]), baseline)

    def test_stronger_excerpt_keeps_independent_validation(self):
        item = selected(SIMPLE + " Independent validation against reference measurements confirmed performance.")
        self.assertEqual(item["evaluation"]["criteria"]["validation"]["score"], 3)

    def test_humanities_outputs_can_receive_reproducibility_points(self):
        result = assess("The publicly available critical edition and dataset can be downloaded from a version 2 repository.")
        self.assertEqual(result["criteria"]["reproducibility"]["score"], 4)
        self.assertEqual(result["criteria"]["accessibility"]["score"], 4)

    def test_evidence_score_precedes_legacy_tier(self):
        weak, rich = selected(), selected(RICH)
        weak["id"], rich["id"] = "zzzz", "aaaa"
        self.assertEqual(weak["scores"], rich["scores"])
        self.assertGreater(rank(rich), rank(weak))
        rich["scores"] = {"scientific": 2, "practical": 2, "capability": 2}
        self.assertGreater(rank(rich), rank(weak))


class RankingPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "focused.sqlite"
        self.store = Store(self.path, 2)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_cap_evicts_weaker_evidence_at_same_tier(self):
        for name in ("First Research Platform", "Second Research Platform"):
            self.store.upsert(selected(name=name))
        strongest = self.store.upsert(selected(RICH, "Third Research Platform"))
        self.assertEqual(len(self.store.findings()), 2)
        self.assertEqual(self.store.findings()[0]["id"], strongest)

    def test_source_update_and_withdrawal_remove_metric_evidence(self):
        first = selected(RICH)
        second = selected(url="https://unibe.ch/research/followup")
        fid = self.store.upsert(first)
        self.store.upsert(second)
        self.assertEqual(self.store.findings()[0]["evaluation"]["criteria"]["validation"]["score"], 3)
        self.store.reconcile_source(first["source_urls"][0], set())
        remaining = self.store.findings()[0]
        self.assertEqual(remaining["id"], fid)
        self.assertEqual(remaining["evaluation"]["criteria"]["validation"]["score"], 1)
        self.assertNotIn(first["source_urls"][0], remaining["source_urls"])

    def test_untrusted_stored_evaluation_is_recomputed_on_upsert(self):
        item = selected()
        item["evaluation"]["score"] = 100
        self.store.upsert(item)
        self.assertNotEqual(self.store.findings()[0]["evaluation"]["score"], 100)

    def test_consolidation_recalculates_criteria_from_retained_evidence(self):
        records = consolidate([selected(), selected(RICH)])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["evaluation"], assess_evidence(records[0]["evidence"]))

    def make_legacy(self):
        fid = self.store.upsert(selected())
        with self.store.db:
            for table in ("findings", "observations"):
                for rowid, payload in self.store.db.execute(f"SELECT rowid, record FROM {table}").fetchall():
                    item = json.loads(payload)
                    item.pop("evaluation")
                    self.store.db.execute(f"UPDATE {table} SET record=? WHERE rowid=?", (json.dumps(item), rowid))
        return fid

    def test_backfill_preserves_identity_scores_and_frontier_and_is_idempotent(self):
        fid = self.make_legacy()
        self.store.save_state("https://unibe.ch/pending", {"status": "pending"}, "2026-10-18")
        before = self.store.findings()[0]
        result = refresh_evaluations(self.path)
        self.assertEqual(result, {"findings": 1, "observations": 1})
        self.assertEqual(refresh_evaluations(self.path), {"findings": 0, "observations": 0})
        after = self.store.findings()[0]
        self.assertEqual(after["id"], fid)
        after.pop("evaluation")
        self.assertEqual(before, after)
        self.assertEqual(len(self.store.pending()), 1)

    def test_backfill_rolls_back_if_an_observation_is_corrupt(self):
        self.make_legacy()
        with self.store.db:
            self.store.db.execute("UPDATE observations SET record='not JSON'")
        with self.assertRaises(json.JSONDecodeError):
            refresh_evaluations(self.path)
        self.assertNotIn("evaluation", self.store.findings()[0])

    def test_missing_database_is_not_created_and_inspection_is_read_only(self):
        missing = self.path.with_name("missing.sqlite")
        with self.assertRaises(FileNotFoundError):
            refresh_evaluations(missing)
        self.assertFalse(missing.exists())
        self.make_legacy()
        before = self.path.read_bytes()
        read_highlights(self.path)
        self.assertEqual(before, self.path.read_bytes())


class EvaluationMetricTests(unittest.TestCase):
    def test_confusion_matrix_and_rates_on_mixed_predictions(self):
        rows = [{"expected": e, "accepted": a} for e, a in
                [(True, True), (True, True), (True, False), (False, True), (False, False), (False, False)]]
        result = metrics(rows)
        self.assertEqual(result["true_negatives"], 2)
        for key in ("precision", "recall", "f1", "specificity", "accuracy", "balanced_accuracy"):
            self.assertAlmostEqual(result[key], 2 / 3)
        self.assertAlmostEqual(result["matthews_correlation"], 1 / 3)
        self.assertFalse(result["target_met"])

    def test_abstention_single_class_and_empty_data_cannot_pass(self):
        for rows in ([], [{"expected": True, "accepted": False}], [{"expected": False, "accepted": False}],
                     [{"expected": True, "accepted": True}]):
            self.assertFalse(metrics(rows)["target_met"])
        self.assertIsNone(metrics([])["precision"])
        self.assertIsNone(ranking_metrics([])["pairwise_accuracy"])

    def test_perfect_small_sample_still_has_uncertainty(self):
        lower, upper = wilson(10, 10)
        self.assertLess(lower, .8)
        self.assertAlmostEqual(upper, 1)
        self.assertIsNone(wilson(0, 0))

    def test_ranking_ties_do_not_get_free_credit_from_ids(self):
        finding = selected()
        rows = [{"id": "z", "ranking_group": "a", "relevance": 3, "expected": True, "findings": [finding]},
                {"id": "a", "ranking_group": "a", "relevance": 1, "expected": True, "findings": [finding]}]
        result = ranking_metrics(rows)
        self.assertEqual(result["pairwise_accuracy"], 0)
        self.assertEqual(result["pairwise_tie_rate"], 1)
        expected = (4 + 4 / math.log2(3)) / (7 + 1 / math.log2(3))
        self.assertAlmostEqual(result["ndcg_at"]["3"], expected)
        rows[0]["id"], rows[1]["id"] = "a", "z"
        self.assertEqual(ranking_metrics(rows)["ndcg_at"], result["ndcg_at"])

    def test_missing_relevant_result_penalizes_ranking(self):
        rows = [{"id": "high", "ranking_group": "a", "relevance": 3, "expected": True, "findings": []},
                {"id": "low", "ranking_group": "a", "relevance": 1, "expected": True, "findings": [selected()]}]
        result = ranking_metrics(rows)
        self.assertEqual(result["positive_pairwise_accuracy"], 0)
        self.assertLess(result["ndcg_at"]["3"], .2)

    def test_zero_signal_coverage_is_not_an_unavailable_metric(self):
        result = ranking_summary([{"scores": {"scientific": 2}, "evidence": []}])
        self.assertEqual(result["mean_score"], 0)
        self.assertEqual(result["criterion_coverage"]["validation"], 0)
        self.assertIsNone(ranking_summary([])["mean_score"])


if __name__ == "__main__":
    unittest.main()
