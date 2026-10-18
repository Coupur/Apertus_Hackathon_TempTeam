"""Unified inventory regressions: attribution, identity, caps and entailment."""
import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from navigator.focused.entities import extract_entities, assess_entity, ENTITY_WEIGHTS
from navigator.focused.models import Document, Settings
from navigator.focused.privacy import public_record, has_contact
from navigator.focused.ranking import rank, score_record, SELECTION_VERSION
from navigator.focused.store import Store, identity_keys
from test_focused import record, document
from navigator.focused.company_report import generate_report, render_markdown, prepare_context, CompanyBrief, shortlist
from navigator.focused.web import Boundary, Response
from test_company_report import prepare, model_report, QUOTE, finding, COMPANY, URL as SOURCE_URL

URL='https://www.artorg.unibe.ch/research/sensor/index_eng.html'
BASE='Sensor Project\nThe research project investigates glucose measurements using microfluidic assays and develops a method for reliable measurement of glucose concentrations in blood samples.'


def entities(extra,links=(),url=URL):
    document=Document(url,'Sensor Project',BASE+'\n'+extra,'artorg','ARTORG','2026-10-19',url,(),links)
    work=dict(id='work-1',original_name='Sensor Project',type='project',unit='',organizations=['ARTORG'],
              evidence=[dict(quote=BASE.split('\n')[1],source_url=url)],source_urls=[url])
    return extract_entities(document,[work])


