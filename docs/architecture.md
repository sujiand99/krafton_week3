# Mini Redis Architecture

## 목표

Mini Redis는 RESP 프로토콜을 이용해 `SET`, `GET`, `DEL`, `EXPIRE`를 처리하는 간단한 in-memory key-value 서버를 만드는 프로젝트입니다.
Mini Redis는 RESP 프로토콜을 이용해 `SET`, `GET`, `DEL`, `EXPIRE`, `TTL`를 처리하는 간단한 in-memory key-value 서버를 만드는 프로젝트입니다.

## 모듈 경계

- `server/`
  - 소켓 서버 실행
  - 클라이언트 연결 처리
  - 요청/응답 흐름 제어
  - command 결과를 RESP 응답으로 인코딩
- `protocol/`
  - RESP 요청 파싱
  - RESP 응답 인코딩
- `commands/`
  - 명령어 분기
  - storage 호출 연결
  - 명령 유효성 검증
  - 인자 파싱 및 예외 전달
- `storage/`
  - key-value 저장
  - 삭제 처리
  - TTL 메타데이터 저장
  - lazy expiration 처리
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
expire(key: str, seconds: int, option: str | None = None) -> bool
ttl(key: str) -> int
```

### Parser output

```python
["SET", "mykey", "123"]
["GET", "mykey"]
["DEL", "mykey"]
["EXPIRE", "mykey", "10"]
["EXPIRE", "mykey", "10", "NX"]
["TTL", "mykey"]
```

### Command handler output

```python
"OK"
"123"
None
1
0
-1
-2
```

- `SET key value` -> `"OK"`
- `GET key` -> `str | None`
- `DEL key` -> `1 | 0`
- `EXPIRE key seconds [NX | XX | GT | LT]` -> `1 | 0`
- `TTL key` -> `int`
- `PING`, `PERSIST`, `RENAME`은 현재 미지원

### Command handler errors

```python
CommandError
UnknownCommandError
WrongNumberOfArgumentsError
```

Command layer는 RESP 에러 문자열을 직접 만들지 않습니다. 예외를 상위 계층으로 전달하고, 서버/프로토콜 계층이 이를 RESP 에러로 인코딩합니다.

## TTL 설계

### 저장 방식

- 실제 값은 key-value store에 저장합니다.
- TTL은 별도의 만료 메타데이터에 저장합니다.
- 만료 시각은 `현재 monotonic clock + seconds`로 계산한 절대 deadline으로 관리합니다.

### 만료 처리 방식

- active expiration이나 background sweeper는 두지 않습니다.
- 만료 검사는 key를 접근하는 시점에만 수행합니다.
- 현재 구현에서 lazy expiration이 적용되는 경로는 `GET`, `DEL`, `EXPIRE`입니다.
- 만료된 key를 발견하면 value와 TTL 메타데이터를 함께 삭제합니다.

### 명령별 TTL 규칙

- `SET`
  - 값을 저장합니다.
  - 기존 TTL이 있으면 제거합니다.
  - 결과적으로 key는 다시 persistent 상태가 됩니다.
- `GET`
  - 먼저 만료 여부를 확인합니다.
  - 만료되지 않았으면 값을 반환하고, 만료됐으면 key를 삭제한 뒤 `None`을 반환합니다.
- `TTL`
  - 먼저 만료 여부를 확인합니다.
  - key가 없으면 `-2`
  - key는 있지만 만료 시간이 없으면 `-1`
  - 만료 시간이 있으면 남은 초를 정수로 반환합니다.
- `DEL`
  - 먼저 만료 여부를 확인합니다.
  - 삭제 시 value와 TTL 메타데이터를 함께 제거합니다.
- `EXPIRE`
  - key가 없거나 이미 만료된 경우 `False`
  - key가 존재하면 새 TTL을 적용하거나 갱신합니다.
  - `NX`: 현재 TTL이 없을 때만 적용
  - `XX`: 현재 TTL이 있을 때만 적용
  - `GT`: 새 deadline이 기존 deadline보다 클 때만 적용
  - `LT`: 새 deadline이 기존 deadline보다 작을 때만 적용
  - `GT`와 `LT` 비교에서 TTL이 없는 key는 무한 TTL로 취급합니다.
  - `seconds <= 0`이면 TTL을 저장하지 않고 key를 즉시 삭제합니다.

## 요청 처리 흐름

1. 서버가 raw bytes 요청을 받습니다.
2. protocol 계층이 RESP 배열을 파싱해 토큰 리스트를 만듭니다.
3. command handler가 명령 이름과 인자 개수를 검증합니다.
4. `EXPIRE`의 경우 seconds와 option을 파싱합니다.
5. command handler가 storage를 호출합니다.
6. storage는 필요한 경우 만료를 정리한 뒤 결과를 반환합니다.
7. 서버가 command 결과를 RESP 타입에 맞게 인코딩합니다.
8. 에러가 발생하면 서버가 RESP error 응답으로 변환합니다.

## 테스트 전략

- storage 테스트
  - TTL 저장, 남은 TTL 조회, 만료 후 정리, `SET` 시 TTL 제거, 옵션별 `NX/XX/GT/LT`, `seconds <= 0` 즉시 삭제 검증
- command 테스트
  - `EXPIRE`, `TTL` 명령 인자 수 검증, seconds 정수 파싱, 옵션 검증, 반환값 검증
- integration 테스트
  - 실제 소켓 흐름에서 `SET -> EXPIRE -> GET` 검증
  - 실제 소켓 흐름에서 `TTL` integer 응답 검증
  - fake clock 주입으로 `sleep` 없이 만료 전후 동작 검증
  - RESP 레벨에서 `EXPIRE` integer 응답 검증
