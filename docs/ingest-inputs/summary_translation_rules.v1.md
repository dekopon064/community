# Machimoa Summary and Japanese Translation Rules v1

## Korean summary format

Use the following compact structure:

```text
[한 줄 요약]
핵심 내용을 한두 문장으로 작성한다.

[대상]
원문에서 명확하게 확인되는 신청·참여 대상만 작성한다.

[기간·상태]
원문에서 확인되는 신청 기간, 행사 기간 또는 현재 상태를 작성한다.

[주요 내용]
지원 내용, 행사 내용, 금액, 장소 등 사용자가 알아야 할 핵심 사실만 작성한다.

[신청 방법]
원문에서 확인되는 신청 방법만 작성한다.
```

Rules:

- `[한 줄 요약]`과 `[주요 내용]`은 필수다.
- 나머지 항목은 원문에서 확인될 때만 작성한다.
- 알 수 없는 정보를 추측하거나 “정보 없음”으로 채우지 않는다.
- 원문 URL은 본문에 반복하지 않는다. UI의 원문 링크를 사용한다.
- 장소와 온라인 진행 여부를 신청 자격으로 해석하지 않는다.
- 홍보 문구와 반복 표현은 제거한다.
- 새로운 자격 조건, 혜택, 기한을 만들어내지 않는다.

## Japanese summary format

Use the following corresponding structure:

```text
[要約]

[対象]

[期間・状況]

[主な内容]

[申請方法]
```

Rules:

- Korean summary와 동일한 사실만 사용한다.
- 자연스럽고 간결한 `です・ます` 문체를 사용한다.
- 일본어 제목과 본문에 한글을 남기지 않는다.
- 한국어 고유명사를 괄호 안에 병기하지 않는다.
- 지역명은 승인된 `region_ja_glossary.v1` 표기를 정확히 사용한다.
- 용어집에 없는 지역명은 한국어 발음을 기준으로 자연스럽게 가타카나로 표기한다.
- 번역하기 어려운 이름을 한국어 그대로 남기지 않는다.
- 기관명과 사업명은 의미를 해치지 않는 범위에서 자연스러운 일본어로 번역한다.
- 원문에 없는 자격, 혜택, 기한 또는 판단을 추가하지 않는다.

## Date and time

- 날짜: `2026年9月21日`
- 기간: `2026年9月1日～2026年9月30日`
- 시간: `14時00分`
- 연도나 시간이 원문에 없으면 임의로 추가하지 않는다.

## Currency

- 한국 원화는 반드시 `ウォン`으로 쓴다.
- 예: `10,000ウォン`
- `円`, `￥`, `¥`를 사용하지 않는다.
- 통화를 환산하지 않는다.

## Region glossary

- 광역지역은 지역 고유명만 가타카나로 쓰고 행정 단위는 일본어 한자를 사용한다.
  - `부산광역시 → プサン広域市`
  - `경기도 → キョンギ道`
- 시·군·구도 지역 고유명만 가타카나로 쓰고 행정 단위는 `市`, `郡`, `区`로 쓴다.
  - `성남시 → ソンナム市`
  - `양평군 → ヤンピョン郡`
  - `강남구 → カンナム区`
- 괄호 독음을 추가하지 않는다.
- 지역명 변환은 승인된 용어집을 우선한다.

## Validation

Japanese title and body must fail validation when:

- either field is empty;
- Hangul remains;
- `円`, `￥`, or `¥` appears.

Validation failure must use the existing AI worker failure/retry path. Do not add a separate queue or fallback provider.