class EntityTests(unittest.TestCase):
    def test_mention_contact_and_professor_title_are_not_a_role(self):
        for text in ('Prof. Alice Example and Bob Person attended.','Contact: Prof. Alice Example','Team photograph: Alice Example'):
            self.assertEqual(entities(text),[])

    def test_named_company_in_team_list_is_not_a_person(self):
        self.assertEqual(entities('Project team: Example Digital (Technology consultant)'),[])

    def test_link_needs_accepted_work(self):
        doc=Document(URL,'Sensor Project',BASE+'\nPrincipal investigator: Alice Example','artorg','ARTORG','today')
        self.assertEqual(extract_entities(doc,[]),[])

    def test_leader_and_participant_have_separate_contribution(self):
        rs=entities('Principal investigator: Alice Example\nProject team: Bob Person, Clara Person')
        levels={r['original_name']:assess_entity(r)['criteria']['contribution']['score'] for r in rs}
        self.assertEqual(levels,{'Alice Example':4,'Bob Person':1,'Clara Person':1})
        self.assertEqual(assess_entity(rs[0])['score'],25)

    def test_role_list_quotes_preserve_all_intervening_names(self):
        source = 'Project team\nAlice Example\nBob Person\nClara Person'
        rs = entities(source)
        self.assertEqual(len(rs), 3)
        for r in rs:
            self.assertIn(r['related_works'][0]['quote'], source)
        self.assertEqual(rs[-1]['related_works'][0]['quote'], source)

    def test_removed_contact_block_ends_a_role_list(self):
        rs = entities('Project team\nAlice Example\nEmail\nalice@example.org\nBob Person')
        self.assertEqual([r['original_name'] for r in rs], ['Alice Example'])

    def test_named_group_activity_quote_does_not_splice_removed_contacts(self):
        title = 'Sensor Research Group (SRG)'
        text = title + '\n\nEmail\nteam@example.org\n\nThe SRG has developed a working prototype for glucose measurement.'
        doc = Document(URL,title,text,'artorg','ARTORG','today')
        work = dict(id='work',original_name=title,type='project',unit='',organizations=['ARTORG'],
                    evidence=[dict(quote=text.splitlines()[-1],source_url=URL)])
        rs = extract_entities(doc,[work])
        self.assertEqual(len(rs),1)
        self.assertIn(rs[0]['related_works'][0]['quote'],text)
        self.assertFalse(has_contact(rs[0]['related_works'][0]['quote']))

    def test_names_on_other_projects_are_not_linked_by_cooccurrence(self):
        doc=Document(URL,'Research projects','Sensor Project\n'+BASE.split('\n')[1]+'\n\nUnrelated Project\nPrincipal investigator: Alice Example','artorg','ARTORG','today')
        work=dict(id='work',original_name='Sensor Project',type='project',unit='',organizations=['ARTORG'],evidence=[dict(quote=BASE.split('\n')[1],source_url=URL)])
        self.assertEqual(extract_entities(doc,[work]),[])

    def test_person_never_inherits_colleague_or_work_score(self):
        r=entities('Project team: Alice Example')[0]
        ev=dict(quote='Bob Person independently reproduced the validated method.',source_url=URL,work_id='work-1')
        r['attributed_evidence']=[ev]
        r['related_works'][0]['work_evidence']=[ev]
        r['evaluation']={'score':100}
        assessed=assess_entity(r)
        self.assertEqual(assessed['score'],6.25)
        self.assertEqual(assessed['criteria']['results']['score'],0)
        self.assertIn('No data',assessed['criteria']['results']['reason'])

    def test_repetition_does_not_increase_score(self):
        r=entities('Principal investigator: Alice Example')[0]
        expected=assess_entity(r)
        r['related_works']*=5
        r['attributed_evidence']*=5
        self.assertEqual(assess_entity(r),expected)

    def test_unnamed_awards_and_generic_partners_do_not_earn_points(self):
        r=entities('Project team: Alice Example')[0]
        r['attributed_evidence']=[dict(quote='Alice Example received an international award and collaborated with a company.',source_url=URL,work_id='work-1')]
        result=assess_entity(r)
        self.assertEqual(result['criteria']['recognition']['score'],0)
        self.assertEqual(result['criteria']['collaboration']['score'],0)

    def test_named_awards_require_independent_bodies_for_level_four(self):
        r=entities('Principal investigator: Alice Example')[0]
        r['attributed_evidence']=[dict(quote=f'Alice Example received the {award} Prize from {body}, an international award.',source_url=URL,work_id='work-1')
                                   for award,body in [('Edison','Alpha Foundation'),('Curie','Beta Foundation')]]
        result=assess_entity(r)
        self.assertEqual(result['criteria']['recognition']['score'],4)
        self.assertEqual(len(result['criteria']['recognition']['evidence']),2)

    def test_legacy_records_do_not_gain_unified_fields_without_new_source_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.sqlite')
            legacy=record()
            for key in ('source_read_version','selection_version','selection_score'): legacy.pop(key,None)
            store.upsert(legacy)
            self.assertNotIn('selection_score',store.findings()[0])
            store.close()

    def test_one_global_cap_and_entity_score_beats_legacy_work_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.sqlite',1)
            work=record(score=4)
            work_id=store.upsert(work)
            expert=entities('Principal investigator: Alice Example')[0]
            expert['related_works'][0]['work_id']=work_id
            expert['source_read_version']=SELECTION_VERSION
            store.upsert(expert)
            self.assertEqual(len(store.findings()),1)
            self.assertEqual(store.findings()[0]['type'],'expert')
            self.assertEqual(store.findings()[0]['related_works'][0]['work_id'],work_id)
            store.close()

    def test_formula_and_own_attributed_results(self):
        r=entities('Principal investigator: Alice Example')[0]
        r['attributed_evidence']=[dict(quote='Alice Example developed a method using microscopy and measured accuracy of 95%.',source_url=URL,work_id='work-1')]
        a=assess_entity(r)
        self.assertEqual(a['criteria']['results']['score'],2)
        self.assertEqual(a['score'],sum(ENTITY_WEIGHTS[k]*v['score']/4 for k,v in a['criteria'].items()))

    def test_same_name_with_different_profiles_does_not_merge(self):
        first=entities('Principal investigator: Alice Example',((URL+'/persons/alice_a','Alice Example',''),))[0]
        second=entities('Principal investigator: Alice Example',((URL+'/persons/alice_b','Alice Example',''),))[0]
        self.assertFalse(identity_keys(first)&identity_keys(second))

    def test_language_profiles_merge_and_work_entity_ids_stay_separate(self):
        first=entities('Principal investigator: Alice Example',(('https://www.artorg.unibe.ch/persons/alice/index_eng.html','Alice Example',''),))[0]
        second=entities('Projektleiter: Alice Example',(('https://www.artorg.unibe.ch/persons/alice/index_ger.html','Alice Example',''),))[0]
        self.assertEqual(identity_keys(first),identity_keys(second))
        self.assertNotEqual(first['id'],'work-1')

    def test_no_name_only_merge_across_pages(self):
        a=entities('Principal investigator: Alice Example')[0]
        b=entities('Principal investigator: Alice Example',url=URL+'/other')[0]
        self.assertFalse(identity_keys(a)&identity_keys(b))

    def test_source_institution_is_not_external_person_affiliation(self):
        r=entities('Principal investigator: Alice Example, Chief Physician – Kantonsspital Olten')[0]
        self.assertEqual(r['organizations'],['Kantonsspital Olten'])

    def test_contact_fields_and_contact_text_are_removed_from_legacy_reads(self):
        raw={'experts':[{'name':'Alice Example','email':'a@example.com','phone2':'+41 31 123 45 67'}],
             'text':'Research result.\nEmail: a@example.com\nPhone\n031 123 45 67\nb(at)example.com'}
        cleaned=public_record(raw)
        self.assertEqual(cleaned,{'experts':[{'name':'Alice Example'}],'text':'Research result.'})

    def test_store_keeps_link_proof_after_work_falls_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(Path(tmp)/'test.sqlite',1)
            r=entities('Principal investigator: Alice Example')[0]
            r['source_read_version']=SELECTION_VERSION
            s.upsert(r)
            retained=s.findings()[0]
            self.assertEqual(retained['selection_score'],25)
            self.assertEqual(retained['related_works'][0]['work_id'],'work-1')
            self.assertTrue(retained['related_works'][0]['work_evidence'])
            s.close()

    def test_default700_and_optional500_limits(self):
        self.assertEqual(Settings().max_findings,700)
        self.assertEqual(Settings(max_findings=500).max_findings,500)
        with self.assertRaises(ValueError): Settings(max_findings=701)

    def test_score_and_stable_id_only_ordering(self):
        a={'selection_score':10,'id':'a','scores':{'scientific':4}}
        b={'selection_score':20,'id':'b','scores':{'scientific':2}}
        self.assertGreater(rank(b),rank(a))
        b['selection_score']=10
        self.assertGreater(rank(b),rank(a))

    def test_language_detail_urls_merge_works_and_order_is_stable(self):
        en='https://www.artorg.unibe.ch/en/project/sensor'
        de='https://www.artorg.unibe.ch/de/project/messung'
        first_doc=document(en,'Sensor research')
        second_doc=document(de,'Sensorforschung')
        first_doc.links=((de,'German',''),)
        second_doc.links=((en,'English',''),)
        first=record(first_doc)
        second=record(second_doc)
        identities=[]
        for sequence in ((first,second),(second,first)):
            with tempfile.TemporaryDirectory() as tmp:
                store=Store(Path(tmp)/'test.sqlite')
                for r in sequence: store.upsert(r)
                self.assertEqual(len(store.findings()),1)
                identities.append(store.findings()[0]['id'])
                store.close()
        self.assertEqual(*identities)

    def test_700_cap_with_a_higher_scoring_late_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.sqlite',700,defer_trim=True)
            for i in range(705):
                item=record()
                item.update(original_name=f'Distinct Facility {i}',title=f'Distinct Facility {i}')
                if i==704:
                    item['evidence'][0]['quote']='A randomized controlled trial using microscopy with 100 patients measured accuracy of 99% (confidence interval 97 to 100).'
                store.upsert(item)
            store.defer_trim=False
            store.finish({'mode':'collection'},100)
            rs=store.findings()
            self.assertEqual(len(rs),700)
            self.assertEqual(rs[0]['original_name'],'Distinct Facility 704')
            store.close()


