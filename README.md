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

## 발표용 요약

### 프로젝트 개요

저희 팀은 Python 내장 모듈을 활용해 Mini Redis를 직접 구현하고, 이를 콘서트 티켓팅 시나리오에 적용했습니다.

티켓팅 도메인을 선택한 이유는, 티켓 오픈 순간처럼 짧은 시간에 요청이 burst하게 몰리는 상황이야말로 Redis의 강점을 가장 잘 보여줄 수 있다고 생각했기 때문입니다. 저희는 빠르게 변하는 임시 상태는 Redis가, 최종 예약의 진실은 DB가 담당하도록 역할을 분리해 시스템을 설계했습니다.

### 핵심 아이디어

- Redis는 좌석 홀드, TTL, 대기열, 중복 요청 방지 같은 실시간 경쟁 제어를 담당합니다.
- DB는 사용자, 좌석, 예약, 결제 결과 같은 영속 데이터와 최종 예약 상태를 담당합니다.
- 즉, Redis는 빠르고 짧은 상태를 처리하고, DB는 최종 결과를 보존하는 구조입니다.

### 시스템 구조

클라이언트 요청은 TCP 소켓과 RESP 프로토콜을 통해 Mini Redis 서버로 들어옵니다.

전체 흐름은 다음과 같습니다.

1. 클라이언트가 RESP 형식으로 요청을 전송합니다.
2. 서버는 요청을 파싱해 command layer로 전달합니다.
3. command는 storage를 호출해 결과를 생성합니다.
4. 서버는 그 결과를 다시 RESP 형식으로 인코딩해 응답합니다.
5. 상위 Ticketing App Server는 Redis와 DB를 오케스트레이션하여 최종 서비스 흐름을 구성합니다.

또한 동시성 문제를 줄이기 위해 single worker 기반 직렬 실행 구조를 사용하여, 여러 요청이 들어와도 실제 명령 실행은 순차적으로 처리되도록 설계했습니다.

### 구현 기능

기본 Redis 기능:

- `SET`
- `GET`
- `DEL`
- `EXPIRE`
- `TTL`

티켓팅 도메인 기능:

- `RESERVE_SEAT`
- `CONFIRM_SEAT`
- `RELEASE_SEAT`
- `SEAT_STATUS`

대기열 기능:

- `JOIN_QUEUE`
- `QUEUE_POSITION`
- `POP_QUEUE`
- `LEAVE_QUEUE`
- `PEEK_QUEUE`

### 좌석 상태 모델

좌석은 다음 3가지 상태로 관리됩니다.

- `AVAILABLE`: 아직 누구도 점유하지 않은 좌석
- `HELD`: 사용자가 임시로 선점한 좌석
- `CONFIRMED`: 결제와 예약이 완료된 최종 좌석

사용자가 좌석을 선택하면 바로 확정되는 것이 아니라, 먼저 `HELD` 상태가 되고 TTL이 설정됩니다. 결제가 성공했을 때만 `CONFIRMED`로 전환되며, 결제하지 않고 시간이 지나면 다시 `AVAILABLE`로 돌아갑니다.

### TTL 및 상태 보정

저희는 TTL 처리를 위해 lazy expiration 방식을 사용했습니다. 즉, 별도의 background sweeper가 아니라 key에 접근하는 시점에 만료 여부를 확인하고 정리합니다.

또한 티켓팅 도메인에서는 stale `HELD` 상태가 남지 않도록 reconciler를 두어 DB와 Redis 상태를 다시 맞추도록 했습니다. 즉 Redis는 빠른 임시 상태를 처리하고, DB는 최종 예약을 기록하며, 두 계층 사이의 불일치는 보정 작업으로 정리합니다.

### 시연 시나리오

시연에서는 다음 흐름을 보여줍니다.

1. 사용자가 좌석을 선택하면 Redis에서 즉시 `HELD` 상태가 됩니다.
2. 같은 좌석을 다른 사용자가 선택하려 하면 즉시 실패합니다.
3. 시간이 지나 TTL이 만료되면 좌석은 다시 `AVAILABLE`로 돌아갑니다.
4. 결제가 성공하면 DB에 먼저 예약이 기록되고, 이후 Redis 상태가 `CONFIRMED`로 전환됩니다.
5. 프런트의 `Run simulation` 버튼을 통해 여러 사용자가 좌석과 대기열에 동시에 접근하는 티켓팅 혼잡 상황을 자동으로 재현합니다.

즉 시연의 핵심은 빠른 좌석 선점, 중복 요청 차단, TTL 만료 처리, 자동 시뮬레이션 기반 혼잡 상황 재현, DB 최종 확정입니다.

### 테스트 및 검증

저희는 `pytest` 기반으로 다음 항목을 검증했습니다.

- RESP parser / encoder 단위 테스트
- storage 및 TTL 동작 테스트
- command layer 테스트
- ticketing API 테스트
- high-contention 시나리오 테스트

즉 단순 구현에 그치지 않고, 실제로 요청이 몰리는 상황과 엣지 케이스까지 고려하여 안정성을 확인했습니다.

### 결론

이 프로젝트는 단순한 key-value 저장소 구현을 넘어서, 티켓팅처럼 짧은 순간에 트래픽이 몰리는 환경에서 Redis를 실시간 임시 상태 제어에 활용하고, DB와 역할을 분리해 최종 일관성을 유지하는 구조를 구현한 결과물입니다.
