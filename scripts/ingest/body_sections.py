"""Canonical generated headings; read legacy headings without changing prose."""
from __future__ import annotations

import re
from ingest.ai_errors import AiJobError

KO_SCHEDULE_HEADER = '[일정 안내]'
JA_SCHEDULE_HEADER = '[日程案内]'
KO_SECTION_HEADERS = ('[한 줄 요약]', '[대상]', KO_SCHEDULE_HEADER, '[주요 내용]', '[신청 방법]')
JA_SECTION_HEADERS = ('[要約]', '[対象]', JA_SCHEDULE_HEADER, '[主な内容]', '[申請方法]')
_SCHEDULE_ALIASES = {
    'ko': {'[기간·상태]': KO_SCHEDULE_HEADER, KO_SCHEDULE_HEADER: KO_SCHEDULE_HEADER},
    'ja': {'[期間・状況]': JA_SCHEDULE_HEADER, JA_SCHEDULE_HEADER: JA_SCHEDULE_HEADER},
}


def normalize_schedule_heading(content: str, locale: str) -> str:
    """Normalize only a standalone/space-separated heading, outside code fences.

    Duplicate semantic schedule sections fail; never silently merge or discard
    one. Existing persisted bodies are not mutated by this pure function.
    """
    aliases = _SCHEDULE_ALIASES[locale]
    pattern = re.compile(r'^([ \t]*)(' + '|'.join(re.escape(h) for h in aliases) + r')(?=[ \t]|$)')
    count = 0
    fence = None
    output = []
    for line in content.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
        elif marker:
            fence = marker[1]
        else:
            match = pattern.match(line.rstrip('\r\n'))
            if match:
                count += 1
                if count > 1:
                    raise AiJobError('ai_schema_error')
                line = line[:match.start(2)] + aliases[match[2]] + line[match.end(2):]
        output.append(line)
    return ''.join(output)
