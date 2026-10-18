"""Subject tagging, medical link priorities and safe backfill of existing data."""
import io
import json
import tempfile
import unittest
from argparse import ArgumentParser
from contextlib import redirect_stdout
from pathlib import Path

from navigator.focused.cli import add_commands, dispatch
from navigator.focused.crawl import consolidate, priority
from navigator.focused.keywords import MAX_KEYWORDS, PATTERNS, extract_keywords, matches_keyword, record_keywords
from navigator.focused.models import Document
from navigator.focused.selection import evaluate, validate_findings
from navigator.focused.store import Store, refresh_keywords


def selected(text, name="Atlas medical study", url="https://www.unibe.ch/research/atlas"):
    doc = Document(url, name, text, "www", "University of Bern", "2026-10-18T12:00:00Z")
    records, rejected = validate_findings(evaluate(doc), doc)
    assert records and not rejected, (records, rejected)
    return records[0]


DIABETES = "The research project investigates how continuous glucose monitoring and insulin pumps improve treatment decisions for adults with type 1 diabetes."
ONCOLOGY = "The research project investigates how genomic sequencing can identify new treatment targets in breast cancer and improve the interpretation of molecular changes."


class KeywordTests(unittest.TestCase):
    def test_detailed_medical_concepts_in_both_languages(self):
        examples = [
            (DIABETES, {"type 1 diabetes", "diabetes", "continuous glucose monitoring", "insulin delivery"}),
            ("Typ-1-Diabetes, kontinuierliche Glukosemessung und Insulinpumpen",
             {"type 1 diabetes", "diabetes", "continuous glucose monitoring", "insulin delivery"}),
            ("Robotische Chirurgie mit MRT-Bildgebung und klinischer Validierung",
             {"surgical robotics", "surgery", "medical imaging", "clinical validation"}),
            ("Brustkrebs, Genomik, RNA-Sequenzierung und Immuntherapie",
             {"breast cancer", "oncology", "genomics", "sequencing", "immunotherapy"}),
            ("Clinical pharmacology using LC-MS to study chronic pain",
             {"pharmacology", "mass spectrometry", "pain medicine"}),
            ("A warning system for nocturnal hypoglycaemia and hypoglycemia",
             {"hypoglycemia", "glucose"}),
        ]
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertLessEqual(expected, set(extract_keywords(text)))

    def test_ambiguous_stems_do_not_create_medical_tags(self):
        self.assertEqual(extract_keywords("General research generates data. Diese Projekte gehören zur Universität Bern. Dieter presents a chair."), [])
        self.assertNotIn("automated insulin delivery", extract_keywords("A closed-loop control system for a satellite."))
        self.assertNotIn("glucose monitoring", extract_keywords("Researchers examine glucose metabolism in cells."))

    def test_institution_and_template_text_are_not_subjects(self):
        record = {"original_name": "Technology Transfer - Diabetes Center Berne",
                  "organizations": ["Diabetes Center Berne"], "topics": ["diabetes"],
                  "summary": "Cancer research", "rationale": "Clinical validation",
                  "evidence": [{"quote": "Diabetes Center Berne coordinates a research project."}]}
        self.assertEqual(record_keywords(record), [])

    def test_selection_uses_only_candidate_evidence_not_unrelated_sections(self):
        text = ("Glucose monitoring project\n" + DIABETES + "\n\n"
                "Breast cancer project\n" + ONCOLOGY)
        doc = Document("https://unibe.ch/research/projects", "Research projects", text,
                       "www", "University of Bern", "2026-10-18T12:00:00Z")
        raw = evaluate(doc)
        for item in raw["findings"]:
            item["keywords"] = ["invented clinical efficacy"]
        records, rejected = validate_findings(raw, doc)
        self.assertFalse(rejected)
        self.assertEqual(len(records), 2)
        glucose = next(r for r in records if "Glucose" in r["original_name"])
        cancer = next(r for r in records if "Breast" in r["original_name"])
        self.assertIn("continuous glucose monitoring", glucose["keywords"])
        self.assertNotIn("oncology", glucose["keywords"])
        self.assertIn("breast cancer", cancer["keywords"])
        self.assertNotIn("diabetes", cancer["keywords"])
        self.assertNotIn("invented clinical efficacy", glucose["keywords"])

    def test_nonmedical_science_remains_supported(self):
        self.assertLessEqual({"climate research", "biodiversity", "space science"},
                             set(extract_keywords("Climate change, biodiversity and exoplanets")))

    def test_tags_are_bounded_deduplicated_and_title_is_preferred(self):
        text = ", ".join(PATTERNS)
        result = extract_keywords(text + text, title="Surgical robotics")
        self.assertEqual(len(result), MAX_KEYWORDS)
        self.assertEqual(len(result), len(set(result)))
        self.assertIn("surgical robotics", result[:3])
        self.assertEqual(result, extract_keywords(text + text, title="Surgical robotics"))

    def test_tags_describe_mentions_even_when_work_is_planned(self):
        self.assertIn("clinical trials", extract_keywords("Clinical trials are planned but have not started."))

    def test_medical_links_receive_priority_without_institution_bias(self):
        url = "https://www.unibe.ch/detail"
        self.assertGreater(priority(url, "Continuous glucose monitoring", "", "", 1),
                           priority(url, "Climate research", "", "", 1))
        self.assertGreater(priority(url, "Genomik", "", "", 1), priority(url, "More", "", "", 1))
        self.assertGreater(priority("https://unibe.ch/continuous_glucose_monitoring", "More", "", "", 1),
                           priority(url, "More", "", "", 1))
        self.assertEqual(priority(url, "More", "diabetes", "Diabetes Center Berne", 1),
                         priority(url, "More", "", "", 1))

    def test_keyword_filter_supports_aliases_and_requires_each_concept(self):
        record = selected(DIABETES)
        self.assertTrue(matches_keyword(record, "CGM"))
        self.assertTrue(matches_keyword(record, "Typ-1-Diabetes"))
        self.assertFalse(matches_keyword(record, "Typ-2-Diabetes"))
        self.assertFalse(matches_keyword(record, "diabetes and oncology"))
        self.assertTrue(matches_keyword({"keywords": ["surgical robotics"]}, "surgical robotics"))


class KeywordPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "focused.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_merge_chunk_and_source_evidence_then_withdraw_old_tags(self):
        first = selected(DIABETES)
        second = selected(ONCOLOGY, url="https://www.unibe.ch/research/atlas-followup")
        consolidated = consolidate([first, second])
        self.assertEqual(len(consolidated), 1)
        self.assertLessEqual({"diabetes", "breast cancer"}, set(consolidated[0]["keywords"]))
        fid = self.store.upsert(first)
        self.assertEqual(self.store.upsert(second), fid)
        self.assertIn("diabetes", self.store.findings()[0]["keywords"])
        self.assertIn("breast cancer", self.store.findings()[0]["keywords"])
        self.store.reconcile_source(first["source_urls"][0], set())
        remaining = self.store.findings()[0]
        self.assertIn("breast cancer", remaining["keywords"])
        self.assertNotIn("diabetes", remaining["keywords"])
        self.assertEqual(remaining["scores"], second["scores"])

    def test_update_same_source_removes_previous_tags(self):
        fid = self.store.upsert(selected(DIABETES))
        self.assertEqual(fid, self.store.upsert(selected(ONCOLOGY)))
        record = self.store.findings()[0]
        self.assertNotIn("diabetes", record["keywords"])
        self.assertIn("oncology", record["keywords"])

    def test_backfill_changes_only_keywords_is_idempotent_and_preserves_state(self):
        self.store.upsert(selected(DIABETES))
        self.store.save_state("https://unibe.ch/research/queued", {"status": "pending"}, "2026-10-18")
        originals = {}
        with self.store.db:
            for table in ("findings", "observations"):
                rowid, raw = self.store.db.execute(f"SELECT rowid, record FROM {table}").fetchone()
                record = json.loads(raw)
                record.pop("keywords")
                originals[table] = record
                self.store.db.execute(f"UPDATE {table} SET record=? WHERE rowid=?", (json.dumps(record), rowid))
        identities = self.store.db.execute("SELECT * FROM identities").fetchall()
        self.assertEqual(refresh_keywords(self.path), {"findings": 1, "observations": 1})
        for table, original in originals.items():
            record = json.loads(self.store.db.execute(f"SELECT record FROM {table}").fetchone()[0])
            self.assertIn("type 1 diabetes", record.pop("keywords"))
            self.assertEqual(record, original)
        self.assertEqual(refresh_keywords(self.path), {"findings": 0, "observations": 0})
        self.assertEqual(identities, self.store.db.execute("SELECT * FROM identities").fetchall())
        self.assertEqual(len(self.store.pending()), 1)

    def test_backfill_failure_rolls_back_both_tables(self):
        fid = self.store.upsert(selected(DIABETES))
        with self.store.db:
            record = self.store.findings()[0]
            record.pop("keywords")
            self.store.db.execute("UPDATE findings SET record=? WHERE id=?", (json.dumps(record), fid))
            self.store.db.execute("UPDATE observations SET record='invalid JSON'")
        with self.assertRaises(json.JSONDecodeError):
            refresh_keywords(self.path)
        self.assertNotIn("keywords", self.store.findings()[0])

    def test_read_and_keyword_filter_are_read_only(self):
        self.store.upsert(selected(DIABETES))
        self.store.upsert(selected(ONCOLOGY, name="Separate oncology project"))
        parser = ArgumentParser()
        add_commands(parser.add_subparsers(dest="cmd"))
        args = parser.parse_args(["highlights", "--db", str(self.path), "--keyword", "CGM",
                                  "--keyword", "Typ-1-Diabetes", "--json"])
        before = self.path.read_bytes()
        with redirect_stdout(io.StringIO()) as output:
            dispatch(args, parser)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["count"], 1)
        self.assertIn("continuous glucose monitoring", payload["findings"][0]["keywords"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_backfill_missing_database_does_not_create_it(self):
        path = self.path.with_name("missing.sqlite")
        with self.assertRaises(FileNotFoundError):
            refresh_keywords(path)
        self.assertFalse(path.exists())
