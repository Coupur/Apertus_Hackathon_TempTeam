import unittest
from unittest.mock import patch

from navigator import enrich


PAGE = {
    "page_id": "page-1",
    "url": "https://example.test/research",
    "title": "Research group",
    "text": "Research in biomedical engineering.",
    "source_id": "example",
    "source_name": "Example Institute",
    "institution": "University of Bern",
    "emails": [],
}


class EnrichmentCompatibilityTests(unittest.TestCase):
    def test_enrich_without_llm_keeps_heuristic_record(self):
        with patch.object(enrich.config, "LLM_ENABLED", False):
            record = enrich.enrich_page(PAGE)

        self.assertEqual(record["enriched_by"], "heuristic")
        self.assertEqual(record["unit"], "Example Institute")
        self.assertEqual(record["summary"], PAGE["text"])
        self.assertEqual(record["page_id"], PAGE["page_id"])

    def test_heuristic_records_are_indexable_but_retryable(self):
        records = [
            {"page_id": "page-1", "enriched_by": "heuristic"},
            {"page_id": "page-2", "enriched_by": "failed"},
            {"page_id": "page-3", "enriched_by": "apertus"},
        ]
        with patch.object(enrich.config, "read_jsonl", return_value=records):
            self.assertEqual(set(enrich.load()), {"page-3"})
            self.assertEqual(set(enrich.load(include_heuristic=True)), {"page-1", "page-3"})


if __name__ == "__main__":
    unittest.main()
