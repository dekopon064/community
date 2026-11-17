"""Seoul-specific validation, source projection and fenced completion."""
from ingest.program_candidate_review import ProgramCandidateReview


class SeoulCandidateReview(ProgramCandidateReview):
    @classmethod
    def for_translation(cls, translate):
        suggest = getattr(getattr(translate, '__self__', None), 'suggest_seoul_review', None)
        return cls(suggest) if callable(suggest) else None

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
