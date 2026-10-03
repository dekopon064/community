export const categories = { policy: "정책", program: "프로그램", event: "행사", youth_space: "청년공간", living: "생활" };
const reasons: Record<string, { title: string; help: string }> = {
  restored_review_pending: { title: "복구한 사실을 다시 확인해 주세요", help: "기존 사실과 근거를 확인한 뒤 사실 저장·재평가를 눌러 주세요. 수정할 내용이 없어도 검토를 완료할 수 있습니다." },
  product_type_unknown: { title: "정보 성격을 확인해 주세요", help: "원문을 읽고 행사·프로그램, 정책 참고자료, 생활 안내 중 하나를 선택해 주세요." },
  product_type_unconfirmed: { title: "정보 성격을 확인해 주세요", help: "원문을 읽고 정보 성격을 선택해 주세요. 공개 카테고리와는 별도 판단입니다." },
  policy_lifecycle_uncertain: { title: "이 정책의 정보 성격을 확인해 주세요", help: "모집 중인 행사·프로그램인지, 계속 참고하는 정책 자료인지, 생활 안내인지 원문을 읽고 선택해 주세요. 저장 후 추가로 확인할 지역·신청 자격·카테고리를 확인합니다." },
  policy_lifecycle_conflict: { title: "정책의 기간 정보와 성격이 일치하지 않습니다", help: "원문에서 실제 모집·진행 기간을 확인하고 정보 성격을 선택하세요. 이미 확정된 정보 성격은 이 화면에서 덮어쓸 수 없습니다." },
  end_date_absent_not_reference: { title: "종료일이 없지만 상시 참고자료인지 불명확합니다", help: "종료일이 없다는 사실만으로 상시 자료로 판단하지 마세요. 원문을 읽고 행사·프로그램, 정책 참고자료, 생활 안내 중 정보 성격을 선택하세요." },
  missing_source_url: { title: "공식 원문 링크가 없습니다", help: "이 화면에서는 원문 링크를 보완할 수 없습니다. 수집된 원문 정보를 별도로 확인하거나, 부적격 판단이 가능하면 제외 사유를 남겨 주세요." },
  attachment_dependent: { title: "첨부파일을 확인해야 사실을 판단할 수 있습니다", help: "원문 링크에서 첨부파일을 확인하세요. 이 화면에서는 원문 본문을 교체할 수 없으며, 부족한 본문은 별도 보완이 필요합니다." },
  region_scope_unknown: { title: "누가 어느 지역에서 이용할 수 있는지 확인해 주세요", help: "개최 장소가 아니라 신청·이용 대상 지역을 선택하고 원문 근거를 입력해 주세요." },
  relevance_unconfirmed: { title: "외국인 거주자의 신청 자격을 확인해 주세요", help: "정책 원문에서 외국인 거주자도 신청할 수 있는지 확인해 주세요. 불명확하면 ‘확인 필요’를 유지하세요." },
  user_category_unconfirmed: { title: "공개 카테고리를 선택해 주세요", help: "정책·프로그램·행사·청년공간·생활 중 독자가 찾을 카테고리를 선택해 주세요." },
  application_deadline_unknown: { title: "신청 마감을 확인해 주세요", help: "정책·프로그램은 마감일, 정해진 마감 없음, 이미 접수 종료 중 하나를 선택하세요. 행사 개최일을 마감일로 입력하지 마세요." },
  event_period_unknown: { title: "행사 개최 기간을 확인해 주세요", help: "신청 기간이 아닌 실제 행사 시작일과 종료일을 입력해 주세요." },
  insufficient_evidence: { title: "판단할 수 있는 원문 근거가 부족합니다", help: "공식 원문에서 사실을 확인하세요. 끝내 확인할 수 없다면 사유를 남기고 제외할 수 있습니다." },
  manual_non_target: { title: "운영자가 서비스 대상에서 제외했습니다", help: "처리 이력에서 제외 사유를 확인해 주세요." },
};
export function reasonText(code: string) {
  return reasons[code] ?? { title: "추가 확인이 필요한 항목입니다", help: "현재 입력 항목으로 해결할 수 있는지 확인하세요. 지원하지 않는 사유는 임의로 해소 처리하지 않습니다." };
}
export const statusText: Record<string, string> = { open: "사실 확인 필요", resolved: "사실 검토 완료", excluded: "제외됨", pending: "후보 검토 대기", published: "게시됨", rejected: "반려됨", superseded: "다른 후보로 대체됨" };
export const aiStatusText: Record<string, string> = {
  blocked: "AI 작업이 준비되지 않았습니다. 남은 확인 사유를 확인하세요.", queued: "AI 대기 · 실행은 별도 자동화가 담당합니다.",
  claimed: "AI 작업이 다른 처리에서 진행 중입니다.", completed: "기존 AI 작업은 완료 상태입니다.",
  failed: "AI 작업은 실패 상태입니다. 별도 확인이 필요합니다.", cancelled: "AI 작업은 취소 상태입니다.",
};
export const actionText: Record<string, string> = { save_facts: "사실 저장·재평가", exclude: "부적격 제외", save_candidate: "비공개 수정 저장", publish: "승인하고 게시", reject: "반려" };
export const failureText: Record<string, string> = {
  trash_targets_changed: "삭제 대상이 변경되었습니다. 새로고침한 뒤 대상과 건수를 다시 확인해 주세요.",
  too_many_trash_items: "한 번에 비울 수 있는 항목은 5,000개까지입니다. 개별 삭제로 항목을 줄인 뒤 다시 확인해 주세요.",
  program_input_changed: "후보 생성 이후 프로그램 사실이 변경되어 게시할 수 없습니다. 자동 요약·재번역은 실행하지 않았습니다. 현재 사실과 후보의 대조가 필요합니다.",
  program_unavailable: "현재 프로그램의 접수 상태·검토 결과 또는 수집원 권한 때문에 게시할 수 없습니다. 후보는 비공개로 유지됩니다.",
  not_connected: "관리 데이터 연결 설정을 확인할 수 없습니다. 서버의 DB 모드와 키 설정이 준비되어야 항목을 조회하거나 처리할 수 있습니다.",
  not_found: "항목을 찾을 수 없습니다. 목록을 다시 확인해 주세요.",
  conflict: "다른 변경이 먼저 저장되었거나 원문이 갱신되었습니다. 입력을 복사해 두고 최신 내용을 다시 불러와 확인해 주세요.",
  already_processed: "이미 처리된 항목입니다. 최신 상태를 다시 확인해 주세요.",
  publish_failed: "게시되지 않았습니다. 저장된 후보는 비공개로 유지됩니다. 게시 조건을 확인한 뒤 다시 시도해 주세요.",
  invalid_input: "입력한 값을 확인해 주세요. 표시된 항목을 수정한 뒤 다시 저장할 수 있습니다.",
  unavailable: "요청을 완료하지 못했습니다. 최신 상태를 다시 확인한 뒤 재시도해 주세요.",
  signed_out: "로그인이 만료되었거나 로그인하지 않았습니다. 다시 로그인해 주세요.",
  forbidden: "이 계정에는 운영자 권한이 없습니다. 운영자 계정으로 다시 로그인해 주세요.",
  auth_unavailable: "로그인 상태를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
  configuration_error: "운영자 권한 설정을 확인할 수 없습니다. 서비스 관리자에게 문의해 주세요.",
  wrong_origin: "요청 출처를 확인할 수 없습니다. 관리 화면을 다시 열어 주세요.",
};
export function sourceLink(value: string): string | null {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}

Object.assign(actionText, {restore: "휴지통에서 복구", confirm_restored: "복구 후 사실 재확인"});
Object.assign(failureText, {trash_expired: "복구 기한 72시간이 지났습니다. 휴지통을 새로고침해 주세요.", trash_source_changed: "원문이 변경되어 이전 항목을 복구할 수 없습니다. 최신 review 항목을 확인해 주세요.", trash_processing_active: "작업이 처리 중이라 지금 처리할 수 없습니다. 완료 후 최신 상태를 확인해 주세요.", trash_already_published: "이미 게시된 항목입니다. 최신 상태를 확인해 주세요."});
