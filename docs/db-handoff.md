# Ticketing DB Handoff

## 목적

이 문서는 티켓팅 시연을 위해 Redis 계층과 DB 계층의 책임 경계를 맞추기 위한 전달 문서입니다.
현재 Redis 서버는 single worker 기반으로 명령을 순차 실행합니다.
따라서 "좌석 선점", "중복 요청 방지", "대기열", "짧은 TTL 기반 상태"는 Redis가 맡고,
"최종 예매 내역", "결제 결과", "영속 데이터"는 DB가 맡는 구조를 기준으로 합니다.

## 역할 분리

### Redis가 맡을 것

- 빠른 좌석 점유 상태
- 임시 홀드 상태와 만료
- 대기열
- 중복 요청 방지 토큰
- 짧은 수명의 예약 세션 상태

### DB가 맡을 것

- 이벤트 정보
- 좌석 마스터 데이터
- 사용자 정보
- 최종 예약 레코드
- 결제 성공/실패 결과
- 감사용 영속 로그가 필요하면 그 부분도 DB

## 추천 예약 상태 모델

DB와 Redis가 같은 상태 이름을 쓰면 협업이 편합니다.

- `AVAILABLE`
- `HELD`
- `CONFIRMED`
- `CANCELLED`
- `EXPIRED`

설명:

- `AVAILABLE`: 아직 누구도 잡지 않은 좌석
- `HELD`: Redis에서 임시 선점 중인 상태
- `CONFIRMED`: DB에 최종 예매 완료
- `CANCELLED`: 사용자 취소 또는 결제 실패 후 해제
- `EXPIRED`: 홀드 TTL 만료

## 기본 처리 흐름

### 1. 좌석 선점

1. 앱 서버가 Redis에 좌석 선점 명령을 보냄
2. Redis가 해당 좌석이 비어 있으면 `HELD`로 전환하고 TTL 설정
3. 앱 서버는 선점 성공 응답을 받으면 결제/주문 생성 단계로 이동

이 단계에서는 DB에 아직 최종 예매 확정을 쓰지 않아도 됩니다.
원하면 "결제 진행 중" 상태의 임시 주문은 DB에 만들 수 있습니다.

### 2. 결제 성공 후 확정

1. 앱 서버가 DB에 최종 예약 레코드 저장
2. DB 저장이 성공하면 Redis에 좌석 확정 명령 호출
3. Redis에서 `HELD -> CONFIRMED` 상태로 전환

중요:

- DB 저장 성공 전에 Redis만 `CONFIRMED`로 바꾸면 안 됩니다.
- 데모 기준으로는 "DB 성공 후 Redis 확정" 순서를 추천합니다.

### 3. 결제 실패 또는 취소

1. 앱 서버가 DB 실패 또는 결제 실패를 인지
2. Redis에 홀드 해제 명령 호출
3. 좌석 상태를 다시 `AVAILABLE`로 전환

### 4. TTL 만료

1. Redis에 잡혀 있던 홀드가 만료
2. 좌석은 다시 예약 가능 상태로 복귀
3. DB에는 필요하면 만료 이력만 남기고, 최종 예약 레코드는 만들지 않음

## DB 팀원에게 필요한 테이블/엔티티

최소 기준:

- `events`
- `seats`
- `users`
- `reservations`
- `payments` 또는 결제 상태 테이블

### reservations 추천 필드

- `reservation_id`
- `event_id`
- `seat_id`
- `user_id`
- `status`
- `created_at`
- `updated_at`
- `confirmed_at` nullable
- `cancelled_at` nullable
- `hold_token` nullable

설명:

- `hold_token`은 Redis 홀드와 DB 예약 흐름을 연결할 때 유용합니다.
- 데모에서는 `reservation_id`만으로도 충분할 수 있지만, 중복 요청 방지를 위해 token이 있으면 편합니다.

## Redis 쪽에서 준비할 예정인 도메인 기능

아래는 Redis 계층에서 우선 구현 후보입니다.
DB 팀원은 이 명령 결과를 받아 어떤 DB 저장을 할지 맞춰주면 됩니다.

- `RESERVE_SEAT event_id seat_id user_id ttl_seconds`
- `CONFIRM_SEAT event_id seat_id user_id`
- `RELEASE_SEAT event_id seat_id user_id`
- `SEAT_STATUS event_id seat_id`
- `JOIN_QUEUE event_id user_id`
- `QUEUE_POSITION event_id user_id`

## 권장 데이터 계약

DB 팀원과 아래 계약을 맞추면 구현이 쉬워집니다.

### 앱 서버가 Redis에 기대하는 것

- 좌석 선점 성공/실패를 즉시 판단 가능
- 홀드 TTL 확인 가능
- 특정 좌석이 누가 잡고 있는지 확인 가능

### 앱 서버가 DB에 기대하는 것

- 최종 예매 저장 성공/실패 응답
- 이미 확정된 좌석인지 확인 가능한 조회
- 사용자 기준 예약 조회

## 꼭 맞춰야 하는 포인트

### 1. 최종 진실의 원천

- 최종 예매 상태의 source of truth는 DB
- 짧은 시간의 경쟁 제어와 속도는 Redis

### 2. 키 충돌 방지

Redis 키와 DB 컬럼 naming을 맞추면 디버깅이 편합니다.

추천:

- Redis key: `seat:{event_id}:{seat_id}`
- DB columns: `event_id`, `seat_id`

### 3. idempotency

앱 서버나 결제 콜백은 중복 호출될 수 있습니다.
DB 저장 쪽도 아래 기준을 고려해 주세요.

- 같은 `reservation_id` 재요청 시 중복 insert 방지
- 같은 `(event_id, seat_id)`에 대해 최종 확정은 1건만 허용

### 4. 실패 복구

DB 저장은 성공했는데 Redis 확정이 실패한 경우를 대비해야 합니다.
데모 단계에서는 아래 중 하나면 충분합니다.

- 앱 서버가 재시도
- 시작 시 DB 기준으로 Redis 상태 재구성
- 관리자용 복구 스크립트 준비

## 팀원에게 바로 전달할 요약

아래 문장을 그대로 전달해도 됩니다.

> Redis는 좌석 홀드, TTL, 대기열, 중복 요청 방지를 담당하고,
> DB는 최종 예약/결제/사용자/좌석 영속 데이터를 담당합니다.
> 좌석 확정은 "Redis 홀드 성공 -> 결제/DB 저장 성공 -> Redis 확정" 순서로 맞추고 싶습니다.
> DB 쪽에서는 `reservations(event_id, seat_id, user_id, status, reservation_id)` 기준으로
> 중복 확정 방지와 상태 전이 처리가 가능하면 됩니다.

## 지금 DB 팀원에게 확인받아야 할 질문

- 최종 예약의 unique key를 무엇으로 둘지
- 결제 성공 전 임시 주문 row를 만들지
- 좌석 마스터는 DB에서만 관리할지
- Redis 만료 후 DB에 어떤 흔적을 남길지
- 데모에서는 결제 실패/취소를 어떤 수준까지 보여줄지
