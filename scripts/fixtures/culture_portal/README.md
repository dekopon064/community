# 서울문화포털 수집 시험 자료

확인일: 2026-11-12 (한국 시간). 운영 수집 실행 결과가 아닌 공개 페이지 구조 확인용 자료입니다.

- `official-detail-160138.html`: 서울문화포털 ‘2026 복작복작 오늘전통축제’ 공개 상세 HTML. `https://culture.seoul.go.kr/culture/culture/cultureEvent/view.do?cultcode=160138&menuNo=200010`
- `official-list.html`: 공식 축제 목록의 동적 HTML. `https://culture.seoul.go.kr/culture/culture/cultureEvent/list.do?searchCate=FESTIVAL&menuNo=200010&sdate=2026-11-12&edate=2026-12-13&pageIndex=1`
- `official-list.json`: 위 페이지가 사용하는 동일 출처 `jsonList.json` 조회 응답 1페이지. HTML만 읽어 빈 목록으로 오인하지 않는지 검증합니다. 인증이 없는 공개 조회이며 저장 API가 아닙니다.
- `admin-synthetic.json`: 격리 PostgreSQL에서 합성 행사와 합성 기존 항목으로 생성한 관리자 RPC 결과. 실제 후보/운영 기록이 아닙니다. SQL 시험마다 합성 UUID와 버전이 바뀔 수 있습니다.

시험은 보존 파일을 재생하며 외부 페이지를 다시 요청하지 않습니다. HTML의 스크립트는 실행하지 않습니다. 실제 포스터 이미지 다운로드·OCR·첨부/외부 사이트 조사도 하지 않습니다.

도림천 유형의 시간 충돌, 식물원의 별도 문화 행사, 유료 체험, 관광객 조건, 축제 내부 예약 프로그램 연결은 합성 반례입니다. 해당 실제 행사의 현재 운영 조건을 확인했다는 뜻이 아닙니다.
