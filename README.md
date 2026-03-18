# Mini Redis

Mini Redis는 Python으로 만든 작은 Redis 스타일의 in-memory 서버입니다. RESP 프로토콜을 사용하고, 여러 클라이언트 연결을 받되 실제 명령 실행은 single worker가 순차 처리합니다. 현재는 이 Redis와 SQLite 기반 DB API를 묶는 앱 서버도 함께 포함하고 있습니다.

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

앱 서버 HTTP API:

- `GET /events`
- `GET /events/{event_id}/seats`
- `GET /events/{event_id}/seats/{seat_id}`
- `GET /users/{user_id}/reservations`
- `POST /queue/join`
- `GET /queue/{event_id}/users/{user_id}/position`
- `POST /queue/leave`
- `GET /queue/{event_id}/peek`
- `POST /reservations/hold`
- `POST /reservations/{reservation_id}/confirm`
- `POST /reservations/{reservation_id}/cancel`
- `POST /reservations/purchase`

## 아키텍처

```text
Frontend / HTTP Client
        |
        v
Ticketing App Server (FastAPI)
        |                    |
        |                    +--> Ticketing DB API (FastAPI + SQLite)
        |
        +--> MiniRedisServer (TCP, RESP)
                    |
                    v
            SerialCommandExecutor
                    |
                    v
                StorageEngine
```

핵심 포인트:

- 클라이언트 연결은 여러 개 받을 수 있습니다.
- command 실행은 `SerialCommandExecutor` 한 곳에서만 수행됩니다.
- race condition을 storage lock보다 실행 모델로 줄이는 구조입니다.
- 필요하면 `--db-path` 옵션으로 SQLite snapshot 저장/복원을 켤 수 있습니다.
- 앱 서버는 Redis seat/queue command와 DB REST API를 오케스트레이션합니다.
- 결제는 실제 PG 연동 대신 `mock-pay`로 항상 승인 처리합니다.

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
- 만료는 background sweeper 없이 lazy expiration 방식입니다.
- snapshot 기능은 현재 메모리 상태를 SQLite에 저장하고 재시작 시 복원하는 선택 기능입니다.

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

상세 요청/응답 예시는 `docs/ticketing-command-spec.md`에 정리했습니다.

## Redis/DB 책임 분리

- 티켓팅 시연 기준으로 Redis는 빠르게 변하는 좌석 홀드, TTL, 대기열, 중복 요청 방지를 담당합니다.
- 최종 예약, 결제 결과, 사용자/좌석/이벤트 같은 영속 데이터는 별도 DB가 source of truth가 됩니다.
- 프론트는 직접 Redis에 붙지 않고 앱 서버 HTTP API만 호출하면 됩니다.
- DB 쪽 계약은 `docs/db-handoff.md`, Redis 연동 공유 문서는 `docs/redis-integration-handoff.md`에 정리했습니다.
- 권장 흐름은 `Redis RESERVE_SEAT -> 앱 서버 DB 처리 -> 성공 시 Redis CONFIRM_SEAT -> 실패 시 Redis RELEASE_SEAT` 입니다.
- SQLite snapshot 기능은 기본 저장소가 아니라 로컬 복구/실험용 선택 기능으로만 취급합니다.

## 앱 서버 역할

- `app_server/`는 프론트가 바라보는 단일 HTTP 진입점입니다.
- 좌석 조회 시 DB 좌석 마스터에 Redis의 `HELD` 상태를 overlay 해서 반환합니다.
- `POST /reservations/hold`는 Redis hold 성공 뒤 DB에 `HELD` 예약을 생성합니다.
- `POST /reservations/{reservation_id}/confirm`은 mock payment 승인 후 DB `CONFIRMED`, Redis `CONFIRM_SEAT` 순으로 처리합니다.
- `POST /reservations/purchase`는 hold + confirm을 한 번에 수행하는 간편 endpoint입니다.
- queue endpoint는 Redis queue command를 HTTP로 노출합니다.

Mini Redis 서버 실행:

```bash
py -3.12 server/server.py --db-path data/mini_redis.db --snapshot-interval 5
```

DB API 실행:

```bash
py -3.12 -m uvicorn ticketing_api.app:app --host 127.0.0.1 --port 8001
```

앱 서버 실행:

```bash
py -3.12 -m uvicorn app_server.app:app --host 127.0.0.1 --port 8000
```

Reconciler worker 실행:

```bash
py -3.12 -m scripts.reconciler --db-path data/ticketing.db --redis-host 127.0.0.1 --redis-port 6379 --interval-seconds 2
```

## 테스트

```bash
py -3.12 -m pytest -q
```

현재 테스트는 아래 범위를 포함합니다.

- RESP 파싱/인코딩
- 기본 key-value 및 TTL 동작
- single-worker 기반 동시성 처리
- 티켓팅 seat / queue 명령 흐름
- 선택적 SQLite snapshot 저장/복원
- DB 서비스 `ticketing_api/` 스키마와 예약 상태 전이
- 앱 서버의 Redis/DB orchestration 흐름과 mock payment 승인

## 프로젝트 구조

```text
mini-redis/
|- README.md
|- docs/
|  |- architecture.md
|  |- db-handoff.md
|  |- redis-integration-handoff.md
|  `- ticketing-command-spec.md
|- app_server/
|- ticketing_api/
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
|  |- sqlite_store.py
|  `- ttl.py
`- tests/
```
