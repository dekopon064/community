"""Synthetic classification, human-approved publication plans and fake worker/RPC."""
import copy
import json
import socket
import unittest
from unittest.mock import patch
from uuid import UUID
from ingest.content_filters import empty_filters,field,validate_filters,missing_filters,extract_filter_facts,validate_claim_filter
from ingest.foreigner_program_plan import publication_plan
from ingest.myseoul_ai import process_myseoul_job
from ingest.program_ai import ProgramAIAdapter,process_seoul_program_job
from test_content_filter_python import ready,ctx,bind_filters
from test_myseoul_ai import context as my_context,providers as my_providers
from test_program_ai import context as seoul_context,providers as seoul_providers
import test_reclassification_ai as re_tests

class ForeignerFilterTests(unittest.TestCase):
 def setUp(self):
  self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('network_forbidden'));self.network.start();self.addCleanup(self.network.stop)
 def test_legacy_unknown_and_other_are_distinct_without_mutation(self):
  d=ready();d.pop('foreignerProgram');before=copy.deepcopy(d)
  self.assertEqual(validate_filters(d)['foreignerProgram'],field());self.assertEqual(d,before)
  for value in ('foreigner','other'):
   selected={**d,'foreignerProgram':field(value)}
   self.assertEqual(validate_filters(selected),selected)
   self.assertEqual(missing_filters(selected),missing_filters(d))
  self.assertEqual(missing_filters(ready()),[])
 def test_invalid_values_and_category_stay_blocked(self):
  for invalid in (field('eligible'),field(status='not_applicable'),{'status':'unknown','value':'other'},{'status':'known','value':True}):
   with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate_filters({**ready(),'foreignerProgram':invalid})
  with self.assertRaises(ValueError):validate_filters({**ready('event'),'foreignerProgram':field('foreigner')})
 def test_extraction_does_not_infer_from_source_title_or_nationality_text(self):
  for source,key in (('myseoul_program','description'),('seoul_reservation','program_text')):
   for text in ('외국인만 참가할 수 있는 체험','내·외국인 문화 수업','성인, 가족, 청년'):
    packet=extract_filter_facts(source,{key:text},{'public_category':'program'})
    self.assertEqual(packet['data']['foreignerProgram'],field());self.assertNotIn('foreignerProgram',packet['evidence'])
 def test_claim_preserves_known_decision_and_fence(self):
  c=ctx();c['data']['foreignerProgram']=field('foreigner');before=copy.deepcopy(c)
  self.assertEqual(validate_claim_filter(c,worker=c['workerId']),c);self.assertEqual(c,before)
  with self.assertRaises(ValueError):validate_claim_filter(c,worker='wrong')
 def test_general_workers_keep_snapshot_and_do_not_append_classification(self):
  for source in ('my','seoul'):
   for value in (None,'foreigner','other'):
    c=bind_filters(my_context() if source=='my' else seoul_context());c['filterContext']['data']['foreignerProgram']=field(value)
    before=copy.deepcopy(c);base_ko,base_ja=(my_providers(c) if source=='my' else seoul_providers(c)[:2]);counts={'ko':0,'ja':0};events=[]
    def ko(*args,**kwargs):counts['ko']+=1;return base_ko(*args,**kwargs)
    def ja(title,body):
     counts['ja']+=1;self.assertNotIn('외국인 프로그램 구분',body);return base_ja(title,body)
    def rpc(name,args):
     events.append((name,copy.deepcopy(args)))
     return [copy.deepcopy(c)] if name.startswith('claim_') else {'candidateId':str(UUID(int=2,version=4)),'outcome':'inserted'}
    fn=process_myseoul_job if source=='my' else process_seoul_program_job
    result=fn(ProgramAIAdapter(rpc),source_item_id=c['sourceItemId'],revision=c['revision'],summarize_ko=ko,translate_ja=ja)
    self.assertEqual(result.completed,1,(source,value,result));self.assertEqual(counts,{'ko':1,'ja':1});self.assertEqual(len(events),2)
    self.assertEqual(c,before);self.assertEqual(events[-1][1]['p_job_id'],c['jobId'])
    self.assertEqual(events[-1][1]['p_revision'],c['revision'])
 def test_reclassification_workers_pass_current_operator_value(self):
  runner=re_tests.ClassificationAITests('runTest')
  for source in ('myseoul_program','seoul_reservation'):
   c=re_tests.context('program',source);c['filters']['foreignerProgram']=field('foreigner');before=copy.deepcopy(c)
   result,events,inputs=runner.run_job(c)
   self.assertEqual(result.completed,1);self.assertEqual(inputs[0]['currentFilters']['foreignerProgram'],field('foreigner'))
   self.assertEqual(len(events),2);self.assertEqual(c,before)
  legacy=re_tests.context('program');legacy['filters'].pop('foreignerProgram');before=copy.deepcopy(legacy)
  self.assertEqual(runner.run_job(legacy)[0].completed,1);self.assertEqual(legacy,before)

