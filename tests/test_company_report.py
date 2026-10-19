"""Company matching, bounded source reads and report citation integrity (offline)."""
import asyncio
import copy
import io
import json
import tempfile
import unittest
from argparse import ArgumentParser
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from navigator.focused.company_report import (CompanyBrief, add_command, dispatch, generate_report,
                                              prepare_context, render_markdown, shortlist, source_text, evidence_urls)
from navigator.focused.models import Settings
from navigator.focused.web import Boundary, Fetcher


URL = "https://www.artorg.unibe.ch/research/sensor"
QUOTE = "The laboratory evaluates continuous glucose monitoring devices against reference measurements in clinical studies."
COMPANY = {"company_name": "Example", "need": "Validate a wearable glucose sensor",
           "keywords": ["CGM", "wearable devices"],
           "requirements": ["Evaluation against reference measurements"], "budget": "To be discussed"}


def finding(fid="f1", keywords=None, url=URL, quality=2):
    return {"id": fid, "original_name": "Glucose sensor laboratory", "type": "capability",
            "organizations": ["ARTORG"], "keywords": keywords or ["continuous glucose monitoring", "wearable devices"],
            "scores": {"scientific": quality, "practical": quality, "capability": quality},
            "source_urls": [url], "evidence": [{"quote": QUOTE, "source_url": url,
                                                "fetched_at": "2026-10-01T10:00:00Z"}]}


async def no_wait(seconds):
    pass


