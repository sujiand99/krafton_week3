# Redis Integration Handoff

## 목적

이 문서는 현재 구현된 DB 서비스 기준으로 Redis 구현 팀이 바로 연동할 수 있도록
DB 쪽 계약을 정리한 문서입니다.

핵심 원칙:

- Redis는 좌석 홀드, TTL, 대기열, 중복 요청 방지를 담당
- DB는 최종 예약/결제/사용자/좌석 영속 데이터를 담당
- 최종 source of truth는 DB
- 좌석 확정 순서는 반드시 `Redis 홀드 성공 -> DB 저장 성공 -> Redis 확정`

## 현재 구현된 DB 서비스

- 패키지: `ticketing_api/`
- 서버 엔트리포인트: `ticketing_api/app.py`
- 기본 DB 파일: `data/ticketing.db`
- 시드 스크립트: `ticketing_api/seed_demo.py`

DB 서비스는 Redis를 직접 호출하지 않습니다.
앱 서버가 Redis 결과를 받아 DB API를 호출하는 구조를 전제로 합니다.

## 상태 모델

### 예약 상태

- `HELD`
- `CONFIRMED`
- `CANCELLED`
- `EXPIRED`

### 좌석 상태

- `AVAILABLE`
- `CONFIRMED`

주의:

- DB는 `AVAILABLE` 좌석을 row로 저장하지 않습니다.
- `AVAILABLE`은 좌석 마스터는 존재하지만 `CONFIRMED` 예약이 없는 상태를 뜻합니다.
- `HELD`는 reservations 테이블에 저장됩니다.

## DB 스키마 요약

### events

- `event_id`
- `title`
- `venue`
- `starts_at`
- `booking_opens_at`
- `created_at`

### seats

- `(event_id, seat_id)` 복합 PK
- `seat_label`
- `section`
- `row_label`
- `seat_number`
- `price`
- `created_at`

### users

- `user_id`
- `display_name`
- `email`
- `created_at`

### reservations

- `reservation_id` PK
- `event_id`
- `seat_id`
- `user_id`
- `status`
- `hold_token`
- `expires_at`
- `created_at`
- `updated_at`
- `confirmed_at`
- `cancelled_at`

제약:

- `reservation_id` 유니크
- `hold_token` 유니크 nullable
- 같은 `(event_id, seat_id)`에 대해 `status='CONFIRMED'`는 1건만 허용

### payments

- `payment_id`
- `reservation_id` 유니크 FK
- `status`
- `amount`
- `provider`
- `provider_ref`
- `created_at`
- `updated_at`

## Redis 팀이 알아야 할 API 계약

### 1. 홀드 성공 후 DB에 HELD 생성

`POST /reservations/held`

요청:

```json
{
  "reservation_id": "res-100",
  "event_id": "concert-seoul-2026",
  "seat_id": "A1",
  "user_id": "user-1",
  "hold_token": "hold-100",
  "expires_at": "2026-03-19T11:05:00Z"
}
```

동작:

- 이벤트, 좌석, 사용자 존재 확인
- 같은 `reservation_id`로 동일 payload 재호출 시 idempotent 성공
- 같은 `reservation_id`인데 payload가 다르면 `409`
- 이미 같은 좌석이 `CONFIRMED`면 `409`
- 성공 시 `HELD` row 생성

응답:

- 신규 생성: `201`
- idempotent 재호출: `200`

### 2. 결제 성공 후 DB에서 CONFIRMED 처리

`POST /reservations/{reservation_id}/confirm`

요청:

```json
{
  "payment_id": "pay-100",
  "amount": 120000,
  "provider": "demo-pay",
  "provider_ref": "demo-pay-100"
}
```

동작:

- `HELD -> CONFIRMED`
- payment row를 `SUCCEEDED`로 저장
- 이미 같은 payment payload로 확정된 경우 idempotent 성공
- 다른 좌석 확정과 충돌하면 `409`

중요:

