import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from navigator.clusters import cluster_findings, latest_clusters


def seed_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE findings (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        for finding_id, title, keywords in (
            ("f1", "Wearable sensor validation", ["wearable devices", "clinical trials"]),
            ("f2", "Clinical imaging study", ["medical imaging", "clinical trials"]),
            ("f3", "Cell therapy platform", ["cell therapy", "biotechnology"]),
        ):
            db.execute(
                "INSERT INTO findings VALUES (?, ?)",
                (finding_id, json.dumps({
                    "title": title,
                    "summary": f"Research about {title.lower()} with a documented methodology.",
                    "type": "research_result",
                    "organizations": ["University of Bern"],
                    "source_urls": [f"https://example.org/{finding_id}"],
                    "keywords": keywords,
                })),
            )


class ClusteringTests(unittest.TestCase):
    def test_clusters_all_findings_and_marks_results_stale_after_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "focused.sqlite"
            seed_database(db_path)
            calls = []

            def model(system, user, **kwargs):
                calls.append((system, kwargs))
                payload = json.loads(user)
                if "proposed_themes" in payload:
                    return {
                        "themes": [{
                            "name": "Health research and technologies",
                            "description": "Clinical research and tools for advancing health.",
                            "batch_theme_ids": [theme["id"] for theme in payload["proposed_themes"]],
                        }]
                    }
                findings = payload["findings"]
                return {
                    "themes": [{
                        "name": "Biomedical research",
                        "description": "Research studies and technologies related to human health.",
                        "finding_ids": [finding["id"] for finding in findings],
                    }]
                }

            with patch("navigator.clusters.llm.chat_json", side_effect=model):
                result = cluster_findings(db_path, batch_size=2)

            self.assertEqual(len(calls), 3)
            self.assertEqual(result["finding_count"], 3)
            self.assertEqual(result["theme_count"], 1)
            self.assertEqual(result["clusters"][0]["finding_count"], 3)
            self.assertEqual(
                {item["id"] for item in result["clusters"][0]["findings"]},
                {"f1", "f2", "f3"},
            )
            self.assertEqual(latest_clusters(db_path)["stale"], False)

            with sqlite3.connect(db_path) as db:
                record = json.loads(db.execute("SELECT record FROM findings WHERE id='f1'").fetchone()[0])
                record["summary"] = "Updated evidence describing this research in more detail."
                db.execute("UPDATE findings SET record=? WHERE id='f1'", (json.dumps(record),))
            self.assertTrue(latest_clusters(db_path)["stale"])

    def test_invalid_assignment_is_rejected_without_saving_partial_result(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "focused.sqlite"
            seed_database(db_path)

            def incomplete_model(system, user, **kwargs):
                finding = json.loads(user)["findings"][0]
                return {
                    "themes": [{
                        "name": "Biomedical research",
                        "description": "Research studies and technologies related to human health.",
                        "finding_ids": [finding["id"]],
                    }]
                }

            with patch("navigator.clusters.llm.chat_json", side_effect=incomplete_model):
                with self.assertRaisesRegex(ValueError, "exactly once"):
                    cluster_findings(db_path, batch_size=2)
            self.assertIsNone(latest_clusters(db_path))

    def test_batch_size_and_empty_database_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "focused.sqlite"
            seed_database(db_path)
            with self.assertRaisesRegex(ValueError, "batch_size"):
                cluster_findings(db_path, batch_size=81)

            with sqlite3.connect(db_path) as db:
                for index in range(40):
                    db.execute(
                        "INSERT INTO findings VALUES (?, ?)",
                        (f"extra-{index}", json.dumps({
                            "title": f"Research finding {index}",
                            "summary": "A bounded test record for batch request accounting.",
                            "keywords": ["research"],
                        })),
                    )
            with patch("navigator.clusters.llm.chat_json") as model:
                with self.assertRaisesRegex(ValueError, "at most 20"):
                    cluster_findings(db_path, batch_size=1)
            model.assert_not_called()

            empty_path = Path(directory) / "empty.sqlite"
            with sqlite3.connect(empty_path) as db:
                db.execute("CREATE TABLE findings (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
            with self.assertRaisesRegex(ValueError, "no findings"):
                cluster_findings(empty_path)

    def test_http_api_reads_saved_results_and_runs_requested_batch_size(self):
        from navigator.api import app

        result = {
            "generated_at": "2026-10-19T00:00:00+00:00",
            "model": "Apertus",
            "finding_count": 3,
            "theme_count": 1,
            "clusters": [],
        }
        with TestClient(app) as client:
            with patch("navigator.api.latest_clusters", return_value=result):
                response = client.get("/clusters")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["finding_count"], 3)

            with patch("navigator.api.cluster_findings", return_value=result) as run:
                response = client.post("/clusters/run", json={"batch_size": 25})
            self.assertEqual(response.status_code, 200)
            run.assert_called_once_with(batch_size=25)

            response = client.post("/clusters/run", json={"batch_size": 81})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
