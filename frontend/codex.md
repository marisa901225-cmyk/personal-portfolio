내 Next.js(Vercel) 프론트에서 네이버 OAuth 로그인 성공(화면에 로그인됨 표시) + 백엔드 상태 확인 API 테스트도 성공하는데,
계속 "서버 연결이 필요합니다. 설정에서 서버 URL과 API 토큰을 입력해주세요." 화면(서버 연결 설정 페이지)으로 강제 이동됨.

목표:
- 기존 X-API-Key 기반 게이트를 네이버 로그인(JWT Bearer)로 전환했는데,
- 로그인 후에는 API 키 입력 없이도 앱이 정상 동작해야 함.
- 서버 URL은 이미 입력되어 있고 상태 확인도 성공했는데도 게이트 화면이 계속 떠서 루프가 생김.

해야 할 일:
1) "서버 연결 필요" 화면으로 보내는 라우트 가드/리다이렉트 조건을 찾아라.
   - 어떤 컴포넌트/훅/미들웨어에서 조건으로 redirect하는지 찾아서 파일/라인을 보고해라.
2) 인증 조건을 수정해라:
   - 기존 조건이 (apiBaseUrl && apiKey) 같은 형태면,
     이제는 (apiBaseUrl && (jwt || apiKey)) 로 바꿔라.
   - jwt는 sessionStorage/localStorage/쿠키 중 어디에 저장되어 있는지 현재 코드를 확인하고,
     저장/복구 로직이 없으면 추가해라.
3) ApiClient(axios/fetch wrapper)에서 Authorization 헤더가 실제로 붙는지 확인하고 수정해라.
   - jwt가 있으면 `Authorization: Bearer <jwt>` 를 보내고
   - jwt가 없을 때만 fallback으로 `X-API-Key` 를 보낸다.
4) "백엔드 상태 확인" 버튼이 성공해도 저장이 안 되어 리다이렉트가 계속 되는지 확인해라.
   - serverUrl/apiBaseUrl 값을 localStorage 등에 저장하는지 확인하고 없으면 저장하도록 수정해라.
5) 수정 후 동작 검증 시나리오를 정리해라:
   - (1) 로그아웃 상태 → 게이트 화면 정상
   - (2) 네이버 로그인 완료 → 게이트 화면 없이 메인으로 이동
   - (3) 새로고침 후에도 jwt 복구되어 접근 유지(또는 의도한 방식대로 동작)

작업 방식:
- 레포에서 관련 키워드로 먼저 찾아라: "서버 연결이 필요합니다", "API 토큰", "serverUrl", "apiBaseUrl", "X-API-Key", "Authorization", "redirect", "navigate('/settings')" 등.
- 찾은 파일/라인 기반으로 최소 수정 diff로 패치를 제안해라.
- 변경해야 할 코드 조각은 실제 코드로 보여줘라.