- 이 API는 Redis가 이미 홀드를 성공시킨 뒤에만 호출해야 합니다.
- DB가 `200`으로 성공한 뒤 Redis에서 `CONFIRM_SEAT` 같은 확정 처리를 해야 합니다.

### 3. 결제 실패 또는 사용자 취소

`POST /reservations/{reservation_id}/cancel`

요청 예시:

```json
{
  "payment_id": "pay-100",
  "payment_status": "FAILED",
  "amount": 120000,
  "provider": "demo-pay",
  "provider_ref": "demo-pay-100"
}
```

또는 payment 정보 없이 빈 JSON `{}` 도 허용됩니다.

동작:

- `HELD -> CANCELLED`
- 필요하면 payment 상태를 `FAILED` 또는 `CANCELLED`로 저장
- 이미 `CANCELLED`면 idempotent 성공
- `CONFIRMED` 상태에는 적용되지 않음

Redis 팀 관점:

- DB 취소가 성공한 뒤 Redis에서 좌석을 다시 `AVAILABLE`로 풀어야 합니다.

### 4. TTL 만료 후 EXPIRED 처리

`POST /reservations/{reservation_id}/expire`

동작:

- `HELD -> EXPIRED`
- 이미 `EXPIRED`면 idempotent 성공
- `CONFIRMED`에는 적용되지 않음

Redis 팀 관점:

- Redis TTL 만료가 실제로 발생했을 때 후속 기록용으로 호출하면 됩니다.
- DB가 TTL을 직접 계산하거나 polling하지는 않습니다.

### 5. 복구/조회용 API

`GET /events/{event_id}/confirmed-seats`

- Redis 재구성용
- 특정 이벤트의 `CONFIRMED` 좌석만 반환

`GET /users/{user_id}/reservations`

- 사용자 예약 조회용

`GET /events/{event_id}/seats`

- 좌석 마스터 + 현재 DB 기준 `AVAILABLE/CONFIRMED` 상태 조회

## HTTP 규약

- `200`: 정상 처리 또는 idempotent 재반환
- `201`: 신규 `HELD` 생성
- `404`: 이벤트/좌석/사용자/예약 없음
- `409`: 상태 전이 불가, 좌석 확정 충돌, idempotency 충돌

에러 응답 형태:

```json
{
  "detail": "..."
}
```

## Redis 팀이 맞춰야 할 흐름

### 권장 성공 흐름

1. Redis에서 좌석 홀드 성공
2. 앱 서버가 `POST /reservations/held`
3. 결제 성공
4. 앱 서버가 `POST /reservations/{reservation_id}/confirm`
5. DB 성공 응답 확인
6. Redis에서 좌석 확정 처리

### 실패/취소 흐름

1. Redis에서 홀드 성공
2. DB에 `HELD` 생성
3. 결제 실패 또는 사용자 취소
4. 앱 서버가 `POST /reservations/{reservation_id}/cancel`
5. DB 성공 응답 확인
6. Redis에서 좌석 해제

### TTL 만료 흐름

1. Redis 홀드 TTL 만료
2. 앱 서버 또는 후속 작업이 `POST /reservations/{reservation_id}/expire`
3. DB에 만료 흔적 저장

## 현재 데모 데이터

시드 스크립트 실행 시:

- 이벤트: `concert-seoul-2026`
- 사용자:
  - `user-1`
  - `user-2`
  - `user-3`
- 좌석:
  - `A1` ~ `A8`
  - `B1` ~ `B8`

Redis 키 네이밍은 handoff 문서 기준대로 아래 형식을 권장합니다.

```text
seat:{event_id}:{seat_id}
```

예:

```text
seat:concert-seoul-2026:A1
```

## Redis 팀에 특히 중요한 포인트

- DB는 Redis 홀드 성공 여부를 알지 못하므로, 홀드 성공 후에만 `/reservations/held`를 호출해야 합니다.
- DB가 `CONFIRMED`를 반환한 뒤 Redis 확정이 실패할 수 있으므로, Redis 쪽에는 재시도 또는 재구성 전략이 필요합니다.
- 중복 결제 콜백이나 중복 요청은 `reservation_id`와 `CONFIRMED` 좌석 유니크 제약으로 일부 방어됩니다.
- `hold_token`은 DB에 저장되므로 Redis 홀드와 DB row 연결에 사용할 수 있습니다.

