"""Isolated SIWC probe: OAuth in memory, synthetic input, no DB or paid API fallback.

This module is not registered as a product provider or worker. Only non-secret
host/client registration metadata survives a run; credentials never go to disk.
"""
from __future__ import annotations

import copy
import json

from ingest.ai_claude import (MYSEOUL_SUMMARY_SYSTEM, SUMMARY_SCHEMA,
    TRANSLATION_SCHEMA, translation_system_prompt, validate_summary_payload,
    validate_translation_payload)
from ingest.ai_openai import GPT_MODEL
from ingest.ai_errors import AiJobError
from ingest.region_ja_glossary import validate_japanese_output
from ingest.translation_validation import validate_translation_fidelity

from ingest.chatgpt_plan_protocol import (ISSUER, DISCOVERY, AUTHORIZE, TOKEN, JWKS,
    RESOURCE, SCOPES, APP_NAME, ProbeError, AuthorizationAttempt, validate_discovery,
    verify_grant, model_available, read_completed_stream)

class DiagnosticClient:
    """Memory-only completed response replay; explicit operator runs, no retries."""
    max_retries = 0

    def __init__(self, client):
        self.client, self.cache, self.network_calls = client, {}, 0
        self.attempted = set()
        self.responses = self

    def create(self, **request):
        key = json.dumps(request, sort_keys=True, ensure_ascii=False)
        owner = self
        class Stream:
            def __enter__(self):
                if key in owner.cache:
                    return iter(owner.cache[key])
                if key in owner.attempted:
                    raise ProbeError('diagnostic_response_not_completed')
                if owner.network_calls >= 2:
                    raise ProbeError('diagnostic_generation_limit')
                owner.attempted.add(key)
                owner.network_calls += 1
                self.live = owner.client.responses.create(**request)
                def events():
                    received = []
                    for event in self.live.__enter__():
                        received.append(event)
                        yield event
                    if (sum(get_field(e,'type') == 'response.completed' for e in received) == 1
                            and not any(get_field(e,'type') in {'error','response.failed','response.incomplete'} for e in received)):
                        owner.cache[key] = received
                return events()
            def __exit__(self, *args):
                if hasattr(self,'live'):
                    return self.live.__exit__(*args)
        return Stream()


def probe_request(stage, user):
    schema = copy.deepcopy(SUMMARY_SCHEMA if stage == 'summary' else TRANSLATION_SCHEMA)
    schema.pop('$schema', None); schema.pop('$id', None)
    return dict(model=GPT_MODEL,
        instructions=MYSEOUL_SUMMARY_SYSTEM if stage == 'summary' else translation_system_prompt(),
        input=[{'role':'user','content':user}], store=False, stream=True,
        reasoning={'effort':'low'},
        text={'format':{'type':'json_schema','name':'machimoa_'+stage,'strict':True,'schema':schema}})


def get_field(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


class ChatGPTPlanProbe:
    def __init__(self, client):
        if getattr(client, 'max_retries', None) != 0:
            raise ProbeError('sdk_retry_forbidden')
        self.client, self.calls, self.usage = client, 0, []
        self.stage = 'not_started'
        self.validated_payloads = {}
        self.diagnostic_responses = {}
        self.stream_events = {}
        self.summary_done = False
        self.translation_attempted = False

    def create(self, stage, user):
        if self.calls >= 2:
            raise ProbeError('generation_call_limit')
        self.calls += 1
        self.stage = stage + '_request'
        def observe(event):
            kind = get_field(event, 'type')
            counts = self.stream_events.setdefault(stage, {})
            counts[kind] = counts.get(kind, 0) + 1

        def completed(response, items):
            self.usage.append({'stage':stage,'model':GPT_MODEL,'billing':'chatgpt_plan',
                               'usage':get_field(response,'usage')})
            self.stage = stage + '_json_validation'
            def messages(output):
                return [{'type':get_field(item,'type'),'role':get_field(item,'role'),
                    'status':get_field(item,'status'),
                    'content':[{'type':get_field(p,'type'),'text':get_field(p,'text')}
                        for p in get_field(item,'content',[])]}
                    for item in output if get_field(item,'type')!='reasoning']
            self.diagnostic_responses[stage] = {
                'status':get_field(response,'status'),
                'messages':messages(get_field(response,'output',[])),
                'terminal_messages':messages(items)}
        payload, _ = read_completed_stream(self.client, probe_request(stage, user),
                                           observe=observe, on_completed=completed)
        return payload

    def summarize_myseoul_ko(self, body, source_url, title=None):
        if self.calls:
            raise ProbeError('generation_call_limit')
        payload = self.create('summary',
            f'title: {title or ""}\nsource_url: {source_url or ""}\nbody:\n{body}')
        self.stage = 'summary_schema_validation'
        content = validate_summary_payload(payload)
        self.validated_payloads['summary'] = payload
        self.summary_done = True
        self.stage = 'korean_body_assembly_validation'
        return content,'success',GPT_MODEL

    def translate_ja(self, title, content_ko):
        if not self.summary_done or self.translation_attempted:
            raise ProbeError('translation_not_permitted')
        self.translation_attempted = True
        payload = self.create('translation',
            f'title_ko: {title}\ncontent_ko:\n{content_ko}')
        self.stage = 'translation_schema_validation'
        title_ja, content_ja = validate_translation_payload(payload)
        self.stage = 'translation_fidelity_validation'
        validate_japanese_output(title_ja, content_ja, korean_source=title+'\n'+content_ko)
        validate_translation_fidelity(title, content_ko, title_ja, content_ja)
        self.validated_payloads['translation'] = payload
        self.stage = 'candidate_body_validation'
        return title_ja,content_ja,'success',GPT_MODEL


def synthetic_context():
    def period(start,end):
        return [{'status':'ok','endpoints':[{'value':start,'precision':'day'}, {'value':end,'precision':'day'}]}]
    f=dict(target='18세 이상 외국인 주민', conditions=['성남시 주민만 신청 가능',
        'F-2 비자 소지자만 신청 가능','선착순 25명, 정원 도달 시 마감',
        '업무 효율을 173% 올려주는 교육'], age=['18세 이상'], companion=[],
        language=['영어로 진행'], residence='성남시 주민만 신청 가능', residence_scope='capital_allowed',
        qualification_note='F-2 비자 소지자만 신청 가능', venue='', delivery_mode='online',
        application_actor='individual',activity_region='capital',
        capacity_raw=['선착순 25명'], capacity_value=25,
        fees=[{'component':'tuition','evidence':['10,000원']}, {'component':'materials','evidence':['2,000원']}],
        periods={'application':period('2027-01-05','2027-01-12'),
                 'operation':period('2027-02-03','2027-02-17')},
        session_evidence=['2월 3일, 2월 10일, 2월 17일 09:30~11:00, 총 3회'], meeting_evidence=[],
        application_methods=['전화 상담 후 방문 접수'],
        application_links=['https://synthetic.invalid/apply?a=1'], official_url='https://synthetic.invalid/local-probe',
        source_status=[],early_close_evidence=[],
        description='합성 이미지 보완 설명: 디지털 사무 도구를 읽고 듣고 따라 말하며 실습합니다. 마실 물을 준비하세요.',
        public_category='program',purpose='디지털 사무 교육', source_category='program')
    observed=copy.deepcopy(f);observed['capacity_raw']=[];observed['capacity_value']=None
    observed['description']=''
    return dict(facts=f,observedFacts=observed,factsVersion=2,title='합성 디지털 사무 교육 1반')
