"""Regressions from live source inspection; source excerpts are not model output."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from navigator.extract import extract
from navigator.focused.crawl import Crawler, plain, priority
from navigator.focused.models import Document, Settings
from navigator.focused.rules import evaluate
from navigator.focused.selection import validate_findings
from navigator.focused.store import Store
from navigator.focused.web import Boundary, Fetcher, Response
from navigator.sources import Source


def select(text, title="Research result", organization="ARTORG"):
    doc = Document("https://www.artorg.unibe.ch/research/result", title, text, "artorg", organization, "2026-10-18")
    records, rejected = validate_findings(evaluate(doc), doc)
    if rejected:
        raise AssertionError(rejected)
    return records


class TextAndRuleRegressions(unittest.TestCase):
    def test_inline_markup_keeps_sentences_and_headings_keep_boundaries(self):
        html = "<main><h1>Testing Facility</h1><p>Our <strong>microfluidic</strong> devices support <a href='/research'>organs-on-chip</a> research.</p><h2>Future work</h2><p>We plan new instruments.</p></main>"
        text = extract(html, "https://www.unibe.ch/", paragraphs=True)["text"]
        self.assertIn("Our microfluidic devices support organs-on-chip research.", text)
        self.assertIn("\n\nFuture work\n", text)
        self.assertNotIn("\x1e", text)

    def test_unrelated_sections_cannot_combine_equipment_into_a_finding(self):
        text = "Animal Facility\nThe laboratory offers studies under axenic and gnotobiotic conditions.\n\nSequencing Unit\nThe unit supports next-generation sequencing research."
        self.assertFalse(select(text, "Research infrastructure"))

    def test_wordpress_html_keeps_the_same_evidence_boundaries(self):
        html = "<h2>Animal Facility</h2><p>The laboratory offers studies under axenic and gnotobiotic conditions.</p><h2>Sequencing Unit</h2><p>The unit supports next-generation sequencing research.</p>"
        text = plain({"rendered": html})
        self.assertIn("\n\nSequencing Unit\n", text)
        self.assertFalse(select(text, "Research infrastructure"))

    def test_prospective_comparison_does_not_require_randomization(self):
        # ARTORG's PeriVision report: a paired clinical validation, not an RCT.
        text = "The company shared on August 10, 2026, that a new prospective study at the Inselspital has confirmed that the VisionOne VR perimeter delivers clinical performance equivalent to the Octopus 900 – a stationary perimeter considered to be the gold standard. The study evaluated 73 patients (120 eyes) with mild, moderate and severe glaucoma, with each patient completing both examinations during the same visit."
        records = select(text, "PeriVision clinical performance")
        self.assertEqual(len(records), 1)
        self.assertIn("comparative_result", records[0]["matched_rules"])

    def test_future_work_does_not_erase_existing_facility(self):
        text = "The ARTORG Organs-on-Chip Facility (OOCF) provides researchers at the University of Bern, the Inselspital and beyond with the infrastructure to fabricate microfluidic devices and to culture and test organs-on-chip. An additional imaging platform will become available to users in due course."
        records = select(text, "Organs-on-Chip Facility")
        self.assertEqual(len(records), 1)
        self.assertNotIn("will become", records[0]["evidence"][0]["quote"])

    def test_shortest_sufficient_excerpt_avoids_unrelated_intro(self):
        text = "Our institute runs many events. We welcome visiting colleagues. The Atlas Research Platform offers validated testing for external research projects."
        records = select(text, "Atlas Research Platform")
        self.assertEqual(records[0]["evidence"][0]["quote"], "The Atlas Research Platform offers validated testing for external research projects.")

    def test_funded_project_has_stable_name_across_repeated_mentions(self):
        text = "The ARTORG Center has secured Stage 1 funding from the European Innovation Council's Advanced Innovation Challenges program for the VANTAGE project. The center's project VANTAGE is one of 20 selected projects."
        records = select(text, "ARTORG secures EIC funding")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["original_name"], "VANTAGE")
        self.assertIn({"kind": "project", "value": "VANTAGE"}, records[0]["identifiers"])

    def test_generic_funding_portal_is_not_a_project(self):
        self.assertFalse(select("The university coordinates several Horizon Europe research projects and has received grants from the European Research Council.", "EU project portfolio"))

    def test_service_list_keeps_heading_instead_of_inventing_a_name(self):
        text = "Our services\nSupport for researchers.\n\nLab Services & Facility\nClinical Facility Space\nOvernight Clinical Space\nBio Safety 2 Lab\nOffice Space\nMeeting Space"
        records = select(text, "Services - Diabetes Center Berne", "Diabetes Center Berne")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["original_name"], "Lab Services & Facility")

    def test_two_distinct_headed_findings_can_survive_on_one_page(self):
        text = "Atlas Facility\nThe facility provides validated research testing for external research projects.\n\nOrion Facility\nThe facility offers calibrated measurement services for outside research partners."
        self.assertEqual({r["original_name"] for r in select(text)}, {"Atlas Facility", "Orion Facility"})

    def test_outcome_page_outweighs_call_for_applications(self):
        outcome = priority("https://www.artorg.unibe.ch/news/clinical_performance", "Clinical performance demonstrated", "Research", "News", 2)
        call = priority("https://www.artorg.unibe.ch/news/call_for_applications", "Call for research applications", "Research funding", "News", 2)
        self.assertGreater(outcome, call)

    def test_api_title_and_timestamp_do_not_count_as_content(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "focused.sqlite")
            try:
                source = Source("dcberne", "DCB", "https://www.dcberne.com/", "Diabetes Center Berne")
                crawler = Crawler([source], store, Settings())
                item = {"title": {"rendered": "A long publication title " * 12}, "content": {"rendered": ""},
                        "link": "https://www.dcberne.com/publication/result", "date": "2026-01-01"}
                response = Response("https://www.dcberne.com/wp-json/wp/v2/publication", 200, "application/json", json.dumps([item]), {})
                self.assertFalse(crawler.api_documents(response, 0))
                self.assertIn(item["link"], crawler.queued)
                self.assertEqual(crawler.report["api_page_fallbacks"], 1)
            finally:
                store.close()


class BroaderSelectionTests(unittest.TestCase):
    def test_navigation_heading_cannot_replace_article_title(self):
        html = '<title>Real scientific article</title><nav><h1>Navigation</h1></nav><main><h1>Research platform</h1><p>Scientific content.</p></main>'
        self.assertEqual(extract(html, "https://www.unibe.ch/article", paragraphs=True)["title"], "Research platform")

    def test_workshop_participation_is_not_a_research_finding(self):
        text = "Over two days of discussion, participants identified and showcased best practices, while also exploring challenges based on their shared experiences and longstanding involvement in research co-creation."
        self.assertFalse(select(text, "Workshop: Strengthening research through patient partnerships"))

    def test_institution_history_is_not_a_research_result(self):
        text = "The Department for Biomedical Research was established in 1994 by the University of Bern and the university hospital. It supports research and teaching across many departments."
        self.assertFalse(select(text, "Institute history"))

    def test_navigation_card_is_not_evidence(self):
        text = "Menstrual Cycle Study: Results published in Diabetes Care 5 October 2026 | Applied Clinical Diabetes Research, Clinical Studies, Research projects, Technology Projects"
        self.assertFalse(select(text, "Project news"))

    def test_media_relations_is_not_research(self):
        text = "Wir beantworten Medienanfragen, stellen gerne für Journalistinnen und Journalisten den Kontakt zu Expertinnen und Experten her und informieren mit Medienmitteilungen über Forschungsergebnisse der Universität Bern."
        self.assertFalse(select(text, "Informationen für Medienschaffende"))

    def test_related_cards_removed_but_main_project_and_links_survive(self):
        html = '<title>Research - DCB</title><main><h1>Glucose sensor project</h1><p>The research project investigates how optical measurements can detect changing glucose levels through non-invasive monitoring in patients.</p><div class="et_pb_blog_grid_wrapper"><h2><a href="/other">Unrelated clinical study</a></h2><p>Other research results go here.</p></div></main>'
        page = extract(html, "https://www.dcberne.com/project/sensor", paragraphs=True)
        self.assertEqual(page["title"], "Glucose sensor project")
        self.assertNotIn("Unrelated clinical study", page["text"])
        self.assertIn("https://www.dcberne.com/other", page["links"])
        self.assertIn("optical measurements", page["text"])

    def test_research_type_changes_do_not_split_the_same_named_work(self):
        text = "The research project investigates how planetary radiation and atmospheric chemistry influence the formation of complex organic molecules on rocky exoplanets."
        rec = select(text, "Planetary chemistry research")[0]
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "focused.sqlite")
            try:
                first_id = store.upsert(rec)
                updated = {**rec, "type": "research_result"}
                self.assertEqual(first_id, store.upsert(updated))
                self.assertEqual(len(store.findings()), 1)
            finally:
                store.close()

    def test_research_objectives_qualify_without_completed_results(self):
        text = "Prebiotic Chemistry in Exoplanet Environments\nIn this project, we investigate whether rocky exoplanet environments can support prebiotic chemistry and what these environments imply for interpreting potential biosignatures."
        records = select(text, "Prebiotic Chemistry in Exoplanet Environments")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["scores"]["scientific"], 2)
        self.assertIn("research_activity", records[0]["matched_rules"])
        self.assertNotEqual(records[0]["status"], "completed")

    def test_specified_service_does_not_need_multiple_advanced_instruments(self):
        text = "Nanopore Sequencing Service\nThe institute offers a nanopore sequencing service for bacterial and viral genomics, which allows other laboratories to access long-read whole genome and direct RNA sequencing."
        records = select(text, "Nanopore Sequencing Service")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["scores"]["capability"], 2)
        self.assertIn("research_service", records[0]["matched_rules"])

    def test_reported_result_does_not_need_clinical_trial_or_numbers(self):
        text = "The researchers discovered that the atmospheric composition of rocky exoplanets is shaped by interactions between stellar radiation and chemical processes, using coupled climate simulations."
        records = select(text, "Atmospheric chemistry of rocky exoplanets")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["scores"]["scientific"], 2)
        self.assertIn("reported_research", records[0]["matched_rules"])

    def test_german_project_objective_is_eligible(self):
        text = "Das Forschungsprojekt untersucht die Auswirkungen unterschiedlicher Landnutzungsformen auf die biologische Vielfalt und entwickelt Modelle für den Schutz gefährdeter Lebensräume."
        records = select(text, "Landnutzung und biologische Vielfalt")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["scores"]["scientific"], 2)

    def test_detail_page_subsections_are_one_project(self):
        text = "Climate Landscape Study\nThe project investigates land use practices that reduce greenhouse gas emissions and improve adaptation to climate change.\n\nProject activities\nResearchers are developing shared landscape scenarios with local farmers to evaluate the effects of land use practices on carbon sequestration."
        records = select(text, "Climate Landscape Study")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["original_name"], "Climate Landscape Study")

    def test_secondary_score_still_requires_verbatim_evidence(self):
        from navigator.focused.models import Document
        from navigator.focused.rules import evaluate
        from navigator.focused.selection import validate_findings
        text = "The research project investigates how planetary radiation and atmospheric chemistry influence the formation of complex organic molecules on rocky exoplanets."
        doc = Document("https://www.unibe.ch/research/planet", "Planetary chemistry", text, "www", "University of Bern", "2026-10-18T12:00:00Z")
        raw = evaluate(doc)
        self.assertTrue(raw["findings"])
        raw["findings"][0]["evidence"][0]["quote"] = "An invented experimental result that the original source never actually reported."
        accepted, rejected = validate_findings(raw, doc)
        self.assertFalse(accepted)
        self.assertEqual(rejected["nonverbatim_evidence"], 1)


class DecodingRegressions(unittest.IsolatedAsyncioTestCase):
    async def test_html_meta_charset_is_used_without_http_charset(self):
        async def no_wait(_):
            pass

        html = '<meta charset="windows-1252"><main>Universität Bern – Forschung</main>'

        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, content=html.encode("cp1252"), headers={"content-type": "text/html"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("navigator.focused.web.asyncio.sleep", new=no_wait):
                response = await Fetcher(client, Boundary(["https://www.unibe.ch/"]), Settings()).get("https://www.unibe.ch/")
        self.assertIn("Universität Bern – Forschung", response.text)
        self.assertNotIn("\ufffd", response.text)