## 아직 구현되지 않은 것

- Redis 명령 자체 (`RESERVE_SEAT`, `CONFIRM_SEAT`, `RELEASE_SEAT`, `SEAT_STATUS`, `JOIN_QUEUE`, `QUEUE_POSITION`)
- Redis와 DB를 묶는 앱 서버 오케스트레이션
- 실제 결제사 연동
- 인증/권한 처리

## db-handoff.md 기준 진행 현황

### 완료

- DB 서비스 패키지 `ticketing_api/` 구현 완료
- SQLite 기반 DB 스키마 구현 완료
  - `events`
  - `seats`
  - `users`
  - `reservations`
  - `payments`
- `reservations(event_id, seat_id, user_id, status, reservation_id)` 기준 상태 전이 구현 완료
- 예약 상태 `HELD`, `CONFIRMED`, `CANCELLED`, `EXPIRED` 구현 완료
- `reservation_id` 기준 idempotency 처리 구현 완료
- `(event_id, seat_id)`에 대한 `CONFIRMED` 1건 제약 구현 완료
- Redis 연동용 DB API 구현 완료
  - `POST /reservations/held`
  - `POST /reservations/{reservation_id}/confirm`
  - `POST /reservations/{reservation_id}/cancel`
  - `POST /reservations/{reservation_id}/expire`
  - `GET /events/{event_id}/confirmed-seats`
  - `GET /users/{user_id}/reservations`
  - `GET /events/{event_id}/seats`
- 데모용 시드 데이터 구현 완료
  - 이벤트 `concert-seoul-2026`
  - 좌석 `A1~A8`, `B1~B8`
  - 사용자 `user-1~3`
- 테스트 검증 완료
  - 현재 전체 테스트 기준 `98 passed`

### 부분 완료

- 결제 실패/취소 처리
  - DB 상태 전이와 payment 상태 저장은 구현됨
  - 실제 PG사 연동은 없음
- 실패 복구 전략
  - Redis 재구성용 `GET /events/{event_id}/confirmed-seats` API는 구현됨
  - 자동 재시도 로직이나 관리자 복구 스크립트는 아직 없음
- Redis 만료 후 DB 흔적 남기기
  - `POST /reservations/{reservation_id}/expire`로 `EXPIRED` 전이는 구현됨
  - 별도 감사 로그 테이블은 아직 없음

### 아직 미구현

- Redis와 DB를 묶는 앱 서버 오케스트레이션
  - 현재는 Redis 성공 후 앱 서버가 DB API를 호출하는 구조만 정의되어 있음
  - 실제로 Redis와 DB를 순서대로 호출하는 중간 서버는 아직 없음
- Redis 명령 자체
  - `RESERVE_SEAT`
  - `CONFIRM_SEAT`
  - `RELEASE_SEAT`
  - `SEAT_STATUS`
  - `JOIN_QUEUE`
  - `QUEUE_POSITION`
- 실제 결제사 연동
- 인증/권한 처리
- 관리자용 복구 스크립트

### Redis 팀이 바로 연동해도 되는 범위

- Redis 홀드 성공 후 `POST /reservations/held` 호출
- 결제 성공 후 `POST /reservations/{reservation_id}/confirm` 호출
- 결제 실패/취소 후 `POST /reservations/{reservation_id}/cancel` 호출
- TTL 만료 후 `POST /reservations/{reservation_id}/expire` 호출
- Redis 재구성 필요 시 `GET /events/{event_id}/confirmed-seats` 사용

### Redis 팀이 아직 기다려야 하는 범위

- Redis와 DB를 자동으로 이어주는 앱 서버 구현
- 결제 시스템 실제 연동
- 운영/복구 자동화 도구
