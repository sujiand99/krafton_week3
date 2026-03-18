# Mini Redis

Mini Redis는 Python으로 Redis와 비슷한 in-memory key-value 저장소를 직접 만들어보는 팀 프로젝트입니다. 해시 테이블 기반 저장 구조를 구현하고, 요청과 응답은 RESP 프로토콜 흐름에 맞춰 처리하는 것이 목표입니다.

## MVP

- `SET key value`
- `GET key`
- `DEL key`
- `EXPIRE key seconds [NX | XX | GT | LT]`
- `TTL key`

## 레포지토리 구조

```text
mini-redis/
|- README.md
|- .gitignore
|- docs/
|  |- architecture.md
|  `- meeting-notes.md
|- server/
|  `- server.py
|- protocol/
|  |- resp_parser.py
|  `- resp_encoder.py
|- commands/
|  |- handler.py
|  `- registry.py
|- storage/
|  |- engine.py
|  |- hash_table.py
|  `- ttl.py
|- client/
|  `- client.py
`- tests/
   |- test_protocol.py
   |- test_storage.py
   |- test_commands.py
   `- test_integration.py
```

## 브랜치 전략

- `main`: 항상 배포 가능한 안정 브랜치
- `dev`: 기능 브랜치들을 머지해서 통합 동작을 확인하는 브랜치
- `feature/*`: 역할별 기능 구현 브랜치
  - `feature/server-resp`
  - `feature/storage-core`
  - `feature/command-handler`
  - `feature/tests-docs`

## 역할 분담

- A: `server/`, `protocol/`
- B: `storage/`
- C: `commands/`
- D: `tests/`, `docs/`, `README.md`, `client/`

## 인터페이스 합의

### Storage

```python
set(key: str, value: str) -> None
get(key: str) -> str | None
delete(key: str) -> bool
expire(key: str, seconds: int, option: str | None = None) -> bool
ttl(key: str) -> int
```

### Parser 출력

```python
["SET", "mykey", "123"]
["GET", "mykey"]
["DEL", "mykey"]
["EXPIRE", "mykey", "10"]
["EXPIRE", "mykey", "10", "NX"]
["TTL", "mykey"]
```

### Command Handler 계약

Command layer는 RESP 문자열을 직접 만들지 않습니다. 파싱된 명령을 해석하고 storage를 호출한 뒤, 순수 결과만 반환합니다.

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
- 현재 지원 범위는 `SET`, `GET`, `DEL`, `EXPIRE`, `TTL`
- `PING`, `PERSIST`, `RENAME`은 아직 지원하지 않음

### TTL 동작 요약

- TTL은 storage 내부 메타데이터로 별도 저장됩니다.
- 만료된 key는 background sweeper 없이 key 접근 시점에 정리하는 lazy expiration 방식으로 처리됩니다.
- `GET`은 값을 읽기 전에 만료 여부를 확인하고, 만료된 key면 삭제 후 `None`을 반환합니다.
- `DEL`은 삭제 전에 만료 여부를 확인하고, 삭제 시 값과 TTL 메타데이터를 함께 제거합니다.
- `SET`은 기존 값을 덮어쓸 때 기존 TTL도 제거해서 key를 다시 persistent 상태로 만듭니다.
- `EXPIRE`는 기존 TTL을 갱신할 수 있습니다.
- `TTL`은 남은 초를 반환합니다.
- `NX`: 현재 TTL이 없을 때만 만료 시간 설정
- `XX`: 현재 TTL이 있을 때만 만료 시간 설정
- `GT`: 새 만료 시간이 기존 만료 시간보다 더 클 때만 설정
- `LT`: 새 만료 시간이 기존 만료 시간보다 더 작을 때만 설정
- `GT`와 `LT` 비교에서 TTL이 없는 key는 무한 TTL로 취급합니다.
- `seconds <= 0`이면 TTL을 저장하지 않고 key를 즉시 삭제합니다.
- `TTL` 반환 규칙은 Redis와 비슷하게 동작합니다.
- key가 없으면 `-2`
- key는 있지만 만료 시간이 없으면 `-1`
- key가 만료 예정이면 남은 초를 정수로 반환합니다.

### Command 에러 처리

Command layer의 에러는 RESP 에러 문자열이 아니라 예외로 상위 계층에 전달합니다.

```python
CommandError
UnknownCommandError
WrongNumberOfArgumentsError
```

서버/프로토콜 계층은 이 예외 메시지를 받아 `encode_error(...)`로 RESP 에러 응답을 생성합니다.

## 전체 흐름

```python
data = recv()
cmd = parse_resp(data)
result = handle_command(cmd, storage)
response = encode_resp(cmd, result)
send(response)
```

에러가 발생하면:

```python
try:
    result = handle_command(cmd, storage)
    response = encode_resp(cmd, result)
except CommandError as exc:
    response = encode_error(str(exc))
```

## 테스트 상태

- storage, command, integration 테스트에 EXPIRE 및 TTL 시나리오가 추가되어 있습니다.
- fake clock을 주입해 `sleep` 없이 만료 전후 동작을 검증합니다.
- 현재 테스트 기준으로 `SET -> EXPIRE -> GET`, 옵션별 `NX/XX/GT/LT`, `seconds <= 0` 즉시 삭제가 모두 검증됩니다.
