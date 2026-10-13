"""Explicit per-session quantities, synthetic text only; no network/provider."""
import socket
import unittest
from unittest.mock import patch
from ingest.ai_errors import AiJobError
from ingest.translation_validation import validate_translation_fidelity


class PerSessionTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def validate(self, ko, ja):
        validate_translation_fidelity('합성 안내', ko, '合成案内', ja)

    def test_reported_pair_and_normal_alternatives(self):
        cases = [
            ('회당 20명·9가족', ja) for ja in ('1回につき20名・9家族', '1回当たり20人・9家族',
                '1回あたり20名・9家族', '各回20名・9家族', '毎回20名・9家族',
                '20名・9家族（1回につき）', '一回につき20名・9家族', '1回ごとに20名・9家族')
        ] + [
            ('회차당 12명', '1回につき12名'), ('매회 12명', '毎回12名'),
            ('각 회차 12명', '各回12名'), ('1회당 25명', '1回当たり25名'),
            ('2회당 25명', '2回当たり25名'), ('회당 18세 이상 20명', '1回につき18歳以上20名'),
            ('회당 비용: 수강료 1,000원', '1回当たりの費用: 受講料1,000ウォン'),
            ('회당 한국어 1반', '1回につき韓国語クラス1'),
            ('총 3회, 회당 20명', '全3回、1回につき20名'),
            ('1회, 정원 20명', '1回、定員20名'),
        ]
        for ko, ja in cases:
            for source, target in [(ko, ja), ('- '+ko, '- '+ja), ('- **'+ko+'**', '- **'+ja+'**')]:
                with self.subTest(ko=source, ja=target):
                    self.validate(source, target)

    def test_counts_capacity_family_units_and_conditions_still_fail(self):
        cases = [
            ('회당 20명·9가족', '1回につき21名・9家族'),
            ('회당 20명·9가족', '1回につき20名・8家族'),
            ('회당 20명', '2回につき20名'),
            ('회당 20명', '二回当たり20名'),
            ('회당 20명', '11回当たり20名'),
            ('회당 20명', '全1回、20名'),
            ('회당 20명', '定員20名'),
            ('총 1회, 20명', '1回につき20名'),
            ('총 3회, 회당 20명', '全2回、1回につき20名'),
            ('총 3회, 회당 20명', '1回につき20名'),
            ('회당 20명', '1回につき20家族'),
            ('회당 20명 이상', '1回につき20名以下'),
            ('회당 20명, 보호자 동반 필수', '1回につき20名、保護者同伴は任意'),
            ('회당 20명, 재신청 불가', '1回につき20名、再申請できます'),
            ('회당 20명, 익월 예약이 불가', '1回につき20名、翌月の予約もできます'),
            ('회당 1,000원', '1回につき2,000ウォン'),
            ('총 3회, 회당 정원 20명, 전체 정원 30명', '全3回、1回につき定員30名、全体の定員20名'),
        ]
        for ko, ja in cases:
            with self.subTest(ko=ko, ja=ja), self.assertRaises(AiJobError):
                self.validate('- '+ko, '- '+ja)

    def test_per_session_is_not_an_ordinal_or_a_total_in_other_cell(self):
        ko='| 회차 | 정원 |\n| --- | --- |\n| 1회 | 회당 20명·9가족 |\n| 2회 | 회당 15명 |'
        ja='| 回 | 定員 |\n| --- | --- |\n| 1回 | 1回につき20名・9家族 |\n| 2回 | 1回当たり15名 |'
        self.validate(ko, ja)
        for bad in (ja.replace('| 2回 |', '| 3回 |'),
                    ja.replace('20名・9家族', '15名・9家族').replace('当たり15名', '当たり20名'),
                    ja.replace('| 1回 |', '| 1回につき |')):
            with self.subTest(bad=bad), self.assertRaises(AiJobError):
                self.validate(ko, bad)


if __name__ == '__main__':
    unittest.main()