def publication(index=1,**patches):
 return {'id':str(UUID(int=index,version=4)),'sourceItemId':str(UUID(int=index+100,version=4)),'title':'합성 게시글 '+str(index),
  'source':'myseoul_program','publishedAt':'2026-10-05T00:00:00+09:00','category':'program','revision':'a'*64,'version':'b'*64,'filterVersion':2,'contentFilters':ready(),**patches}

class PublicationPlanTests(unittest.TestCase):
 def plan(self,items):return publication_plan(items,first_day='2026-10-05',last_day='2026-10-11')
 def test_inclusive_kst_boundaries_and_source_selection(self):
  rows=[publication(),publication(2,publishedAt='2026-10-11T23:59:59.999999+09:00'),publication(3,publishedAt='2026-10-12T00:00:00+09:00'),publication(4,publishedAt='2026-10-04T23:59:59+09:00'),publication(5,source='seoul_reservation'),publication(6,publishedAt='2026-10-04T15:00:00Z')]
  before=copy.deepcopy(rows);plan=self.plan(rows)
  self.assertEqual([x['id'] for x in plan['updates']],[rows[i]['id'] for i in (0,1,5)]);self.assertEqual(len(plan['skipped']),3);self.assertEqual(rows,before)
  for item in plan['updates']:
   self.assertEqual(item['patch'],{'foreignerProgram':field('foreigner')});self.assertEqual(item['filterVersion'],2);self.assertEqual(item['basis'],'operator_confirmed_cohort')
 def test_no_reassessment_or_automatic_overwrite_of_existing_decision(self):
  rows=[publication(1,contentFilters={**ready(),'foreignerProgram':field('foreigner')}),publication(2,contentFilters={**ready(),'foreignerProgram':field('other')})]
  plan=self.plan(rows);self.assertEqual(len(plan['already_classified']),1);self.assertEqual(len(plan['conflicts']),1);self.assertEqual(plan['updates'],[])
 def test_missing_publication_dates_are_not_replaced_by_source_dates(self):
  row=publication();row.pop('publishedAt');row['sourceCreatedAt']='2026-10-06T12:00:00+09:00'
  self.assertEqual(len(self.plan([row])['unverified']),1)
  for patches in ({'publishedAt':'2026-10-06'},{'version':'bad'},{'filterVersion':True},{'contentFilters':None},{'category':'event'}):
   self.assertEqual(len(self.plan([publication(**patches)])['unverified']),1)
 def test_repeated_plan_does_not_change_snapshots_or_create_duplicates(self):
  row=publication();first=self.plan([row]);self.assertEqual(first,self.plan([row]));self.assertEqual(len(first['updates']),1)
  row['contentFilters']['foreignerProgram']=field('foreigner')
  self.assertEqual(self.plan([row])['updates'],[])

if __name__=='__main__':unittest.main()
