# Ticketing Command Spec

## 목적

이 문서는 앱 서버 팀이 Mini Redis 티켓팅 command를 바로 붙일 수 있도록 요청/응답 계약을 정리한 문서입니다.

전제:

- 모든 요청은 RESP Array로 전달합니다.
- 모든 응답은 RESP로 반환됩니다.
- 배열 응답은 순서가 곧 계약입니다.

## Seat Commands

### 1. RESERVE_SEAT

형식:

```text
RESERVE_SEAT event_id seat_id user_id ttl_seconds
```

의미:

- 좌석이 `AVAILABLE`이면 `HELD`로 전환
- 같은 유저가 다시 요청하면 TTL 갱신
- 다른 유저가 이미 hold 또는 confirm 상태면 실패

반환 구조:

```text
[success, state, user_id, ttl]
```

- `success`: `1` 또는 `0`
- `state`: `AVAILABLE | HELD | CONFIRMED`
- `user_id`: 현재 점유 유저, 없으면 nil
- `ttl`: 남은 초, 없으면 `-1`

예시:

```text
*5
$12
RESERVE_SEAT
$7
concert
$3
A-1
$6
user-1
$2
30
```

성공 응답:

```text
*4
:1
$4
HELD
$6
user-1
:30
```

실패 응답:

```text
*4
:0
$4
HELD
$6
user-1
:25
```

### 2. CONFIRM_SEAT

형식:

```text
CONFIRM_SEAT event_id seat_id user_id
```

의미:

- 해당 유저가 hold 중이면 confirmed로 전환
- 같은 유저의 중복 confirm은 성공으로 처리

반환 구조:

```text
[success, state, user_id, ttl]
```

성공 응답 예:

```text
*4
:1
$9
CONFIRMED
$6
user-1
:-1
```

### 3. RELEASE_SEAT

형식:

```text
RELEASE_SEAT event_id seat_id user_id
```

의미:

- 해당 유저가 hold 중이면 해제
- confirmed 좌석은 해제되지 않음

반환 구조:

```text
[success, state, user_id, ttl]
```

성공 응답 예:

```text
*4
:1
$9
AVAILABLE
$-1
:-1
```

### 4. SEAT_STATUS

형식:

```text
SEAT_STATUS event_id seat_id
```

반환 구조:

```text
[state, user_id, ttl]
```

예시:

```text
*3
$9
AVAILABLE
$-1
:-1
```

## Queue Commands

### 1. JOIN_QUEUE

형식:

```text
JOIN_QUEUE event_id user_id
```

반환 구조:

```text
[joined_flag, position, queue_length]
```

- `joined_flag`: 새로 들어갔으면 `1`, 이미 있었으면 `0`
- `position`: 현재 순번, 1-based
- `queue_length`: 전체 길이

예시:

```text
*3
:1
:2
:2
```

### 2. QUEUE_POSITION

형식:

```text
QUEUE_POSITION event_id user_id
```

반환 구조:

```text
[position, queue_length]
```

- 없으면 `position = -1`

### 3. POP_QUEUE

형식:

```text
POP_QUEUE event_id
```

반환 구조:

```text
[user_id_or_nil, remaining_length]
```

예시:

```text
*2
$6
user-1
:3
```

빈 큐:

```text
*2
$-1
:0
```

### 4. LEAVE_QUEUE

형식:

```text
LEAVE_QUEUE event_id user_id
```

반환 구조:

```text
[removed_flag, old_position, queue_length]
```

- 없으면 `removed_flag = 0`, `old_position = -1`

### 5. PEEK_QUEUE

형식:

```text
PEEK_QUEUE event_id
```

반환 구조:

```text
[user_id_or_nil, queue_length]
```

## 앱 서버 권장 흐름

### 좌석 예약

1. `QUEUE_POSITION` 또는 `PEEK_QUEUE`로 진입 가능 여부 판단
2. 진입 가능한 사용자는 `RESERVE_SEAT`
3. 결제/DB 저장 성공 시 `CONFIRM_SEAT`
4. 실패 시 `RELEASE_SEAT`

### 대기열

1. 사용자가 진입하면 `JOIN_QUEUE`
2. 주기적으로 `QUEUE_POSITION`
3. 앱 서버 또는 운영 로직이 `PEEK_QUEUE` 또는 `POP_QUEUE`로 다음 사용자 처리
4. 사용자가 나가면 `LEAVE_QUEUE`

## 에러 규칙

- 잘못된 command -> `-ERR unknown command ...`
- 인자 개수 오류 -> `-ERR wrong number of arguments ...`
- `RESERVE_SEAT` TTL이 정수가 아니면 -> `-ERR RESERVE_SEAT ttl_seconds must be an integer`
- `RESERVE_SEAT` TTL이 0 이하이면 -> `-ERR RESERVE_SEAT ttl_seconds must be a positive integer`