def checked_responses(*judgments):
    replies=[]
    for judgment in judgments:
        replies.append({'analysis':'Each assertion is compared with evidence.',**judgment} if isinstance(judgment,dict) else judgment)
        if isinstance(judgment,dict) and judgment.get('verdict')=='entailed':
            replies.append({'issue_found':False,'reason':'No unsupported assertion.'})
    return replies


class EntailmentTests(unittest.TestCase):
    def setUp(self): self.context=asyncio.run(prepare())

    def test_exact_excerpt_is_injected_without_model_transcription(self):
        decision={'verdict':'entailed','reason':'Direct quotation.'}
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=[model_report(),*checked_responses(decision)]) as calls:
            result=generate_report(self.context)
        quote=result['report']['recommendations'][0]['fit'][0]['citations'][0]['quote']
        self.assertIn(QUOTE,quote)
        self.assertIn(quote,self.context['sources'][0]['text'])
        for call in calls.call_args_list:
            self.assertIn('json_schema',call.kwargs)

    def test_unknown_excerpt_cannot_publish(self):
        draft=model_report()
        draft['fit']['excerpt_ids']=['S1P999']
        with patch('navigator.focused.report_contract.llm.chat_json',return_value=draft),self.assertRaises(ValueError):
            generate_report(self.context)

    def test_three_pages_per_finding_and_shared_budget_at_top_ten(self):
        class FakeFetcher:
            boundary=Boundary([SOURCE_URL])
            async def get(self,url):
                return Response(url,200,'text/plain',QUOTE*200,{})
        company=CompanyBrief(**COMPANY)
        findings=[]
        for i in range(10):
            item=finding(str(i))
            item['source_urls']=[SOURCE_URL+f'/{i}/{j}' for j in range(4)]
            findings.append(item)
        context=asyncio.run(prepare_context(company,shortlist(company,findings,10),FakeFetcher()))
        self.assertEqual(len(context['candidates']),10)
        self.assertEqual(len(context['sources']),30)
        self.assertTrue(all(len(c['source_ids'])==3 for c in context['candidates']))
        self.assertLessEqual(sum(len(s['text']) for s in context['sources']),60000)

    def test_verbatim_but_unrelated_radar_claim_is_removed(self):
        draft=model_report()
        draft['fit']['text']='The radar can validate clinical CGM sensor accuracy.'
        radar='These physiological signals change during nocturnal hypoglycemia, positioning radar as a promising indirect detection tool. Clinical validation pairing radar with glucose measurement is now needed.'
        self.context['sources'][0]['text']=radar
        check={'analysis':'The assertion exceeds the evidence.','verdict':'not_enough_information','reason':'A proposed radar validation does not establish completed CGM sensor validation.'}
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=[draft,check]) as call:
            result=generate_report(self.context)
        self.assertEqual(call.call_count,2)
        self.assertEqual(result['report']['recommendations'],[])
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertNotIn('The radar can',render_markdown(result))

    def test_partial_verification_removes_only_unsubstantiated_claim(self):
        draft=model_report()
        unsupported={'kind':'service','text':'An external CGM certification service is available.','excerpt_ids':['S1P1']}
        draft['claims'].append(unsupported)
        checked=[{'verdict':'entailed','reason':'Explicit source fact.'},
                 {'verdict':'not_enough_information','reason':'No service offer.'}]
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=[draft,*checked_responses(*checked)]) as calls:
            result=generate_report(self.context)
        rec=result['report']['recommendations'][0]
        self.assertEqual(rec['services'],[])
        self.assertEqual(rec['name'],self.context['candidates'][0]['name'])
        self.assertEqual(rec['significance']['selection_score'],self.context['candidates'][0]['selection_score'])
        self.assertNotIn(unsupported['text'],render_markdown(result))
        self.assertIn(QUOTE,render_markdown(result))
        for call in calls.call_args_list[1:]:
            payload=json.loads(call.args[1])
            self.assertNotIn('claims',payload)
            self.assertIn('hypothesis',payload)

    def test_invalid_checker_response_never_publishes_or_retries_for_acceptance(self):
        from navigator.llm import InvalidModelResponse
        for reply in ({}, {'verdict':'maybe','reason':'uncertain'},
                      {'verdict':'entailed','reason':'ok','claim_id':'invented'}, InvalidModelResponse('truncated')):
            with self.subTest(reply=reply),patch('navigator.focused.report_contract.llm.chat_json',side_effect=[model_report(),reply]) as calls:
                result=generate_report(self.context)
            self.assertEqual(calls.call_count,2)
            self.assertEqual(result['report']['recommendations'],[])
            self.assertFalse(result['verification']['decisions'][0]['supported'])

    def test_positive_entailment_alone_cannot_publish(self):
        replies=[model_report(),{'analysis':'Each assertion is compared with evidence.','verdict':'entailed','reason':'Initially appears supported.'},
                 {'issue_found':True,'reason':'The quoted text does not establish the collaboration offer.'}]
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=replies):
            result=generate_report(self.context)
        self.assertEqual(result['report']['recommendations'],[])
        decision=result['verification']['decisions'][0]
        self.assertEqual(decision['entailment_verdict'],'entailed')
        self.assertTrue(decision['audit_issue_found'])
        self.assertFalse(decision['supported'])

    def test_invalid_evidence_audit_cannot_publish(self):
        replies=[model_report(),{'analysis':'Each assertion is compared with evidence.','verdict':'entailed','reason':'Initially appears supported.'},{}]
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=replies):
            result=generate_report(self.context)
        self.assertEqual(result['report']['recommendations'],[])

    def test_bounded_syntax_retry_keeps_schema_and_still_verifies(self):
        from navigator.llm import InvalidModelResponse
        checked={'verdict':'entailed','reason':'Direct evidence.'}
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=[InvalidModelResponse('truncated'),model_report(),*checked_responses(checked)]) as calls:
            result=generate_report(self.context)
        self.assertEqual(calls.call_count,4)
        self.assertEqual(calls.call_args_list[0].kwargs['json_schema'],calls.call_args_list[1].kwargs['json_schema'])
        self.assertEqual(result['generation_method'],'per_candidate_json_schema')
        self.assertEqual(result['status'],'complete')

    def test_requirements_are_not_replaced_by_weaker_model_paraphrases(self):
        draft=model_report()
        draft['claims'].append({'kind':'supported_requirement','text':'Improved glucose outcomes',
                    'requirement_index':0,'excerpt_ids':['S1P1']})
        checked=[{'verdict':'entailed','reason':'Direct evidence.'},
                 {'verdict':'not_enough_information','reason':'Original requirement not established.'}]
        with patch('navigator.focused.report_contract.llm.chat_json',side_effect=[draft,*checked_responses(*checked)]) as calls:
            result=generate_report(self.context)
        fit_payload=json.loads(calls.call_args_list[1].args[1])
        requirement_payload=json.loads(calls.call_args_list[-1].args[1])
        self.assertEqual(fit_payload['requirement'],'')
        self.assertEqual(requirement_payload['hypothesis']['text'],COMPANY['requirements'][0])
        self.assertEqual(requirement_payload['requirement'],COMPANY['requirements'][0])
        self.assertEqual(result['report']['recommendations'][0]['supported_requirements'],[])

    def test_unattributed_people_cannot_be_published(self):
        draft=model_report()
        draft['claims'].append({'kind':'expert','name':'Alice Example','text':'Alice is an expert.','excerpt_ids':['S1P1']})
        with patch('navigator.focused.report_contract.llm.chat_json',return_value=draft):
            result=generate_report(self.context)
        self.assertEqual(result['report']['recommendations'],[])
        self.assertEqual(len(result['generation_errors']),1)

    def test_excerpt_passages_retain_names_and_do_not_bridge_omissions(self):
        from navigator.focused.report_contract import source_excerpts
        source={'id':'S1','text':'Michael Example\nIndustry expert\nTwenty years in device development.\n...\nUnrelated research paragraph.'}
        excerpts=source_excerpts(source)
        self.assertIn('Michael Example\nIndustry expert',excerpts[0]['text'])
        self.assertEqual(len(excerpts),2)
        for item in excerpts:
            self.assertIn(item['text'],source['text'])
            self.assertNotIn('...',item['text'])

    def test_candidates_are_generated_in_isolation(self):
        self.context['candidates'].append({**self.context['candidates'][0],'id':'second','name':'Other lab','source_ids':['S2']})
        self.context['sources'].append({**self.context['sources'][0],'id':'S2','url':SOURCE_URL+'/second'})
        with patch('navigator.focused.report_contract.llm.chat_json',return_value={'fit':None,'claims':[]}) as calls:
            result=generate_report(self.context)
        self.assertEqual(calls.call_count,2)
        for call, sid in zip(calls.call_args_list,('S1','S2')):
            payload=json.loads(call.args[1])
            self.assertEqual([s['id'] for s in payload['sources']],[sid])
            permitted=call.kwargs['json_schema']['$defs']['FitDraft']['properties']['excerpt_ids']['items']['enum']
            self.assertTrue(all(e.startswith(sid+'P') for e in permitted))
        self.assertEqual(result['report']['recommendations'],[])


if __name__=='__main__': unittest.main()
