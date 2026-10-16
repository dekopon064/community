"""Private JSON-lines bridge: common Pro auth, search/read, proposals; no DB."""
from __future__ import annotations
import json
import sys

from ingest.ai_provider import require_ai_provider, create_location_research_adapter
from ingest.location_plan_research import ResearchFailure
from ingest.chatgpt_plan_protocol import ProbeError


def serve(source, sink, *, factory=None):
    adapter = None

    def reply(value):
        sink.write(json.dumps(value,ensure_ascii=False)+'\n')
        sink.flush()

    def stats():
        return {'requests':adapter.calls,'officialReads':adapter.reads,
                'usage':adapter.usage,'usageUnknownCount':adapter.calls-len(adapter.usage)}

    try:
        while True:
            line = source.readline(256_001)
            if not line:
                break
            if len(line)>256_000 or not line.endswith('\n'):
                reply({'ok':False,'code':'research_protocol_invalid'})
                break
            try:
                message = json.loads(line)
                if not isinstance(message,dict):
                    raise ValueError()
                if message.get('action') == 'close':
                    reply({'ok':True})
                    break
                if message.get('action') == 'ready':
                    if adapter is not None or set(message) != {'action','limit','choices','instructions'}:
                        raise ValueError()
                    limit, choices, instructions = message['limit'],message['choices'],message['instructions']
                    if (type(limit) is not int or not 1<=limit<=25 or not isinstance(choices,dict) or
                            set(choices) != {'11','41','28'} or
                            any(not isinstance(v,list) or not v or len(v)>100 or any(not isinstance(d,str) or not 1<=len(d)<=40 for d in v) for v in choices.values()) or
                            not isinstance(instructions,str) or not 1<=len(instructions)<=10000):
                        raise ValueError()
                    # This reads AI_PROVIDER only. Actual credentials are accessed
                    # solely by the shared authentication factory on explicit ready.
                    provider = require_ai_provider()
                    adapter = (factory or create_location_research_adapter)(provider,
                        choices=choices,instructions=instructions,limit=limit)
                    reply({'ok':True})
                elif message.get('action') == 'investigate':
                    if adapter is None or set(message) != {'action','item'}:
                        raise ValueError()
                    item = message['item']
                    if (not isinstance(item,dict) or not isinstance(item.get('title'),str) or
                            not isinstance(item.get('description'),str) or len(item['title'])>500 or
                            not 1<=len(item['description'])<=60000):
                        raise ValueError()
                    answer = adapter.investigate(item)
                    reply({'ok':True,'answer':answer,'stats':stats()})
                else:
                    raise ValueError()
            except (ResearchFailure,ProbeError) as error:
                # Exception text/URLs/headers/credentials are never IPC output.
                allowed={'research_call_budget','research_auth_required','research_usage_unknown',
                    'research_output_or_tool_bound','research_response_unknown','official_read_unavailable',
                    'subscription_sharing_unsupported_capability','subscription_sharing_route_not_supported',
                    'subscription_sharing_usage_limit_exceeded','subscription_sharing_usage_unavailable',
                    'subscription_sharing_user_not_eligible','chatgpt_plan_reauthentication_required',
                    'chatgpt_plan_permission_missing','plan_refresh_result_unknown',
                    'plan_http_400','plan_http_401','plan_http_403','plan_http_404','plan_http_429'}
                reply({'ok':False,'code':error.code if error.code in allowed else 'research_runtime_stopped',
                       **({'stats':stats()} if adapter is not None else {})})
                break
            except Exception:
                reply({'ok':False,'code':'research_runtime_stopped',**({'stats':stats()} if adapter is not None else {})})
                break
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass


if __name__ == '__main__':
    if sys.argv[1:] != ['--worker']:
        print('별도 조사 launcher의 명시적 --execute 경로에서만 사용합니다. 인증·검색·GPT·DB 작업을 시작하지 않았습니다.')
    else:
        serve(sys.stdin,sys.stdout)
