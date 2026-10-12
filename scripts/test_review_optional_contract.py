"""Optional quotes are not missing facts; synthetic only, sockets forbidden."""
import copy,json,socket
from datetime import datetime
from dataclasses import fields
from unittest.mock import patch
from ingest.program_scope import ProgramFacts,assess_program_facts
from test_seoul_content import synthetic_facts
from test_program_ai import context,ProgramAITests
from test_reclassification_ai import context as classified_context,ClassificationAITests
from ingest.program_ai import program_input
from ingest.reclassification_ai import classification_input

f=synthetic_facts();f['residence_scope']='unknown';f['residence_evidence']=[]
f['missing']=[];f['conflicts']=[]
def assess(data):
 return assess_program_facts(ProgramFacts(**{x.name:data[x.name] for x in fields(ProgramFacts)}),data['periods'],now=datetime.fromisoformat('2026-10-12T10:00:00+09:00'))
checks=[]
def ok(v,label):assert v,label;checks.append(label)
with patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden')):
 assert 'residence_scope_unknown' not in assess(f).reason_codes,'offline unknown residence must not require a quote'
 checks.append('offline unknown residence does not need quote')
 for mode in ('offline','hybrid'):
  for scope in ('unknown','not_stated','capital','nationwide'):
   v={**f,'delivery_mode':mode,'residence_scope':scope,'activity_evidence':[]}
   r=assess(v);ok('residence_scope_unknown' not in r.reason_codes and 'activity_location_unknown' not in r.reason_codes,mode+' '+scope+' without quote')
 for scope in ('unknown','not_stated'):
  r=assess({**f,'delivery_mode':'online','activity_region':'not_applicable','residence_scope':scope});ok('residence_scope_unknown' in r.reason_codes,'online range unknown remains blocked')
 for scope in ('capital','nationwide','includes_capital'):
  r=assess({**f,'delivery_mode':'online','activity_region':'not_applicable','residence_scope':scope});ok('residence_scope_unknown' not in r.reason_codes,'known online range '+scope+' needs no quote')
 for field,value,reason in [('residence_scope','noncapital','residence_outside_capital'),('application_actor','nationality_excluded','nationality_explicitly_excluded'),('conflicts',['fee_conflict'],'fee_conflict')]:
  r=assess({**f,field:value});ok(reason in r.reason_codes,'actual restriction/conflict '+reason)
 c=context();c['facts'].update(residence_scope='unknown',residence_evidence=[],activity_evidence=[]);c['auditNote']='INTERNAL_MEMO_MUST_NOT_LEAK'
 result,events,inputs=ProgramAITests().run_job(c)
 ok(result.completed==1 and result.claimed==1,'general worker completes fake candidate without quotes')
 ok(len(inputs)==1 and [n for n,_ in events]==['claim_seoul_program_ai','finish_seoul_program_ai'],'one summary and one fake finish, no retry')
 ok('INTERNAL_MEMO_MUST_NOT_LEAK' not in program_input(c) and 'INTERNAL_MEMO_MUST_NOT_LEAK' not in json.dumps(events),'audit note absent from AI input and candidate')
 cc=classified_context('program','seoul_reservation');cc['facts']['evidence']='';cc['auditNote']='INTERNAL_MEMO_MUST_NOT_LEAK'
 harness=ClassificationAITests();harness.setUp()
 try:
  result,events,calls=harness.run_job(cc)
  ok(result.completed==1,'reclassification worker fake candidate with no quote')
  ok('INTERNAL_MEMO_MUST_NOT_LEAK' not in classification_input(cc),'classification history note not AI input')
 finally:harness.doCleanups()
print(json.dumps({'checks':len(checks),'result':'passed','syntheticOnly':True,'networkCalls':0}))
