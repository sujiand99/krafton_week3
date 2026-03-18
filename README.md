# Mini Redis

Mini Redis는 Python으로 만든 작은 Redis 스타일의 in-memory 서버입니다.
현재 구현은 RESP 프로토콜을 사용하고, 여러 클라이언트 연결을 받을 수 있지만 실제 명령 실행은 single worker가 순차 처리합니다.

## 현재 구현 범위

기본 command:

- `SET key value`
- `GET key`
- `DEL key`
- `EXPIRE key seconds [NX | XX | GT | LT]`
- `TTL key`

티켓팅용 command:

- `RESERVE_SEAT event_id seat_id user_id ttl_seconds`
- `CONFIRM_SEAT event_id seat_id user_id`
- `RELEASE_SEAT event_id seat_id user_id`
- `SEAT_STATUS event_id seat_id`
- `JOIN_QUEUE event_id user_id`
- `QUEUE_POSITION event_id user_id`
- `POP_QUEUE event_id`
- `LEAVE_QUEUE event_id user_id`
- `PEEK_QUEUE event_id`

## 아키텍처

```text
App Server / Client
        |
        v
MiniRedisServer (TCP, RESP parsing)
        |
        v
SerialCommandExecutor (single worker)
        |
        v
Command Handler
        |
        v
StorageEngine (dict[str, Entry])
```

핵심 포인트:

- 클라이언트 연결은 여러 개 받을 수 있습니다.
- command 실행은 `SerialCommandExecutor` 한 곳에서만 수행됩니다.
- race condition을 storage lock보다 실행 모델로 줄이는 구조입니다.

## 저장 구조

`storage/engine.py`

```python
@dataclass(slots=True)
class Entry:
    value: str
    expires_at: float | None = None
```

- 일반 key-value 값과 TTL 메타데이터를 함께 관리합니다.
- 티켓팅 seat 상태와 queue도 storage 안에서 관리합니다.
- 만료는 background worker 없이 lazy expiration 방식입니다.

## 티켓팅 상태 모델

seat 상태:

- `AVAILABLE`
- `HELD`
- `CONFIRMED`

의미:

- `AVAILABLE`: 아직 누구도 선점하지 않은 좌석
- `HELD`: 특정 유저가 TTL과 함께 임시 선점한 좌석
- `CONFIRMED`: 최종 확정된 좌석

## 티켓팅 command 요약

### Seat

`RESERVE_SEAT event_id seat_id user_id ttl_seconds`

- 좌석이 비어 있으면 hold 생성
- 같은 유저가 다시 요청하면 hold TTL 갱신
- 다른 유저가 이미 hold 또는 confirm 상태면 실패
- 반환: `[success, state, user_id, ttl]`

`CONFIRM_SEAT event_id seat_id user_id`

- 해당 유저가 hold 중인 좌석을 confirmed로 전환
- 같은 유저의 중복 confirm은 idempotent하게 성공 처리
- 반환: `[success, state, user_id, ttl]`

`RELEASE_SEAT event_id seat_id user_id`

- 해당 유저가 hold 중인 좌석을 해제
- 반환: `[success, state, user_id, ttl]`

`SEAT_STATUS event_id seat_id`

- 현재 좌석 상태 조회
- 반환: `[state, user_id, ttl]`

### Queue

`JOIN_QUEUE event_id user_id`

- 대기열 맨 뒤에 유저 추가
- 이미 들어가 있으면 중복 삽입하지 않고 기존 위치 반환
- 반환: `[joined_flag, position, queue_length]`

`QUEUE_POSITION event_id user_id`

- 현재 유저의 대기 순번 조회
- 없으면 position은 `-1`
- 반환: `[position, queue_length]`

`POP_QUEUE event_id`

- 맨 앞 유저를 꺼냄
- 반환: `[user_id_or_nil, remaining_length]`

`LEAVE_QUEUE event_id user_id`

- 특정 유저를 대기열에서 제거
- 반환: `[removed_flag, old_position, queue_length]`

`PEEK_QUEUE event_id`

- 맨 앞 유저를 제거하지 않고 확인
- 반환: `[user_id_or_nil, queue_length]`

상세 요청/응답 예시는 [docs/ticketing-command-spec.md](C:\Users\haeli\Documents\codex_project7\krafton_week3\docs\ticketing-command-spec.md)에 정리했습니다.

## DB 연동 경계

Redis와 DB 책임 분리는 [docs/db-handoff.md](C:\Users\haeli\Documents\codex_project7\krafton_week3\docs\db-handoff.md)에 정리했습니다.

권장 흐름:

1. Redis `RESERVE_SEAT`
2. 앱 서버에서 결제/DB 처리
3. 성공 시 Redis `CONFIRM_SEAT`
4. 실패 시 Redis `RELEASE_SEAT`

## 프로젝트 구조

```text
mini-redis/
|- README.md
|- docs/
|  |- architecture.md
|  |- db-handoff.md
|  `- ticketing-command-spec.md
|- server/
|  |- executor.py
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
`- tests/
   |- test_commands.py
   |- test_executor.py
   |- test_integration.py
   |- test_protocol.py
   `- test_storage.py
```

## 실행

```bash
py -3.12 server/server.py
```

## 테스트

```bash
py -3.12 -m pytest -q
```

현재 기준 테스트 결과:

- `111 passed`
