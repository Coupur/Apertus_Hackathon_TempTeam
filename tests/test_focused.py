"""Offline behavioral tests for collection, local selection and evidence provenance."""
import asyncio
import copy
import json
import tempfile
import unittest
from argparse import ArgumentParser, Namespace
from pathlib import Path
from unittest.mock import patch

import httpx

from navigator.focused.crawl import Crawler, consolidate, focused_sources, prefilter, priority, run_crawl
from navigator.focused.evaluate import metrics
from navigator.focused.models import Document, Settings
from navigator.focused.selection import evaluate, validate_findings
from navigator.focused.store import Store, read_highlights
from navigator.focused.web import Boundary, BudgetExceeded, FetchError, Fetcher, normalize_url
from navigator.sources import Source

FACT = "The Atlas Research Platform provides validated high-pressure testing unavailable in conventional laboratories and is used by twelve industrial partners."


def document(url="https://www.artorg.unibe.ch/research/atlas", title="Atlas Research Platform", text=FACT):
    return Document(url, title, text, "artorg", "ARTORG", "2026-10-18T12:00:00Z")


def candidate(doc=None, score=3):
    doc = doc or document()
    return {"title": doc.title, "original_name": doc.title, "type": "infrastructure", "unit": "",
            "summary": "A distinctive testing platform with a documented application and industrial use.",
            "rationale": "The source describes a validated testing capability and use by twelve industrial partners.",
            "scores": {"scientific": 1, "practical": score, "capability": score},
            "evidence": [{"quote": FACT, "supports": ["practical", "capability"]}],
            "topics": ["testing"], "organizations": [], "experts": [], "identifiers": [],
            "date": None, "status": "unknown", "status_quote": ""}


def record(doc=None, score=3):
    doc = doc or document()
    accepted, rejected = validate_findings({"findings": [candidate(doc, score)]}, doc)
    assert accepted, rejected
    return accepted[0]


def page(title="Atlas Research Platform", links="", text=FACT):
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>{text}</p>{links}</main></body></html>"


async def no_wait(seconds):
    pass


class RuleTests(unittest.TestCase):
    def select(self, text, title="Atlas Research Platform"):
        doc = document(text=text, title=title)
        records, rejected = validate_findings(evaluate(doc), doc)
        self.assertFalse(rejected)
        return records

    def test_component_integration_is_not_external_adoption(self):
        text = "A new optical sensor is incorporated into a wearable device. The platform measures light emission and combines several components to monitor metabolites continuously. The prototype is being developed in the laboratory."
        records = self.select(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["scores"]["practical"], 2)
        self.assertNotIn("documented_adoption", records[0]["matched_rules"])

    def test_negated_license_and_future_plans_do_not_qualify(self):
        self.assertFalse(self.select("The technology has not been licensed to a manufacturer. The team hopes to adopt it in a future commercial product."))
        self.assertFalse(self.select("The platform will be adopted by twelve industrial partners if future validation succeeds."))

    def test_german_evidence_has_english_authored_fields(self):
        records = self.select("Die Plattform bietet validierte Prüfung von Gewebeproben und Zugang für externe Forschungspartner.", "Berner Gewebeplattform")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["review_status"], "unreviewed")
        self.assertTrue(records[0]["summary"].startswith("The source reports"))
        self.assertIn("Gewebeproben", records[0]["evidence"][0]["quote"])

    def test_historical_rule_selection_records_completion(self):
        text = "The Atlas Research Platform provides validated testing unavailable in conventional laboratories and is used by twelve industrial partners. The project was completed in 1998."
        records = self.select(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "completed")
        self.assertEqual(records[0]["date"], "1998")

    def test_different_named_platforms_are_not_merged_by_generic_titles(self):
        first = self.select(FACT)[0]
        second = self.select(FACT.replace("Atlas", "Orion"), "Orion Research Platform")[0]
        self.assertEqual(first["title"], second["title"])
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "focused.sqlite")
            try:
                store.upsert(first)
                store.upsert(second)
                self.assertEqual(len(store.findings()), 2)
            finally:
                store.close()


