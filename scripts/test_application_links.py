"""Offline URL normalization and MySeoul candidate-path regressions."""
import copy
import json
import re
import socket
import unittest
from unittest.mock import patch

from ingest.application_links import (normalize_application_link, normalize_application_links,
    normalize_application_link_text, application_link_facts_view)
from ingest.connectors.myseoul_program import safe_application_link, normalize_detail
from ingest.myseoul_ai import myseoul_input, fact_sections
from ingest.reclassification_ai import classification_input, protected_information, process_reclassified_job
from ingest.program_ai import ProgramAIAdapter
from test_myseoul_program import observed_detail, url
from test_body_markdown_pipeline import synthetic_context, run_fixture, KO, JA
from test_reclassification_ai import context as classified_context, ID as CLASSIFIED_ID, REV

BASE='https://forms.gle/synthetic?entry.123=a%2Bb&lang=ja#apply'
TRACKED=BASE.replace('#apply','&fbclid=one&utm_source=social#apply')
OTHER=BASE.replace('#apply','&fbclid=two&utm_campaign=sample#apply')


class ApplicationLinkTests(unittest.TestCase):
    def setUp(self):
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden'))
        self.network.start();self.addCleanup(self.network.stop)

    def test_known_tracking_keys_only_and_case_encoded_keys(self):
        for name in ['fbclid','gclid','dclid','msclkid','gbraid','wbraid',
                     'utm_source','utm_medium','utm_campaign','utm_term','utm_content',
                     'FBCLID','%66bclid']:
            with self.subTest(name=name):
                self.assertEqual(normalize_application_link('https://forms.gle/synthetic?'+name+'=x'),
                                 'https://forms.gle/synthetic')
        self.assertEqual(normalize_application_link(TRACKED),BASE)

    def test_required_query_encoding_order_duplicates_empty_and_fragment_preserved(self):
        original='https://example.invalid/form?entry.1=a%2fb+z&id=abc&id=def&blank=&utm_source=social&prefill=A%26B%3DC&ref=form&source=app#section?fbclid=keep'
        expected=original.replace('&utm_source=social','')
        self.assertEqual(normalize_application_link(original),expected)
        for query in ['utm_required=1','source=mail','campaign_id=33','code=abc','key=public-form-id',
                      'redirect=https%3A%2F%2Fexample.invalid%2Freturn%3Ffbclid%3Dx',
                      'entry.1=fbclid%3Dx','utm_source_extra=business-field']:
            value='https://example.invalid/form?'+query
            self.assertEqual(normalize_application_link(value),value)
        self.assertEqual(normalize_application_link('https://example.invalid/form?'),
                         'https://example.invalid/form?')

    def test_signed_and_invalid_urls_remain_opaque(self):
        for key in ['sig','signature','hmac','X-Amz-Signature','X-Goog-Signature','%73ig']:
            value='https://example.invalid/form?fbclid=x&'+key+'=abc'
            self.assertEqual(normalize_application_link(value),value)
        for value in ['mailto:user@example.invalid?fbclid=x','javascript:alert(1)',
                      'https://[invalid?fbclid=x','https://user:pass@example.invalid/?fbclid=x',
                      'https://example.invalid/\nform?fbclid=x']:
            self.assertEqual(normalize_application_link(value),value)
        self.assertIsNone(safe_application_link('https://example.invalid/?token=secret&fbclid=x','신청'))
        self.assertIsNone(safe_application_link('https://example.invalid/poster.png?fbclid=x','신청'))

    def test_stable_dedup_idempotence_and_distinct_applications(self):
        changed=BASE.replace('entry.123=a%2Bb','entry.123=different')
        values=[TRACKED,OTHER,BASE,changed,TRACKED]
        original=copy.deepcopy(values)
        clean=normalize_application_links(values)
        self.assertEqual(clean,[BASE,changed])
        self.assertEqual(normalize_application_links(clean),clean)
        self.assertEqual(values,original)
        self.assertEqual(normalize_application_links([]),[])
        signed=['https://example.invalid/?fbclid=a&sig=s','https://example.invalid/?fbclid=b&sig=s']
        self.assertEqual(normalize_application_links(signed),signed)

    def test_complete_known_links_only_in_text_and_markdown(self):
        text=f'신청: [{TRACKED}]({TRACKED})\n{OTHER}\nhttps://unrelated.invalid/?fbclid=keep\n{TRACKED}&entry.9=another'
        expected=f'신청: [{BASE}]({BASE})\n{BASE}\nhttps://unrelated.invalid/?fbclid=keep\n{TRACKED}&entry.9=another'
        self.assertEqual(normalize_application_link_text(text,[TRACKED,OTHER]),expected)
        self.assertEqual(normalize_application_link_text(expected,[TRACKED,OTHER]),expected)
        self.assertEqual(normalize_application_link_text(text,[BASE]),expected)
        literal='https://example.invalid/form?entry.1=literal)'
        self.assertEqual(normalize_application_link_text(literal,[literal]),literal)

    def test_collected_href_normalization_and_dedup(self):
        links=''.join(f'<a href="{value.replace("&","&amp;")}">신청 폼</a>' for value in [TRACKED,OTHER])
        record=normalize_detail(observed_detail(extra=links),url())
        self.assertEqual(record.normalized_payload['application_links'],[BASE])

    def test_read_only_fact_view_and_operator_provenance(self):
        c=synthetic_context();f=c['facts']
        f['application_links']=[TRACKED,OTHER]
        f['application_methods']=['온라인 '+TRACKED]
        f['description']+='\n신청: '+TRACKED
        c['observedFacts']=copy.deepcopy(f);before=copy.deepcopy(c)
        view=application_link_facts_view(f)
        self.assertEqual(view['application_links'],[BASE])
        self.assertIn(BASE,view['description']);self.assertNotIn('fbclid',view['description'])
        packet=json.loads(myseoul_input(c))
        self.assertEqual(packet['currentFacts']['application_links'],[BASE])
        self.assertEqual(packet['operatorSupplementedFields'],[])
        self.assertEqual(c,before)
        self.assertEqual(fact_sections(f)['[신청 방법]'].count('entry.123'),2)
        self.assertNotIn('fbclid',fact_sections(f)['[신청 방법]'])

    def test_native_fake_pro_translation_and_fenced_candidate(self):
        c=synthetic_context();raw='https://synthetic.invalid/apply?id=1&fbclid=one'
        c['facts']['application_links']=[raw,raw.replace('one','two')]
        c['observedFacts']=copy.deepcopy(c['facts']);before=copy.deepcopy(c)
        _,result,calls,client,candidates=run_fixture(fixture_context=c)
        self.assertEqual(result.completed,1);self.assertEqual(len(client.calls),2)
        self.assertEqual(len(candidates),1);self.assertEqual(c,before)
        body=candidates[0]['contentKo']
        self.assertEqual(body.count('https://synthetic.invalid/apply?id=1'),1)
        self.assertNotIn('fbclid',body);self.assertNotIn('fbclid',client.calls[0]['input'][0]['content'])
        self.assertEqual(client.calls[1]['input'][0]['content'],f"title_ko: {c['title']}\ncontent_ko:\n{body}")
        for parameter,key in [('p_revision','revision'),('p_facts_version','factsVersion'),('p_claimed_at','claimedAt'),('p_lease_until','leaseUntil')]:
            self.assertEqual(calls[-1][1][parameter],c[key])

    def test_required_prefill_and_fragment_reach_fake_candidate_and_translation(self):
        c=synthetic_context();c['facts']['application_links']=[TRACKED,OTHER]
        c['observedFacts']=copy.deepcopy(c['facts']);before=copy.deepcopy(c)
        fake_ja=JA.replace('https://synthetic.invalid/apply?id=1',BASE)
        _,result,calls,client,candidates=run_fixture(fixture_context=c,ja=fake_ja)
        self.assertEqual(result.completed,1);self.assertEqual(c,before)
        self.assertIn(BASE,candidates[0]['contentKo']);self.assertIn(BASE,candidates[0]['contentJa'])
        self.assertIn(BASE,client.calls[1]['input'][0]['content'])
        self.assertNotIn('fbclid',candidates[0]['contentKo'])
        self.assertEqual(len(client.calls),2);self.assertEqual(len(candidates),1)

    def test_schedule_or_fee_conflict_still_stops_candidate_without_retry(self):
        c=synthetic_context();c['facts']['application_links']=[TRACKED,OTHER]
        for summary in [KO.replace('14:00~15:30','10:00~11:30'),KO+'\n수강료는 20,000원입니다.']:
            with self.subTest(summary=summary):
                _,result,calls,client,candidates=run_fixture(fixture_context=c,ko=summary)
                self.assertEqual(result.failed,1);self.assertEqual(len(client.calls),1)
                self.assertEqual(candidates,[])
                self.assertFalse(any(name.startswith('finish_') for name,_ in calls))

    def test_reclassified_fake_candidate_and_other_sources_unchanged(self):
        c=classified_context('program');native=c['nativeConfirmedFacts']['programFacts']
        native.update(application_links=[TRACKED,OTHER],description='신청 '+TRACKED)
        c['body']+='\n신청 '+OTHER;before=copy.deepcopy(c)
        inputs=[];translations=[];events=[]
        def rpc(name,args):
            events.append((name,copy.deepcopy(args)))
            if name=='claim_reclassified_content_ai':return c
            if name=='finish_reclassified_content_ai':return {'candidateId':CLASSIFIED_ID,'outcome':'inserted'}
            raise AssertionError(name)
        def ko(body,url,*,title):
            inputs.append(json.loads(body))
            return '[한 줄 요약]\n합성 안내\n[주요 내용]\n합성 본문','success','fake'
        def ja(title,body):
            translations.append(body)
            return '合成案内','[要約]\n合成案内\n[主な内容]\n保護者同伴。 '+ ' '.join(re.findall(r'\d[\d,]*',body))+'\n'+BASE,'success','fake'
        result=process_reclassified_job(ProgramAIAdapter(rpc),source_item_id=CLASSIFIED_ID,
            revision=REV,classification_version=1,worker_id='synthetic-worker',summarize_ko=ko,translate_ja=ja)
        self.assertEqual(result.completed,1);self.assertEqual(c,before)
        self.assertEqual(len(inputs),1);self.assertEqual(len(translations),1)
        self.assertEqual(inputs[0]['nativeConfirmedFacts']['programFacts']['application_links'],[BASE])
        self.assertNotIn('fbclid',inputs[0]['sourceText']);self.assertNotIn('fbclid',translations[0])
        self.assertEqual(translations[0].count(BASE),1)
        self.assertEqual(events[-1][1]['p_revision'],REV)
        self.assertEqual(events[-1][1]['p_classification_version'],1)
        self.assertEqual(events[-1][1]['p_output']['contentKo'],translations[0])
        c['source']='seoul_reservation'
        self.assertEqual(json.loads(classification_input(c))['nativeConfirmedFacts'],c['nativeConfirmedFacts'])
        self.assertNotIn('신청 링크:',protected_information(c))


if __name__=='__main__':unittest.main()
