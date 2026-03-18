# Mini Redis Architecture

## 목표

Mini Redis는 RESP 프로토콜을 이용해 `SET`, `GET`, `DEL`을 처리하는 간단한 in-memory key-value 서버를 만드는 프로젝트입니다.

## 모듈 경계

- `server/`
  - 소켓 서버 실행
  - 클라이언트 연결 처리
  - 요청/응답 흐름 제어
- `protocol/`
  - RESP 요청 파싱
  - RESP 응답 인코딩
- `commands/`
  - 명령어 분기
  - storage 호출 연결
  - 에러 응답 처리
- `storage/`
  - key-value 저장
  - 삭제 처리
  - TTL 확장 포인트
- `client/`
  - 수동 테스트용 간단한 클라이언트
- `tests/`
  - 프로토콜, 저장소, 명령어, 통합 테스트

## 인터페이스 계약

### Storage

```python
set(key: str, value: str) -> None
get(key: str) -> str | None
delete(key: str) -> bool
expire(key: str, seconds: int) -> bool
```

### Parser output

```python
["SET", "mykey", "123"]
["GET", "mykey"]
["DEL", "mykey"]
```

### Command handler output

```text
+OK\r\n
$3\r\n123\r\n
$-1\r\n
:1\r\n
-ERR unknown command\r\n
```

## 1차 구현 순서

1. 서버에서 raw 요청을 받습니다.
2. RESP 요청을 배열 형태로 파싱합니다.
3. Command handler가 storage와 연결됩니다.
4. RESP 형태로 응답을 반환합니다.
5. 단위 테스트와 통합 테스트를 작성합니다.