class SelectionTests(unittest.TestCase):
    def test_high_value_with_verbatim_evidence_qualifies(self):
        accepted, rejected = validate_findings({"findings": [candidate()]}, document())
        self.assertEqual(len(accepted), 1)
        self.assertFalse(rejected)
        self.assertEqual(accepted[0]["organizations"], ["University of Bern", "ARTORG"])

    def test_low_score_rejected_even_with_evidence(self):
        accepted, rejected = validate_findings({"findings": [candidate(score=1)]}, document())
        self.assertFalse(accepted)
        self.assertEqual(rejected["below_threshold"], 1)

    def test_invented_evidence_rejected(self):
        item = candidate()
        item["evidence"][0]["quote"] = "This invented quote claims a major breakthrough but does not occur in the page."
        accepted, rejected = validate_findings({"findings": [item]}, document())
        self.assertFalse(accepted)
        self.assertEqual(rejected["nonverbatim_evidence"], 1)

    def test_each_high_score_needs_evidence(self):
        item = candidate()
        item["scores"]["scientific"] = 4
        self.assertFalse(validate_findings({"findings": [item]}, document())[0])

    def test_identity_must_be_grounded(self):
        item = candidate()
        item["original_name"] = "Invented Project"
        self.assertFalse(validate_findings({"findings": [item]}, document())[0])

    def test_invalid_candidate_does_not_drop_valid_neighbor(self):
        accepted, rejected = validate_findings({"findings": [{"title": "bad"}, candidate()]}, document())
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected["invalid_candidate"], 1)

    def test_historical_result_retains_date_and_completed_status(self):
        doc = document(text=FACT + " The project was completed in 1998.")
        item = candidate(doc)
        item.update(date="1998", status="completed", status_quote="The project was completed in 1998.")
        accepted, _ = validate_findings({"findings": [item]}, doc)
        self.assertEqual(accepted[0]["date"], "1998")
        self.assertEqual(accepted[0]["status"], "completed")

    def test_ungrounded_status_date_experts_and_identifiers_not_invented(self):
        item = candidate()
        item.update(status="active", date="2025", identifiers=[{"kind": "doi", "value": "10.1234/invented"}],
                    experts=[{"name": "Invented Person"}])
        accepted, _ = validate_findings({"findings": [item]}, document())
        self.assertEqual(accepted[0]["status"], "unknown")
        self.assertIsNone(accepted[0]["date"])
        self.assertFalse(accepted[0]["experts"])
        self.assertFalse(accepted[0]["identifiers"])

    def test_routine_title_filtered_without_model(self):
        self.assertEqual(prefilter(document(title="Research assistant vacancy")), "routine_content")

    def test_clinical_studies_are_not_confused_with_teaching(self):
        doc = document(url="https://www.dcberne.com/research/clinical_studies/", title="Clinical studies",
                       text=FACT + " The platform also supports clinical research.")
        self.assertIsNone(prefilter(doc))

    def test_context_changes_frontier_priority(self):
        url = "https://www.artorg.unibe.ch/a"
        self.assertGreater(priority(url, "Flagship research", "validated project", "Research", 1),
                           priority(url, "More", "", "", 1))

    def test_old_archive_links_remain_eligible(self):
        for year in ("1885", "1998", "2026"):
            self.assertGreater(priority(f"https://unibe.ch/news/{year}/", year, "", "News archive", 5), 0)

    def test_recent_routine_item_has_no_recency_override(self):
        doc = document(text=FACT + " Publication date: 2026-10-18.")
        item = candidate(doc, score=1)
        item["date"] = "2026-10-18"
        self.assertFalse(validate_findings({"findings": [item]}, doc)[0])

    def test_malformed_response_is_not_an_empty_success(self):
        self.assertEqual(validate_findings({"other": []}, document())[1]["invalid_response"], 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "focused.sqlite"
        self.store = Store(self.path, 500)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_repeat_upsert_has_stable_id(self):
        first = self.store.upsert(record())
        second = self.store.upsert(record())
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.findings()), 1)

    def test_language_versions_merge_without_score_inflation(self):
        self.store.upsert(record())
        german = record()
        german.update(original_name="Atlas Forschungsplattform", source_urls=["https://www.artorg.unibe.ch/de/atlas"])
        german["evidence"][0]["source_url"] = german["source_urls"][0]
        self.store.upsert(german)
        findings = self.store.findings()
        self.assertEqual(len(findings), 1)
        self.assertEqual(max(findings[0]["scores"].values()), 3)
        self.assertEqual(len(findings[0]["source_urls"]), 2)

    def test_shared_identifier_merges_cross_institution_coverage(self):
        a = record()
        a["identifiers"] = [{"kind": "project", "value": "ATLAS-2024"}]
        b = copy.deepcopy(a)
        b.update(title="Shared Atlas facility", original_name="Shared Atlas facility",
                 organizations=["Diabetes Center Berne"], source_ids=["dcberne"],
                 source_urls=["https://www.dcberne.com/atlas"])
        b["evidence"][0]["source_url"] = b["source_urls"][0]
        self.store.upsert(a)
        self.store.upsert(b)
        findings = self.store.findings()
        self.assertEqual(len(findings), 1)
        self.assertIn("Diabetes Center Berne", findings[0]["organizations"])

    def test_multiple_findings_on_one_page_remain_separate(self):
        self.store.upsert(record())
        other = record()
        other.update(title="Independent Hearing Facility", original_name="Independent Hearing Facility")
        self.store.upsert(other)
        self.assertEqual(len(self.store.findings()), 2)

    def test_updated_observation_replaces_old_score(self):
        self.store.upsert(record(score=4))
        self.store.upsert(record(score=3))
        self.assertEqual(max(self.store.findings()[0]["scores"].values()), 3)

    def test_multisource_update_does_not_keep_superseded_score(self):
        original = record(score=4)
        self.store.upsert(original)
        second = record(score=3)
        second["source_urls"] = ["https://www.artorg.unibe.ch/other"]
        second["evidence"][0]["source_url"] = second["source_urls"][0]
        self.store.upsert(second)
        self.store.upsert(record(score=3))
        self.assertEqual(max(self.store.findings()[0]["scores"].values()), 3)

    def test_same_generic_title_in_different_units_does_not_merge(self):
        first, second = record(), record()
        first["unit"], second["unit"] = "Engineering laboratory", "Chemistry laboratory"
        self.store.upsert(first)
        self.store.upsert(second)
        self.assertEqual(len(self.store.findings()), 2)

    def test_chunk_consolidation_keeps_strongest_observation(self):
        results = consolidate([record(score=4), record(score=3)])
        self.assertEqual(len(results), 1)
        self.assertEqual(max(results[0]["scores"].values()), 4)

    def test_distinct_doi_punctuation_is_preserved(self):
        first, second = record(), record()
        first["identifiers"] = [{"kind": "doi", "value": "10.1234/a-b"}]
        second["identifiers"] = [{"kind": "doi", "value": "10.1234/a.b"}]
        second.update(title="Other Independent Facility", original_name="Other Independent Facility")
        self.store.upsert(first)
        self.store.upsert(second)
        self.assertEqual(len(self.store.findings()), 2)

    def test_source_check_does_not_trim_existing_findings(self):
        self.store.upsert(record())
        other = record()
        other.update(title="Other Independent Facility", original_name="Other Independent Facility")
        self.store.upsert(other)
        self.store.limit = 1
        self.store.finish({"mode": "source_check"}, 100)
        self.assertEqual(len(self.store.findings()), 2)

    def test_withdraw_one_source_preserves_other_evidence(self):
        first, second = record(score=4), record(score=3)
        second["source_urls"] = ["https://www.artorg.unibe.ch/other"]
        second["evidence"][0]["source_url"] = second["source_urls"][0]
        self.store.upsert(first)
        self.store.upsert(second)
        self.store.reconcile_source(first["source_urls"][0], set())
        remaining = self.store.findings()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(max(remaining[0]["scores"].values()), 3)
        self.assertNotIn(first["source_urls"][0], remaining[0]["source_urls"])

    def test_cap_retains_strongest_not_first(self):
        self.store.limit = 2
        for index, score in enumerate((3, 3, 4)):
            item = record(score=score)
            item.update(title=f"Distinctive Platform {index}", original_name=f"Distinctive Platform {index}")
            self.store.upsert(item)
        self.assertEqual(len(self.store.findings()), 2)
        self.assertEqual(max(self.store.findings()[0]["scores"].values()), 4)

    def test_hard_500_cap_and_repetition_does_not_add_value(self):
        with self.assertRaises(ValueError):
            Settings(max_findings=501)
        for index in range(505):
            item = record()
            item.update(title=f"Independent Facility {index}", original_name=f"Independent Facility {index}")
            self.store.upsert(item)
        self.assertEqual(len(self.store.findings()), 500)

    def test_empty_database_is_not_filled(self):
        self.store.finish({"retained_findings": 0}, 100)
        self.assertEqual(read_highlights(self.path)[0], [])

    def test_read_missing_database_does_not_create_it(self):
        missing = self.path.parent / "missing.sqlite"
        with self.assertRaises(FileNotFoundError):
            read_highlights(missing)
        self.assertFalse(missing.exists())


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sleep = patch("navigator.focused.web.asyncio.sleep", new=no_wait)
        self.sleep.start()

    async def asyncTearDown(self):
        self.sleep.stop()

    async def fetch(self, handler, url="https://www.unibe.ch/", settings=None, hosts=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = Fetcher(client, Boundary(hosts or [url]), settings or Settings())
            return await fetcher.get(url), fetcher

    def test_exact_hosts_only_and_unsafe_urls_rejected(self):
        boundary = Boundary(["https://www.unibe.ch/"])
        self.assertTrue(boundary.allows("https://unibe.ch/research"))
        for url in ("https://unibe.ch.evil.example/", "https://extra.unibe.ch/", "https://unibe.ch:8888/", "https://u:p@unibe.ch/", "file:///tmp/data"):
            self.assertFalse(boundary.allows(url))
        self.assertEqual(normalize_url("https://unibe.ch/a?utm_source=x&year=1998#x"), "https://unibe.ch/a?year=1998")

    async def test_external_redirect_is_never_requested(self):
        requests = []

        def handler(request):
            requests.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
            return httpx.Response(302, headers={"location": "https://external.example/data"})

        with self.assertRaisesRegex(FetchError, "outside_source_boundary"):
            await self.fetch(handler)
        self.assertFalse(any("external.example" in r for r in requests))

    async def test_redirect_destination_robots_checked(self):
        requests = []

        def handler(request):
            requests.append(str(request.url))
            if request.url.path == "/robots.txt":
                rule = "Disallow: /" if request.url.host == "artorg.unibe.ch" else "Allow: /"
                return httpx.Response(200, text="User-agent: *\n" + rule)
            return httpx.Response(302, headers={"location": "https://artorg.unibe.ch/private"})

        with self.assertRaisesRegex(FetchError, "robots"):
            await self.fetch(handler, hosts=["https://www.unibe.ch/", "https://artorg.unibe.ch/"])
        self.assertNotIn("https://artorg.unibe.ch/private", requests)

    async def test_robots_failure_fails_closed(self):
        requests = []

        def handler(request):
            requests.append(str(request.url))
            return httpx.Response(503)

        with self.assertRaisesRegex(FetchError, "robots"):
            await self.fetch(handler)
        self.assertEqual(len(requests), 1)

    async def test_redirect_hops_count_toward_budget(self):
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"location": "/next"})
        with self.assertRaises(BudgetExceeded):
            await self.fetch(handler, settings=Settings(max_fetches=1))

    async def test_bounded_response(self):
        def handler(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text="x" * 200)
        with self.assertRaisesRegex(FetchError, "response_too_large"):
            await self.fetch(handler, settings=Settings(max_bytes=100))

    async def test_pacing_applies_to_robots_and_content(self):
        sleeps = []

        async def track_sleep(seconds):
            sleeps.append(seconds)

        def handler(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text="ok")

        with patch("navigator.focused.web.asyncio.sleep", new=track_sleep):
            await self.fetch(handler)
        self.assertGreater(sleeps[-1], 0.9)

    async def test_crawl_delay_is_respected(self):
        sleeps = []

        async def track_sleep(seconds):
            sleeps.append(seconds)

        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /\nCrawl-delay: 5")
            return httpx.Response(200, text="ok")

        with patch("navigator.focused.web.asyncio.sleep", new=track_sleep):
            await self.fetch(handler)
        self.assertGreater(sleeps[-1], 4.9)

    async def test_network_concurrency_never_exceeds_limit(self):
        running, maximum = 0, 0
        loop = asyncio.get_running_loop()

        async def handler(request):
            nonlocal running, maximum
            running += 1
            maximum = max(maximum, running)
            future = loop.create_future()
            loop.call_soon(future.set_result, None)
            await future
            running -= 1
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(200, text="ok")

        urls = [f"https://site{i}.unibe.ch/" for i in range(6)]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fetcher = Fetcher(client, Boundary(urls), Settings(concurrency=2))
            await asyncio.gather(*(fetcher.get(u) for u in urls))
        self.assertEqual(maximum, 2)


class CrawlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "focused.sqlite"
        self.store = Store(self.path)
        self.source = Source("artorg", "ARTORG", "https://www.artorg.unibe.ch/", "ARTORG")
        self.sleep = patch("navigator.focused.web.asyncio.sleep", new=no_wait)
        self.sleep.start()

    async def asyncTearDown(self):
        self.sleep.stop()
        self.store.close()
        self.temp.cleanup()

    async def run_crawler(self, handler, evaluator=None, settings=None, sources=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            crawler = Crawler(sources or [self.source], self.store, settings or Settings(),
                              evaluator=evaluator or (lambda doc: {"findings": [candidate(doc)]}))
            return await crawler.run(client)

    @staticmethod
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=page(), headers={"content-type": "text/html"})

    async def test_end_to_end_and_repeat_run(self):
        first = await self.run_crawler(self.handler)
        second = await self.run_crawler(self.handler)
        self.assertEqual(first["retained_findings"], 1)
        self.assertEqual(second["retained_findings"], 1)
        self.assertEqual(second["selection_evaluations"], 0)
        self.assertEqual(second["unchanged_documents"], 1)
        self.assertEqual({p.name for p in self.path.parent.iterdir()}, {"focused.sqlite"})

    async def test_network_failure_preserves_findings(self):
        await self.run_crawler(self.handler)

        def failed(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(500)

        report = await self.run_crawler(failed)
        self.assertEqual(report["retained_findings"], 1)
        self.assertEqual(report["errors"]["http_500"], 1)

    async def test_rejected_document_is_not_persisted(self):
        secret_marker = "Rejected body sentinel must never enter persistent storage. " * 8

        def handler(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(
                200, text=page(text=secret_marker), headers={"content-type": "text/html"})

        report = await self.run_crawler(handler, evaluator=lambda doc: {"findings": []})
        self.assertEqual(report["retained_findings"], 0)
        self.assertNotIn(b"Rejected body sentinel", self.path.read_bytes())

    async def test_source_check_never_calls_selector(self):
        def forbidden(doc):
            raise AssertionError("Selector must not be called")
        report = await self.run_crawler(self.handler, forbidden, Settings(source_check=True))
        self.assertEqual(report["selection_evaluations"], 0)
        self.assertEqual(report["retained_findings"], 0)

    async def test_fetch_budget_and_pending_resume(self):
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            links = '<a href="/research/second">Flagship research project</a>' if request.url.path == "/" else ""
            return httpx.Response(200, text=page(links=links, title="Platform " + request.url.path), headers={"content-type": "text/html"})

        report = await self.run_crawler(handler, settings=Settings(max_fetches=1))
        self.assertEqual(report["selection_evaluations"], 1)
        self.assertEqual(report["stopping_reason"], "fetch_budget")
        self.assertTrue(self.store.pending())

    async def test_fetch_budget_under_concurrency(self):
        sources = [self.source, Source("dcberne", "DCB", "https://www.dcberne.com/", "Diabetes Center Berne")]
        report = await self.run_crawler(self.handler, sources=sources, settings=Settings(max_fetches=1, source_check=True))
        self.assertEqual(report["content_fetches"], 1)
        self.assertEqual(report["stopping_reason"], "fetch_budget")

    async def test_no_automatic_external_expansion(self):
        visited = []

        def handler(request):
            visited.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, text=page(links='<a href="https://extra.unibe.ch/project">Flagship project</a>'), headers={"content-type": "text/html"})

        report = await self.run_crawler(handler)
        self.assertEqual(report["outside_links_not_followed"], 1)
        self.assertFalse(any("extra.unibe.ch" in u for u in visited))

    async def test_dcb_api_paginates_and_keeps_public_and_retrieval_urls(self):
        source = Source("dcberne", "DCB", "https://www.dcberne.com/", "Diabetes Center Berne")
        requested = []

        def handler(request):
            requested.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            if request.url.path == "/":
                return httpx.Response(200, text=page(text="Home"), headers={"content-type": "text/html"})
            if request.url.path.endswith("/project"):
                n = request.url.params.get("page", "1")
                return httpx.Response(200, json=[{"title": {"rendered": "Atlas Research Platform " + n},
                                                 "link": f"https://www.dcberne.com/project/atlas-{n}",
                                                 "content": {"rendered": FACT}, "date": "2026-01-01"}],
                                      headers={"x-wp-totalpages": "2"})
            return httpx.Response(200, json=[])

        report = await self.run_crawler(handler, sources=[source])
        self.assertEqual(report["retained_findings"], 2)
        self.assertTrue(any("page=2" in u for u in requested))
        for item in self.store.findings():
            self.assertIn("/project/atlas-", item["evidence"][0]["source_url"])
            self.assertIn("/wp-json/", item["evidence"][0]["retrieval_url"])

    async def test_selector_failure_is_retryable(self):
        def failing(doc):
            raise ValueError("Invalid selection result")
        report = await self.run_crawler(self.handler, failing)
        self.assertEqual(report["retained_findings"], 0)
        self.assertEqual(report["errors"]["selection_ValueError"], 1)
        report = await self.run_crawler(self.handler)
        self.assertEqual(report["retained_findings"], 1)

    async def test_successful_changed_page_can_withdraw_old_finding(self):
        await self.run_crawler(self.handler)

        def changed(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(
                200, text=page(text=FACT + " The earlier claims have been withdrawn after correction."),
                headers={"content-type": "text/html"})

        result = await self.run_crawler(changed, evaluator=lambda doc: {"findings": []})
        self.assertEqual(result["retained_findings"], 0)

    async def test_invalid_evidence_cannot_withdraw_previous_finding(self):
        await self.run_crawler(self.handler)

        def invalid(doc):
            result = candidate(doc)
            result["evidence"][0]["quote"] = "An invented claim that does not occur anywhere in the actual source document."
            return {"findings": [result]}

        result = await self.run_crawler(self.handler, invalid, Settings(reevaluate=True))
        self.assertEqual(result["retained_findings"], 1)
        self.assertEqual(result["rejection_reasons"]["nonverbatim_evidence"], 1)

    async def test_truncated_document_cannot_withdraw_unread_evidence(self):
        await self.run_crawler(self.handler)

        def long_page(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(
                200, text=page(text="Long source context. " * 2000 + FACT), headers={"content-type": "text/html"})

        result = await self.run_crawler(long_page, lambda doc: {"findings": []})
        self.assertEqual(result["retained_findings"], 1)
        self.assertEqual(result["truncated_documents"], 1)

    async def test_collection_uses_real_rules_without_model_calls(self):
        with patch("httpx.post", side_effect=AssertionError("No model requests allowed")):
            report = await self.run_crawler(self.handler, evaluate)
        self.assertEqual(report["retained_findings"], 1)
        self.assertEqual(report["selection_method"], "rules")
        item = self.store.findings()[0]
        self.assertEqual(item["review_status"], "unreviewed")
        self.assertIn("distinctive_capability", item["matched_rules"])

    async def test_public_runner_collects_when_model_endpoint_is_missing(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        with patch("navigator.config.LLM_ENABLED", False), patch("navigator.focused.crawl.focused_sources", return_value=[self.source]), patch("navigator.focused.crawl.httpx.AsyncClient", return_value=client), patch("httpx.post", side_effect=AssertionError("No model requests allowed")):
            report = await run_crawl(self.path, Settings(max_fetches=1))
        self.assertEqual(report["mode"], "collection")
        self.assertEqual(report["retained_findings"], 1)

    async def test_api_external_doi_is_stored_without_being_fetched(self):
        from navigator.focused.web import Response
        source = Source("dcberne", "DCB", "https://www.dcberne.com/", "Diabetes Center Berne")
        crawler = Crawler([source], self.store, Settings())
        response = Response("https://www.dcberne.com/wp-json/wp/v2/publication?page=1", 200, "application/json",
                            json.dumps([{"link": "https://www.dcberne.com/publication/atlas", "title": {"rendered": "Atlas research"},
                                         "acf": {"abstract": FACT, "reference": {"url": "https://doi.org/10.1234/atlas"}}}]), {})
        docs = crawler.api_documents(response, 0)
        self.assertIn("https://doi.org/10.1234/atlas", docs[0].references)
        self.assertIn("10.1234/atlas", docs[0].text)
        self.assertFalse(any("doi.org" in entry[2] for entry in crawler.queue))

    async def test_frontier_drops_weaker_links_first(self):
        crawler = Crawler([self.source], self.store, Settings(max_frontier=2))
        crawler.enqueue("https://www.artorg.unibe.ch/weak", 1)
        crawler.enqueue("https://www.artorg.unibe.ch/medium", 5)
        crawler.enqueue("https://www.artorg.unibe.ch/strong", 10)
        self.assertNotIn("https://www.artorg.unibe.ch/weak", crawler.queued)
        self.assertIn("https://www.artorg.unibe.ch/strong", crawler.queued)

    async def test_complete_mode_exhausts_low_priority_links_beyond_all_budgets(self):
        visited = []

        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            visited.append(request.url.path)
            links = '<a href="/plain/1">Next</a><a href="/plain/2">Next</a>' if request.url.path == "/" else '<a href="/plain/3">Next</a>' if request.url.path == "/plain/2" else ""
            return httpx.Response(200, text=page(title="Platform " + request.url.path, links=links), headers={"content-type": "text/html"})

        settings = Settings(complete=True, max_fetches=1, max_depth=1, max_frontier=1, max_findings=1)
        self.store.limit = settings.max_findings
        first = await self.run_crawler(handler, settings=settings)
        self.assertEqual(set(visited), {"/", "/plain/1", "/plain/2", "/plain/3"})
        self.assertEqual(first["stopping_reason"], "frontier_exhausted")
        self.assertEqual(first["frontier_dropped"], 0)
        self.assertEqual(first["retained_findings"], 1)
        self.assertIsNone(first["limits"]["content_fetches"])
        self.assertIsNone(first["limits"]["depth"])
        self.assertIsNone(first["limits"]["frontier"])
        visited.clear()
        second = await self.run_crawler(handler, settings=settings)
        self.assertFalse(visited)
        self.assertEqual(second["resumed_checked_urls"], 4)
        self.assertEqual(second["content_fetches"], 0)

    async def test_complete_mode_checkpoints_and_resumes_interruption(self):
        checkpoints, requests = [], []

        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            requests.append(request.url.path)
            links = '<a href="/plain/next">Next</a>' if request.url.path == "/" else ""
            return httpx.Response(200, text=page(links=links), headers={"content-type": "text/html"})

        def interrupt(_):
            asyncio.current_task().cancel()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            crawler = Crawler([self.source], self.store, Settings(complete=True), progress=interrupt, checkpoint=checkpoints.append)
            report = await asyncio.create_task(crawler.run(client))
        self.assertEqual(report["stopping_reason"], "interrupted")
        self.assertTrue(self.store.pending())
        self.assertEqual(checkpoints[0]["stopping_reason"], "running")
        self.assertIsNone(checkpoints[0]["finished_at"])
        resumed = await self.run_crawler(handler, settings=Settings(complete=True))
        self.assertEqual(requests, ["/", "/plain/next"])
        self.assertEqual(resumed["stopping_reason"], "frontier_exhausted")
        self.assertFalse(self.store.pending())

    async def test_complete_resume_retries_failed_selection(self):
        def failed(_):
            raise ValueError("Transient selection failure")

        first = await self.run_crawler(self.handler, evaluator=failed, settings=Settings(complete=True))
        self.assertEqual(first["retained_findings"], 0)
        second = await self.run_crawler(self.handler, settings=Settings(complete=True))
        self.assertEqual(second["content_fetches"], 1)
        self.assertEqual(second["retained_findings"], 1)

    async def test_complete_resume_retries_failed_network_request(self):
        def failed(request):
            return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(503)

        first = await self.run_crawler(failed, settings=Settings(complete=True))
        self.assertEqual(first["errors"]["http_503"], 1)
        second = await self.run_crawler(self.handler, settings=Settings(complete=True))
        self.assertEqual(second["content_fetches"], 1)
        self.assertEqual(second["retained_findings"], 1)


class InventoryAndBenchmarkTests(unittest.TestCase):
    def test_invalid_delays_cannot_disable_pacing(self):
        for delay in (0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                Settings(delay=delay)

    def test_export_cannot_overwrite_database(self):
        from navigator.focused.cli import dispatch
        parser = ArgumentParser()
        path = Path("same.sqlite")
        with patch.object(parser, "error", side_effect=ValueError) as error:
            with self.assertRaises(ValueError):
                dispatch(Namespace(cmd="highlights", db=path, out=path), parser)
        self.assertIn("must not overwrite", error.call_args[0][0])

    def test_discovered_sources_are_excluded(self):
        sources = focused_sources()
        self.assertEqual(sum(s.host == "artorg.unibe.ch" for s in sources), 1)
        self.assertEqual(sum(s.host == "dcberne.com" for s in sources), 1)
        self.assertNotIn("medizinischelehre.unibe.ch", {s.host for s in sources})

    def test_thirty_labeled_examples_cover_three_groups(self):
        path = Path(__file__).resolve().parents[1] / "bench/focused_examples.json"
        dataset = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("synthetic", dataset["description"])
        examples = dataset["examples"]
        self.assertEqual(len(examples), 30)
        for organization in ("University of Bern", "ARTORG", "Diabetes Center Berne"):
            cases = [e for e in examples if e["organization"] == organization]
            self.assertEqual(len(cases), 10)
            self.assertEqual({e["accept"] for e in cases}, {True, False})
            self.assertTrue(all(e["label_reason"] for e in cases))

    def test_zero_predictions_cannot_claim_precision_target(self):
        result = metrics([{"expected": True, "accepted": False}])
        self.assertIsNone(result["precision"])
        self.assertFalse(result["target_met"])


if __name__ == "__main__":
    unittest.main()
