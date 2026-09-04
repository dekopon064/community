import { FEEDBACK_CS_EMAIL, FEEDBACK_PRIVACY_NOTICE_VERSION } from "@/app/lib/feedback-privacy";
import type { PrivacyDoc } from "./types";

export const koPrivacy: PrivacyDoc = {
  title: "마치모아 개인정보처리방침",
  version: FEEDBACK_PRIVACY_NOTICE_VERSION,
  intro: [
    "이 안내는 로그인·계정·연락처 없이 비공개로 보내는 피드백과 그 처리에 관한 것입니다. 피드백 본문에는 개인정보나 민감정보를 적지 않도록 안내합니다.",
    "이 문서는 법률 적합성을 보장하지 않습니다. 공고일·시행일·운영자 실명 등 자리 표시는 공개 전 법률 검토 후 실제 값으로 바꿉니다.",
  ],
  sections: [
    {
      id: "scope",
      title: "1. 서비스와 이 안내문의 범위",
      blocks: [
        {
          type: "p",
          text: "마치모아(Machimoa)는 사람이 검수한 한국 생활정보를 한국어와 일본어로 제공합니다. 생활정보 열람에는 회원가입이 없고 연령 제한도 없습니다.",
        },
        {
          type: "p",
          text: "피드백은 운영 개선을 위한 비공개 제출입니다. 공개 Q&A, 큐레이션, 사용자 후기, 홈 인용, SNS·마케팅, 제품 요구사항으로 자동 전환하거나 자동 공개하지 않습니다.",
        },
        {
          type: "p",
          text: "현재 피드백은 서비스 개선을 위한 단방향 의견 접수입니다. 이메일 답변이나 개별 후속 연락 기능을 제공하지 않습니다.",
        },
      ],
    },
    {
      id: "controller",
      title: "2. 개인정보 보호 담당 / 연락처",
      blocks: [
        {
          type: "ul",
          items: [
            "담당 명칭: Machimoa 개인정보 보호 담당",
            `문의 이메일: ${FEEDBACK_CS_EMAIL}`,
            "운영자 실명·전화번호: [서비스 개시 전 법률 검토 후 결정]",
          ],
        },
      ],
    },
    {
      id: "purpose",
      title: "3. 처리 목적",
      blocks: [
        {
          type: "ul",
          items: [
            "한국 생활정보 수요 파악",
            "제품 의견 검토",
            "기타 문의 검토",
            "스팸·반복 제출 방지",
            "접수 코드를 통한 삭제 요청 처리",
          ],
        },
        {
          type: "p",
          text: "자동 공개, 광고, 프로파일링을 하지 않습니다. 현재 분석·광고 추적 도구는 없습니다. 익명 인용 동의와 마케팅 동의는 받지 않습니다.",
        },
      ],
    },
    {
      id: "items",
      title: "4. 처리 항목",
      blocks: [
        {
          type: "p",
          text: "필수: 피드백 유형, 본문, locale, 개인정보 동의 여부, 만 14세 이상 확인 여부(생년월일·정확한 나이가 아님), 적용된 개인정보 안내문 버전, Turnstile 검증 정보, 원본 IP를 저장하지 않고 생성한 rate-limit HMAC.",
        },
        {
          type: "p",
          text: "선택: 생활 주제.",
        },
        {
          type: "p",
          text: "별도 입력 항목으로 수집하지 않음: 이름, 이메일 주소, 생년월일, 정확한 나이, 전화번호, 주소, 외국인등록번호, 계약서, 첨부파일.",
        },
      ],
    },
    {
      id: "age",
      title: "5. 만 14세",
      blocks: [
        {
          type: "p",
          text: "만 14세 미만의 피드백 제출만 제한합니다. 확인은 개인정보 수집·이용 동의와 다른 필수 확인란이며, 생년월일이나 정확한 나이를 받지 않습니다. 생활정보 열람에는 연령 제한이 없습니다. 만 14세 미만임을 알게 되면 해당 피드백을 지체 없이 삭제합니다.",
        },
      ],
    },
    {
      id: "retention",
      title: "6. 보유·파기",
      blocks: [
        {
          type: "ul",
          items: [
            "일반 피드백: 이용자에게는 최대 180일. 저장 시스템은 생성일부터 178일을 기준으로 정리합니다.",
            "스팸 판정 피드백: 이용자에게는 최대 30일. 저장 시스템은 28일을 기준으로 정리합니다.",
            "rate-limit HMAC: 이용자에게는 최대 72시간. 저장 시스템은 48시간을 기준으로 정리합니다.",
            "접수 코드로 삭제 요청이 처리되면 Supabase의 해당 제출과 접수 HMAC를 즉시 완전히 삭제합니다. 삭제 흔적(tombstone)을 남기지 않습니다.",
            "비식별 정리 이력(purge_runs)은 최대 30일 보존합니다.",
            "개인을 식별할 수 없는 집계는 더 오래 둘 수 있습니다.",
          ],
        },
      ],
    },
    {
      id: "processors",
      title: "7. 외부 처리",
      blocks: [
        {
          type: "ul",
          items: [
            "Supabase: 서울 지역 데이터베이스와 Edge Function(ap-northeast-2)에서 피드백 원문과 처리 상태를 다룹니다.",
            "Cloudflare Turnstile: 스팸 방지 검증. Production 호스트는 community-app-drab.vercel.app입니다.",
            "Telegram: 새 의견이 저장되었다는 고정 문장만 보냅니다. 피드백 내용이나 사용자 관련 정보는 보내지 않으며, 개인 채팅은 최대 7일 보관합니다. 알림이 실패해도 저장된 피드백은 유지됩니다.",
            "Gmail: 개인정보 관련 문의를 받는 용도로만 사용합니다. 피드백 답변이나 후속 연락, 자동 전달, 광고 목적에는 사용하지 않으며 2단계 인증을 적용했습니다.",
            "Vercel: 앱 페이지와 정적 파일을 제공하고 일반 웹 요청 로그를 처리합니다.",
          ],
        },
        {
          type: "p",
          text: "피드백 POST는 브라우저에서 Supabase Edge Function으로 직접 전송됩니다. 현재 구현에서 피드백 본문을 Vercel Route Handler나 Server Action으로 보내지 않습니다. Vercel이 피드백 원문을 처리한다고 보지 않습니다. 브라우저·Vercel 로그 검증이 이 설명과 다르면 공개 전에 문서 또는 구현을 수정합니다.",
        },
      ],
    },
    {
      id: "overseas",
      title: "8. 국외 처리",
      blocks: [
        {
          type: "p",
          text: "확인된 사실만 적습니다. Vercel Function 지역은 미국 워싱턴(iad1), Cloudflare Turnstile, Telegram, Gmail이 국외에서 처리될 수 있습니다. 확인되지 않은 법인 소재지는 쓰지 않습니다.",
        },
      ],
    },
    {
      id: "rights",
      title: "9. 이용자 권리",
      blocks: [
        {
          type: "p",
          text: "접수 코드를 저장해 둔 경우 삭제 화면에서 Supabase에 남은 해당 제출을 삭제 요청할 수 있습니다. 삭제 완료 응답은 코드가 실제로 있었는지, 이미 없었는지를 구분하지 않습니다. 이메일 문의는 위 연락처로 할 수 있습니다.",
        },
      ],
    },
    {
      id: "logs",
      title: "10. 로그·PWA",
      blocks: [
        {
          type: "p",
          text: "앱 로그에 피드백 본문, 접수 코드, HMAC, 원본 IP, Turnstile token, 요청 본문, 데이터베이스 행을 남기지 않도록 구현합니다. Supabase Free 로그 조회는 약 1일, Vercel Hobby Runtime 로그 조회는 약 1시간입니다. 조회 가능 기간이 완전 삭제를 보장하는 것은 아닙니다.",
        },
      ],
    },
    {
      id: "cookies",
      title: "11. 쿠키·Turnstile·PWA 캐시",
      blocks: [
        {
          type: "p",
          text: "Turnstile은 스팸 방지에 필요합니다. PWA는 페이지와 정적 자산을 캐시할 수 있습니다. 피드백 제출·삭제 POST는 NetworkOnly로 두고, 피드백 본문과 접수 코드는 Cache Storage에 넣지 않습니다.",
        },
      ],
    },
    {
      id: "refusal",
      title: "12. 동의 거부",
      blocks: [
        {
          type: "p",
          text: "필수 개인정보 수집·이용 동의와 만 14세 이상 확인을 거부할 수 있으나, 없으면 피드백을 제출할 수 없습니다. 생활정보 열람에는 영향이 없습니다.",
        },
      ],
    },
    {
      id: "changes",
      title: "13. 안내 변경",
      blocks: [
        {
          type: "p",
          text: `현재 안내문 버전은 ${FEEDBACK_PRIVACY_NOTICE_VERSION}입니다. 수집 목적, 항목, 보존기간 또는 외부 처리가 실질적으로 바뀌면 버전을 올립니다. 새 목적을 이미 받은 제출에 소급하지 않습니다.`,
        },
      ],
    },
    {
      id: "dates",
      title: "14. 공고일·시행일",
      blocks: [
        {
          type: "ul",
          items: [
            "공고일: [공고일]",
            "시행일: [시행일]",
          ],
        },
        {
          type: "p",
          text: "같은 배포에서 공개되면 공고일과 시행일은 같은 실제 날짜입니다. 소급하여 시행하지 않습니다. 자리 표시 날짜를 임의로 확정하지 않습니다.",
        },
      ],
    },
  ],
};
