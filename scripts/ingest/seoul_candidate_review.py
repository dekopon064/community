"""Collect advisory Seoul checks and prepare a private, operator-reviewed patch."""
import json
import re

from ingest.ai_errors import AiJobError, ValidationError
from ingest.ai_worker import extract_summary_section, KO_SECTION_HEADERS, JA_SECTION_HEADERS, KO_SUMMARY_HEADER, JA_SUMMARY_HEADER
from ingest.body_markdown import read_body, require_plain_summary

MAX_ISSUES = 32


class SeoulCandidateReview:
    def __init__(self, suggest):
        self.suggest = suggest
        self.issues = []
        self.stage = 'korean_validation'

    @classmethod
    def for_translation(cls, translate):
        suggest = getattr(getattr(translate, '__self__', None), 'suggest_seoul_review', None)
        return cls(suggest) if callable(suggest) else None

    def record(self, error):
        issue = {'stage': self.stage, **error.diagnostic}
        if issue not in self.issues and len(self.issues) < MAX_ISSUES:
            self.issues.append(issue)

    def check(self, validate, *args, **kwargs):
        try:
            validate(*args, **kwargs)
        except ValidationError as error:
            self.record(error)

    def check_japanese(self, title, korean, title_ja, japanese):
        from ingest.region_ja_glossary import validate_japanese_output
        from ingest.seoul_public_guidance import validate_public_guidance
        from ingest.translation_validation import validate_translation_fidelity

        self.stage = 'japanese_validation'
        self.check(validate_public_guidance, japanese, 'ja')
        self.check(validate_japanese_output, title_ja, japanese, korean_source=title + '\n' + korean)
        validate_translation_fidelity(title, korean, title_ja, japanese, report=self.record)

    def prepare(self, output, facts):
        from ingest.seoul_content import source_description

        # The provider receives only candidate fields and public source prose.
        # Stored review notes and credentials never enter this request.
        source = source_description(facts['description'])[:32_000] if self.issues else ''
        return self.propose(output, source) if self.issues else None

    @staticmethod
    def finish(adapter, fence, output, review, *, mode, input_version):
        if review is None:
            args = {'p_facts_version': input_version} if mode == 'program' else {
                'p_classification_version': input_version}
            name = 'finish_seoul_program_ai' if mode == 'program' else 'finish_reclassified_content_ai'
            return adapter.invoke(name, {**fence, **args, 'p_output': output})

        return adapter.invoke('finish_seoul_ai_candidate_review', {**fence, 'p_mode': mode,
            'p_input_version': input_version, 'p_output': output, 'p_review': review})

    def propose(self, output, source):
        self.stage = 'correction'
        # Every diagnostic has a disposition even when no supported edit is returned.
        review = {'source': source, 'issues': [dict(issue, disposition='needs_review') for issue in self.issues]}
        try:
            payload = self.suggest(output=output, source=source, issues=self.issues)
        except AiJobError as error:
            if error.code not in {'ai_refusal', 'ai_unexpected_thinking'} or getattr(error, 'failure_scope', None) == 'batch':
                raise
            return review
        if not isinstance(payload, dict) or set(payload) != {'findings'} or not isinstance(payload['findings'], list):
            return review

        # Duplicate or overlapping suggestions are ambiguous. Keep the original
        # text and let the reviewer decide how to reconcile them.
        seen = set()
        patches = []
        for row in payload['findings'][:MAX_ISSUES]:
            if not isinstance(row, dict):
                continue
            index = row.get('issue')
            if type(index) is not int or not 1 <= index <= len(self.issues):
                continue
            if index in seen:
                return review
            seen.add(index)
            issue = review['issues'][index - 1]
            evidence = row.get('evidence')
            if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 500 or evidence not in source:
                continue
            if row.get('decision') == 'equivalent':
                patches.append((issue, {'disposition': 'equivalent', 'evidence': evidence}))
                continue
            if row.get('decision') != 'change':
                continue
            patch = self.patch(row, issue, output, evidence)
            if patch:
                patches.append((issue, patch))

        for issue, patch in patches:
            if patch['disposition'] == 'change' and any(
                other is not patch and other.get('field') == patch['field']
                and other['start'] < patch['end'] and patch['start'] < other['end']
                for _, other in patches
            ):
                continue
            issue.update({key: value for key, value in patch.items() if key not in {'start', 'end'}})
        return review

    @staticmethod
    def patch(row, issue, output, evidence):
        field, before, after = (row.get(key) for key in ('field', 'before', 'after'))
        fields = {'contentKo'} if issue['stage'] == 'korean_validation' else {'contentJa', 'titleJa'}
        location = issue.get('location', {}).get('field')
        if location in {'title', 'title_ja'}:
            fields &= {'titleJa'}
        elif location in {'body', 'content_ja'}:
            fields &= {'contentJa'}
        if not isinstance(field, str) or field not in fields:
            return None
        if not all(isinstance(value, str) and 0 < len(value) <= 500
                   and value == value.strip() and all(char.isprintable() for char in value)
                   for value in (before, after)) or before == after:
            return None
        text = output[field]
        start = text.find(before)
        if start < 0 or text.find(before, start + 1) >= 0:
            return None
        if re.findall(r'https?://[^\s)]+', before) != re.findall(r'https?://[^\s)]+', after):
            return None
        end = start + len(before)
        amended = text[:start] + after + text[end:]
        summary_patch = False
        try:
            if field == 'titleJa':
                require_plain_summary(amended)
                if len(amended) > 300:
                    return None
            else:
                read_body(amended)
                header, headers = (KO_SUMMARY_HEADER, KO_SECTION_HEADERS) if field == 'contentKo' else (
                    JA_SUMMARY_HEADER, JA_SECTION_HEADERS)
                # Protect the editor's required one-line summary and its boundaries.
                summary_patch = extract_summary_section(amended, header, headers) != extract_summary_section(text, header, headers)
                summary = output['summaryKo' if field == 'contentKo' else 'summaryJa']
                if summary_patch and (before not in summary or summary.count(before) != 1):
                    return None
                if len(amended) > 200_000:
                    return None
                if re.findall(r'(?m)^\s*\[[^\]\n]+\]', text) != re.findall(r'(?m)^\s*\[[^\]\n]+\]', amended):
                    return None
        except ValidationError:
            return None
        return {'disposition': 'change', 'field': field, 'before': before, 'after': after,
                'evidence': evidence, 'start': start, 'end': end, 'summaryPatch': summary_patch}


def correction_prompt(output, source, issues):
    return json.dumps({'candidate': output, 'officialSource': source,
        'issues': [dict(issue, issue=index) for index, issue in enumerate(issues, 1)]}, ensure_ascii=False)