async def prepare(company=None, findings=None, handler=None):
    company = company or CompanyBrief(**COMPANY)
    findings = [finding()] if findings is None else findings
    if handler is None:
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"})
            return httpx.Response(200, text=f"<html><nav>NOISE</nav><main><h1>Sensor lab</h1><p>{QUOTE}</p></main></html>",
                                  headers={"content-type": "text/html"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = Fetcher(client, Boundary([URL]), Settings())
        with patch("navigator.focused.web.asyncio.sleep", no_wait):
            return await prepare_context(company, shortlist(company, findings), fetcher)


def model_report():
    return {"fit": {"text": "The source describes relevant sensor evaluation.",
                    "excerpt_ids": ["S1P1"]}, "claims": []}


def verified_report(system, user, **kwargs):
    if 'Audit the hypothesis' in system:
        return {'issue_found':False,'reason':'Every asserted fact is supported.'}
    if 'textual entailment judge' in system:
        return {"analysis":"Each assertion matches the evidence.","verdict": "entailed", "reason": "Explicitly supported by the quote."}
    return model_report()


class MatchingTests(unittest.TestCase):
    def test_overlap_precedes_evidence_score_and_zero_matches_are_excluded(self):
        company = CompanyBrief(**COMPANY)
        result = shortlist(company, [finding("broad", ["wearable devices"], quality=3),
                                     finding("unrelated", ["oncology"], quality=4), finding()])
        self.assertEqual([m["finding"]["id"] for m in result], ["f1", "broad"])
        self.assertEqual(result[0]["matched_keywords"], ["continuous glucose monitoring", "wearable devices"])

    def test_aliases_do_not_inflate_counts_or_match_only_broad_glucose(self):
        company = CompanyBrief(need="Test", keywords=["CGM", "continuous glucose monitoring", "cgm"])
        result = shortlist(company, [finding(), finding("broad", ["glucose"])])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keyword_match_count"], 1)

    def test_german_aliases_and_unknown_keywords(self):
        company = CompanyBrief(requirements=["A partner"], keywords=["Typ-1-Diabetes", "unknown subject"])
        result = shortlist(company, [finding(keywords=["type 1 diabetes"])])
        self.assertEqual(result[0]["matched_keywords"], ["type 1 diabetes"])
        self.assertEqual(result[0]["unmatched_keywords"], ["unknown subject"])

    def test_invalid_briefs_and_additional_context(self):
        for payload in ({"need": "Test", "keywords": []}, {"keywords": ["CGM"]},
                        {"need": "Test", "keywords": [" "]}, {"need": "Test", "keywords": "CGM"}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                CompanyBrief(**payload)
        self.assertEqual(CompanyBrief(**COMPANY).model_dump()["budget"], "To be discussed")

    def test_text_budget_preserves_late_keyword_passages(self):
        text = "Unrelated material. " * 500 + QUOTE
        selected = source_text(text, ["continuous glucose monitoring"], 2000)
        self.assertLessEqual(len(selected), 2000)
        self.assertIn("reference measurements", selected)

    def test_detail_pages_precede_catalogues_and_other_work_pages(self):
        r=finding()
        r['original_name']='Menstrual Cycle Study: Results published in Diabetes Care'
        r['source_urls']=['https://www.dcberne.com/en/project_category/research/',
                          'https://www.dcberne.com/en/project/the-fibregum-study/',
                          'https://www.dcberne.com/en/project/menstrual-cycle-study/']
        self.assertEqual(evidence_urls(r),[r['source_urls'][-1]])

    def test_selected_windows_are_exact_spans_without_cut_words(self):
        text=('Unrelated research paragraph with several complete words.\n\n'*40 +
              QUOTE+'\n\n'+'Different research paragraph with complete words.\n\n'*40)
        selected=source_text(text,['continuous glucose monitoring'],2000)
        self.assertLessEqual(len(selected),2000)
        for span in selected.split('\n...\n'):
            self.assertIn(span,text)
            start=text.index(span)
            end=start+len(span)
            self.assertFalse(start and text[start-1].isalnum() and text[start].isalnum())
            self.assertFalse(end<len(text) and text[end-1].isalnum() and text[end].isalnum())


class SourceTests(unittest.TestCase):
    def test_selected_pages_only_and_shared_source_fetched_once(self):
        requested = []

        def handler(request):
            requested.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, text=f"<nav>NOISE</nav><main><p>{QUOTE}</p></main>",
                                  headers={"content-type": "text/html"})

        context = asyncio.run(prepare(findings=[finding(), finding("f2"), finding("x", ["oncology"], URL + "-other")], handler=handler))
        self.assertEqual(requested.count(URL), 1)
        self.assertNotIn(URL + "-other", requested)
        self.assertEqual(len(context["sources"]), 1)
        self.assertEqual(len(context["candidates"]), 2)
        self.assertNotIn("NOISE", context["sources"][0]["text"])
        self.assertEqual(context["sources"][0]["status"], "fetched")

    def test_failed_page_uses_its_own_dated_excerpts(self):
        def handler(request):
            return httpx.Response(404 if request.url.path == "/robots.txt" else 503)

        context = asyncio.run(prepare(handler=handler))
        source = context["sources"][0]
        self.assertEqual(source["status"], "stored_excerpt")
        self.assertEqual(source["text"], QUOTE)
        self.assertIn("2026-10-01", " ".join(context["limitations"]))

    def test_external_redirect_is_not_fetched(self):
        requested = []

        def handler(request):
            requested.append(str(request.url))
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(302, headers={"location": "https://outside.example/private"})

        context = asyncio.run(prepare(handler=handler))
        self.assertFalse(any("outside.example" in u for u in requested))
        self.assertEqual(context["sources"][0]["status"], "stored_excerpt")

    def test_no_matches_do_not_fetch_or_call_model(self):
        with patch("navigator.focused.company_report.llm.chat_json") as model:
            context = asyncio.run(prepare(findings=[]))
            result = generate_report(context)
        model.assert_not_called()
        self.assertEqual(result["status"], "no_matches")
        self.assertTrue(result["no_reliable_match"])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.context = asyncio.run(prepare())

    def test_report_gets_company_and_clean_text_and_renders_canonical_links(self):
        with patch("navigator.focused.company_report.llm.chat_json", side_effect=verified_report) as model:
            result = generate_report(self.context)
        supplied = json.loads(model.call_args_list[0].args[1])
        self.assertEqual(supplied["company"]["requirements"], COMPANY["requirements"])
        self.assertEqual(supplied["candidate"]["name"], "Glucose sensor laboratory")
        self.assertIn(QUOTE, " ".join(e["text"] for e in supplied["sources"][0]["excerpts"]))
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["report"]["recommendations"][0]["finding_id"], "f1")
        self.assertIn(f"[S1]({URL})", render_markdown(result))

    def test_model_cannot_override_database_identity_or_supply_unchecked_quotes(self):
        for field, value in (("finding_id", "invented"), ("quote", "Invented quotation"), ("selection_score", 100)):
            raw = model_report()
            raw["fit"][field] = value
            with self.subTest(field=field), patch("navigator.focused.company_report.llm.chat_json", return_value=raw):
                result = generate_report(self.context)
            self.assertEqual(result["report"]["recommendations"], [])
            self.assertEqual(len(result['generation_errors']), 1)

    def test_rerun_does_not_inherit_prior_model_reply_provenance(self):
        self.context['model_response_provenance']={'model':'old-model','reply_sha256':['old-response']}
        with patch('navigator.focused.company_report.llm.chat_json',side_effect=verified_report):
            result=generate_report(self.context)
        self.assertNotIn('model_response_provenance',result)
        self.assertEqual(self.context['model_response_provenance']['reply_sha256'],['old-response'])

    def test_another_candidates_source_cannot_support_a_recommendation(self):
        context = copy.deepcopy(self.context)
        context["sources"].append({**context["sources"][0], "id": "S2"})
        raw = model_report()
        raw["fit"]["excerpt_ids"] = ["S2P1"]
        with patch("navigator.focused.company_report.llm.chat_json", return_value=raw), self.assertRaises(ValueError):
            generate_report(context)

    def test_excerpt_catalog_is_rechecked_against_source_text(self):
        forged = [{'excerpt_id':'S1P1','text':'This false quotation never appeared in the supplied source.'}]
        with patch('navigator.focused.report_contract.source_excerpts',return_value=forged), \
             patch('navigator.focused.report_contract.llm.chat_json',return_value=model_report()):
            result=generate_report(self.context)
        self.assertEqual(result['report']['recommendations'],[])
        self.assertEqual(len(result['claim_validation_errors']),1)

    def test_cli_writes_json_and_markdown_without_modifying_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            company, db = root / "company.json", root / "focused.sqlite"
            company.write_text(json.dumps(COMPANY), encoding="utf-8")
            db.write_bytes(b"untouched")
            parser = ArgumentParser()
            add_command(parser.add_subparsers(dest="cmd"))
            args = parser.parse_args(["company-report", str(company), "--db", str(db), "--out", str(root / "report.json"),
                                      "--markdown-out", str(root / "report.md")])
            with patch("navigator.focused.company_report.read_highlights", return_value=([finding()], None)), \
                 patch("navigator.focused.company_report.prepare_context", return_value=self.context), \
                 patch("navigator.focused.company_report.config.LLM_ENABLED", True), \
                 patch("navigator.focused.company_report.llm.chat_json", side_effect=verified_report), redirect_stdout(io.StringIO()):
                dispatch(args, parser)
            self.assertEqual(json.loads((root / "report.json").read_text())["status"], "complete")
            self.assertIn(QUOTE, (root / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(json.loads(company.read_text()), COMPANY)
            self.assertEqual(db.read_bytes(), b"untouched")

    def test_model_failure_preserves_prepared_context(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            company = root / "company.json"
            company.write_text(json.dumps(COMPANY), encoding="utf-8")
            parser = ArgumentParser()
            add_command(parser.add_subparsers(dest="cmd"))
            args = parser.parse_args(["company-report", str(company), "--out", str(root / "report.json")])
            with patch("navigator.focused.company_report.read_highlights", return_value=([finding()], None)), \
                 patch("navigator.focused.company_report.prepare_context", return_value=self.context), \
                 patch("navigator.focused.company_report.config.LLM_ENABLED", True), \
                 patch("navigator.focused.company_report.llm.chat_json", side_effect=ValueError("Invalid model output")), \
                 redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                dispatch(args, parser)
            self.assertEqual(json.loads((root / "report.json").read_text())["status"], "prepared")


if __name__ == "__main__":
    unittest.main()
