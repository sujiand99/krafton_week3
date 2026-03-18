# Mini Redis

Mini Redis는 Python으로 Redis와 비슷한 in-memory key-value 저장소를 직접 만들어보는 하루짜리 팀 프로젝트입니다. 해시 테이블 기반 저장 구조를 구현하고, 요청과 응답은 RESP 프로토콜 흐름에 맞춰 처리하는 것이 목표입니다.

## MVP

- `SET key value`
- `GET key`
- `DEL key`

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
expire(key: str, seconds: int) -> bool
```

### Parser 출력

```python
["SET", "mykey", "123"]
["GET", "mykey"]
["DEL", "mykey"]
```

### Command Handler 계약

Command layer는 RESP 문자열을 직접 만들지 않습니다. 파싱된 명령을 해석하고 storage를 호출한 뒤, 순수 결과만 반환합니다.

```python
"OK"
"123"
None
1
0
```

- `SET key value` -> `"OK"`
- `GET key` -> `str | None`
- `DEL key` -> `1 | 0`
- 현재 MVP 지원 범위는 `SET`, `GET`, `DEL`
- `PING`, `EXPIRE`는 아직 지원하지 않음

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
response = encode_resp(result)
send(response)
```

에러가 발생하면:

```python
try:
    result = handle_command(cmd, storage)
    response = encode_resp(result)
except CommandError as exc:
    response = encode_error(str(exc))
```

## 현재 상태

기본 레포지토리 구조는 준비되어 있고, 각 역할별 기능은 개별 브랜치에서 병렬로 구현 중입니다. 현재 Command MVP 계약은 `commands/`에서 RESP를 만들지 않고 순수 결과만 반환하며, 에러는 예외로 상위 계층에 전달하는 방식으로 정리되어 있습니다.
