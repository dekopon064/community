"""Collect advisory program checks and prepare a private, operator-reviewed patch."""
import json
import re

from ingest.ai_errors import AiJobError, ValidationError, failure_stage
from ingest.ai_worker import extract_summary_section, KO_SECTION_HEADERS, JA_SECTION_HEADERS, KO_SUMMARY_HEADER, JA_SUMMARY_HEADER
from ingest.body_markdown import read_body, require_plain_summary

MAX_ISSUES = 32


def private_output(draft):
    """Keep only completed public-text fields that fit the private SQL contract."""
    kept = {}
    for key, limit in (('ko', 200000), ('jaTitle', 300), ('ja', 200000)):
        value = draft.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
            continue
        try:
            size = len(json.dumps({**kept, key: value}, ensure_ascii=False).encode())
        except UnicodeEncodeError:
            continue
        if size <= 445000:
            kept[key] = value
    return kept or None


def validate_candidate_fields(output):
    for language, stage in (('Ko', 'korean_validation'), ('Ja', 'japanese_validation')):
        with failure_stage(stage):
            for field, limit in (('title', 300), ('summary', 1000), ('content', 200000)):
                value = output.get(field + language)
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit or '\x00' in value:
                    raise ValidationError('required_text_field', 'missing_or_invalid')
            require_plain_summary(output['summary' + language])
            read_body(output['content' + language])
    require_plain_summary(output['titleJa'])
    model = output.get('aiModel')
    if not isinstance(model, str) or not 1 <= len(model.strip()) <= 100 or '\x00' in model:
        raise ValidationError('summary_result', 'missing_or_invalid')
    if len(json.dumps(output, ensure_ascii=False).encode()) > 600000:
        raise ValidationError('required_text_field', 'empty_or_too_long')


class ProgramCandidateReview:
    def __init__(self, suggest):
        self.suggest = suggest
        self.issues = []
        self.stage = 'korean_validation'

    def record(self, error):
        issue = {'stage': self.stage, **error.diagnostic}
        if issue not in self.issues and len(self.issues) < MAX_ISSUES:
            self.issues.append(issue)

    def check(self, validate, *args, **kwargs):
        try:
            validate(*args, **kwargs)
        except ValidationError as error:
            self.record(error)

    def propose(self, output, source):
        self.stage = 'correction'
        # Every diagnostic has a disposition even when no supported edit is returned.
        review = {'source': source, 'issues': [dict(issue, disposition='needs_review') for issue in self.issues]}
        from ingest.seoul_review_context import attach_context
        attach_context(review['issues'], output, source)
        for issue in review['issues']:
            issue['reviewOutcome'] = 'no_finding'
        if not callable(self.suggest):
            return review
        try:
            # Reuse bounded excerpts already identified above; no extra AI request.
            payload = self.suggest(output=output, source=source, issues=[
                {k: v for k, v in issue.items() if k not in {'disposition', 'reviewOutcome'}}
                for issue in review['issues']])
        except AiJobError as error:
            if error.code not in {'ai_refusal', 'ai_unexpected_thinking'} or getattr(error, 'failure_scope', None) == 'batch':
                raise
            for issue in review['issues']:
                issue['reviewOutcome'] = 'provider_declined'
            return review
        if not isinstance(payload, dict) or set(payload) != {'findings'} or not isinstance(payload['findings'], list):
            for issue in review['issues']:
                issue['reviewOutcome'] = 'invalid_response'
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
                for issue in review['issues']:
                    issue['reviewOutcome'] = 'duplicate_finding'
                return review
            seen.add(index)
            issue = review['issues'][index - 1]
            evidence = row.get('evidence')
            if row.get('decision') == 'needs_review':
                issue['reviewOutcome'] = 'ai_needs_review'
                if isinstance(evidence, str) and 0 < len(evidence.strip()) <= 500 and evidence in source:
                    issue['evidence'] = evidence
                continue
            if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 500 or evidence not in source:
                issue['reviewOutcome'] = 'evidence_not_matched'
                continue
            if row.get('decision') == 'equivalent':
                patches.append((issue, {'disposition': 'equivalent', 'evidence': evidence, 'reviewOutcome': 'equivalent'}))
                continue
            issue['evidence'] = evidence
            if row.get('decision') != 'change':
                issue['reviewOutcome'] = 'invalid_decision'
                continue
            patch = self.patch(row, issue, output, evidence)
            if patch:
                patch['reviewOutcome'] = 'change'
                patches.append((issue, patch))
            else:
                issue['reviewOutcome'] = 'unsafe_patch'

        for issue, patch in patches:
            if patch['disposition'] == 'change' and any(
                other is not patch and other.get('field') == patch['field']
                and other['start'] < patch['end'] and patch['start'] < other['end']
                for _, other in patches
            ):
                issue['reviewOutcome'] = 'overlapping_patch'
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
