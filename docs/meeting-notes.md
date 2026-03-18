# Meeting Notes

## 2026-03-18

- Mini Redis 팀 프로젝트 초기 구조를 합의했습니다.
- MVP 범위는 `SET`, `GET`, `DEL`로 확정했습니다.
- 브랜치 전략은 `main` / `dev` / 기능 브랜치로 진행합니다.
- 파일 ownership은 `server`, `protocol`, `storage`, `commands`, `tests/docs/client` 단위로 나눕니다.
- 초기 레포 세팅 후 각자 기능 브랜치에서 구현을 시작합니다.
- Command layer MVP 계약은 RESP 문자열을 만들지 않고 순수 결과만 반환하는 형태로 정리했습니다.
- Command layer 에러는 `CommandError` 계열 예외로 상위 계층에 전달하고, 서버/프로토콜 계층이 RESP 에러로 인코딩합니다.
