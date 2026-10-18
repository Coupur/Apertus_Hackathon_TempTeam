"""Entity scores must distinguish supported capabilities without moving credit."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from navigator.focused.entities import assess_entity, extract_entities, enrich_entity_evidence, person_name, ENTITY_WEIGHTS
from navigator.focused.models import Document
from navigator.focused.ranking import ranking_summary
from navigator.focused.store import Store, refresh_evaluations
from test_unified_findings import entities, URL, BASE


def team(text, name='Sensor Research Group (SRG)'):
    doc = Document(URL, name, name + '\n\n' + text, 'artorg', 'ARTORG', '2026-10-19')
    work = dict(id='work-1', original_name=name, type='project', organizations=['ARTORG'],
                evidence=[dict(quote=text, source_url=URL)])
    return extract_entities(doc, [work])[0]


class EntityMetricTests(unittest.TestCase):
    def test_methods_differentiate_role_only_topic_and_concrete_method(self):
        role = entities('Project team: Alice Example')[0]
        topic = entities('Project team: Alice Example\nAlice Example investigates diabetes.')[0]
        method = entities('Project team: Alice Example\nAlice Example investigates diabetes using microfluidic assays.')[0]
        scores = [assess_entity(r) for r in (role, topic, method)]
        self.assertEqual([e['criteria']['expertise']['score'] for e in scores], [0, 1, 2])
        self.assertLess(scores[0]['score'], scores[1]['score'])
        self.assertLess(scores[1]['score'], scores[2]['score'])
        self.assertTrue(all(e['criteria']['results']['score'] == 0 for e in scores))

    def test_team_pronoun_keeps_verbatim_name_context(self):
        text = 'The Sensor Research Group (SRG) studies diabetes. We designed algorithms using RNA-Seq data.'
        r = team(text)
        result = assess_entity(r)
        self.assertEqual(result['criteria']['expertise']['score'], 3)
        self.assertEqual(result['criteria']['results']['score'], 1)
        self.assertEqual(result['criteria']['expertise']['quote'], text)

    def test_own_page_first_person_and_acronym_are_supported(self):
        for text in ('Our group studies diabetes using microscopy.', 'The SRG has developed a working prototype using microscopy.'):
            with self.subTest(text=text):
                e = assess_entity(team(text))
                self.assertEqual(e['criteria']['expertise']['score'], 2)
                self.assertIn(e['criteria']['expertise']['quote'], text)

    def test_named_person_continuation_belongs_to_that_person(self):
        text = 'Project team: Alice Example\nAlice Example studies diabetes. She developed a method using microscopy and measured accuracy of 95%.'
        e = assess_entity(entities(text)[0])
        self.assertEqual(e['criteria']['results']['score'], 2)
        self.assertTrue(e['criteria']['results']['quote'].startswith('Alice Example'))

    def test_person_cannot_inherit_team_first_person_or_adjacent_person(self):
        for paragraph in (
            'Our group independently replicated the validated method.',
            'Bob Person independently replicated a method with Alice Example.',
            'Alice Example studies diabetes. Bob Person studies cancer. He independently replicated a method.',
            'Alice Example studies diabetes.\n\nShe independently replicated a method.',
            "Alice Example's colleague independently replicated a method.",
        ):
            with self.subTest(paragraph=paragraph):
                e = assess_entity(entities('Project team: Alice Example\n' + paragraph)[0])
                self.assertEqual(e['criteria']['results']['score'], 0)

    def test_relative_clause_does_not_transfer_another_person_result(self):
        r = entities('Project team: Alice Example\nAlice Example collaborated with Bob Person, who independently replicated a method.')[0]
        self.assertEqual(assess_entity(r)['criteria']['results']['score'], 0)

    def test_future_negative_and_reputation_do_not_earn_extra_points(self):
        for text in ('Alice Example will develop a method using microscopy.',
                     'Alice Example has not developed a method using microscopy.',
                     'Alice Example is a world-famous professor at a prestigious university.'):
            with self.subTest(text=text):
                r = entities('Project team: Alice Example\n' + text)[0]
                self.assertEqual(assess_entity(r)['score'], 6.25)

    def test_future_sentence_does_not_hide_completed_result(self):
        r = team('Our group studies diabetes. We have developed a working prototype using microscopy. We will deploy it in hospitals.')
        e = assess_entity(r)
        self.assertEqual(e['criteria']['results']['score'], 1)
        self.assertEqual(e['criteria']['application']['score'], 1)

    def test_research_for_clinical_evaluation_is_not_completed_testing(self):
        e = assess_entity(team('Our group has developed an in-vivo animal model for the pre-clinical evaluation of medical devices.'))
        self.assertEqual(e['criteria']['results']['score'], 1)
        self.assertEqual(e['criteria']['application']['score'], 0)

    def test_founder_is_not_a_research_result(self):
        e = assess_entity(entities('Project team: Alice Example\nAlice Example is the founder of Example Labs.')[0])
        self.assertEqual(e['criteria']['results']['score'], 0)

    def test_highest_expertise_needs_measured_validation(self):
        r = entities('Project team: Alice Example\nAlice Example validated a microscopy assay against a reference method with measured accuracy of 95%.')[0]
        self.assertEqual(assess_entity(r)['criteria']['expertise']['score'], 4)

    def test_repeated_paragraphs_do_not_increase_metrics(self):
        r = team('Our group studies diabetes using microscopy. We developed a working prototype.')
        expected = assess_entity(r)
        r['related_works'] *= 4
        r['attributed_evidence'] *= 4
        self.assertEqual(assess_entity(r), expected)

    def test_unlinked_and_other_work_evidence_is_not_scored(self):
        r = entities('Project team: Alice Example')[0]
        r['attributed_evidence'] = [dict(quote='Alice Example independently replicated a method.', source_url=URL, work_id='wrong')]
        self.assertEqual(assess_entity(r)['score'], 6.25)

    def test_topic_heading_is_not_a_person(self):
        self.assertEqual(person_name('Mental Health'), '')
        r = entities('Project team: Alice Example')[0]
        r['original_name'] = 'Mental Health'
        self.assertEqual(assess_entity(r)['score'], 0)

    def test_snapshot_without_the_original_role_proof_cannot_enrich_a_person(self):
        r = entities('Principal investigator: Alice Example')[0]
        original = copy.deepcopy(r)
        doc = Document(URL, 'Sensor Project', BASE + '\nProject team: Alice Example\nAlice Example independently replicated the method.',
                       'artorg', 'ARTORG', '2026-10-19')
        enrich_entity_evidence(r, doc)
        self.assertEqual(r, original)

    def test_snapshot_enrichment_preserves_database_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'focused.sqlite'
            source = Path(directory) / 'sources.jsonl'
            r = entities('Project team: Alice Example')[0]
            r['source_read_version'] = 'unified-v1'
            with_source = BASE + '\nProject team: Alice Example\nAlice Example studies diabetes. She uses microscopy to investigate glucose sensing.'
            doc = Document(URL, 'Sensor Project', with_source, 'artorg', 'ARTORG', '2026-10-19')
            source.write_text(json.dumps(asdict(doc)) + '\n', encoding='utf-8')
            store = Store(path)
            fid = store.upsert(r)
            store.save_state(URL, {'status': 'pending'}, '2026-10-19')
            store.close()
            self.assertEqual(refresh_evaluations(path, source), {'findings': 1, 'observations': 1})
            self.assertEqual(refresh_evaluations(path, source), {'findings': 0, 'observations': 0})
            store = Store(path)
            updated = store.findings()[0]
            self.assertEqual(updated['id'], fid)
            self.assertEqual(updated['related_works'], r['related_works'])
            self.assertEqual(updated['evaluation']['criteria']['expertise']['score'], 2)
            self.assertEqual(len(store.pending()), 1)
            store.close()
            self.assertEqual(list(Path(directory).glob('*.sqlite')), [path])

    def test_coverage_and_type_diagnostics_do_not_inflate_score(self):
        r = team('Our group studies diabetes using microscopy.')
        r['evaluation'] = assess_entity(r)
        r['selection_score'] = r['evaluation']['score']
        summary = ranking_summary([r, copy.deepcopy(r)])
        self.assertEqual(sum(ENTITY_WEIGHTS.values()), 100)
        self.assertEqual(r['evaluation']['evidenced_criteria'], 2)
        self.assertEqual(r['evaluation']['assessed_criteria'], 6)
        self.assertEqual(summary['by_type']['team']['distinct_scores'], 1)
        self.assertEqual(summary['by_type']['team']['modal_score_fraction'], 1)


if __name__ == '__main__':
    unittest.main()
