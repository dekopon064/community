"""Protected server review fallback, fake RPC/provider only; no env/network."""
import copy,json,unittest
from datetime import datetime
from unittest.mock import Mock
from test_myseoul_ai import context,providers
from ingest.myseoul_ai import validate_context,myseoul_input,generate_myseoul_output
from ingest.myseoul_db import evaluate_myseoul_facts
from ingest.ai_errors import AiJobError

class ResidenceAITests(unittest.TestCase):
 def fixture(self):
  c=context();f=c['facts'];f.update(delivery_mode='online',residence_scope='unknown',residence='',residence_evidence=[])
  local=evaluate_myseoul_facts(f,now=datetime.now().astimezone());self.assertIn('online_residence_unknown',local['reasons'])
  result={**local,'scope':'included','quality':'sufficient','decision':'in_scope','disposition':'target','reasons':[r for r in local['reasons'] if r!='online_residence_unknown']}
  d={'id':c['sourceItemId'],'revision':c['revision'],'schema':c['schema'],'profile':c['profile'],'factsVersion':c['factsVersion'],'source':{'name':c['source'],'title':c['title'],'url':f['official_url']},'facts':copy.deepcopy(f),'observedFacts':copy.deepcopy(c['observedFacts']),'result':result,'status':'resolved','aiStatus':'claimed'}
  return c,d
 def test_exact_server_judgment_required(self):
  c,d=self.fixture()
  with self.assertRaises(AiJobError):validate_context(c,c['sourceItemId'],c['revision'],c['workerId'])
  read=Mock(return_value=d);self.assertIs(validate_context(c,c['sourceItemId'],c['revision'],c['workerId'],read_detail=read),c);read.assert_called_once_with(c['sourceItemId'])
 def test_stale_or_unresolved_server_cannot_override(self):
  c,d=self.fixture()
  for patch in [{'factsVersion':999},{'revision':'f'*64},{'status':'open'},{'aiStatus':'queued'},{'result':evaluate_myseoul_facts(c['facts'],now=datetime.now().astimezone())},{'facts':{**c['facts'],'target':'changed'}}]:
   with self.subTest(patch=patch),self.assertRaises(AiJobError):validate_context(c,c['sourceItemId'],c['revision'],c['workerId'],read_detail=Mock(return_value={**d,**patch}))
 def test_other_missing_reason_still_blocks(self):
  c,d=self.fixture();c['facts']['target']=''
  read=Mock(return_value=d)
  with self.assertRaises(AiJobError):validate_context(c,c['sourceItemId'],c['revision'],c['workerId'],read_detail=read)
  read.assert_not_called()
 def test_confirmed_region_requires_exact_fresh_server_snapshot(self):
  c,d=self.fixture();c['facts'].update(delivery_mode='offline',activity_region='capital',venue='',activity_evidence=[])
  local=evaluate_myseoul_facts(c['facts'],now=datetime.now().astimezone());self.assertEqual(local['reasons'],['activity_region_unknown'])
  d.update(facts=copy.deepcopy(c['facts']),result={**local,'scope':'included','quality':'sufficient','decision':'in_scope','disposition':'target','reasons':[]})
  self.assertIs(validate_context(c,c['sourceItemId'],c['revision'],c['workerId'],read_detail=Mock(return_value=d)),c)
  body=json.loads(myseoul_input(c));self.assertEqual(body['currentFacts']['venue'],'');self.assertEqual(c['facts']['activity_evidence'],[])
  for patch in [{'factsVersion':999},{'status':'open'},{'result':local},{'facts':{**c['facts'],'activity_region':'unknown'}}]:
   with self.subTest(patch=patch),self.assertRaises(AiJobError):validate_context(c,c['sourceItemId'],c['revision'],c['workerId'],read_detail=Mock(return_value={**d,**patch}))
 def test_provider_keeps_source_truth_and_no_internal_judgment(self):
  c,d=self.fixture();validate_context(c,c['sourceItemId'],c['revision'],c['workerId'],read_detail=Mock(return_value=d))
  before=copy.deepcopy(c);body=json.loads(myseoul_input(c));self.assertEqual(body['currentFacts']['residence_scope'],'unknown');self.assertNotIn('residenceReview',body);self.assertNotIn('actor',body)
  ko,ja=providers(c);ko=Mock(side_effect=ko);ja=Mock(side_effect=ja);generate_myseoul_output(c,summarize_ko=ko,translate_ja=ja);self.assertEqual(c,before);self.assertEqual(ko.call_count,1);self.assertEqual(ja.call_count,1)

if __name__=='__main__':unittest.main()
