# Mini Redis

Mini Redis는 Python으로 만든 작은 Redis 스타일의 in-memory key-value 서버입니다.
현재 구현은 RESP 프로토콜을 사용하고, 여러 클라이언트 접속을 허용하지만 명령 실행은 single worker가 순차 처리합니다.

## 현재 지원 기능

- `SET key value`
- `GET key`
- `DEL key`
- `EXPIRE key seconds [NX | XX | GT | LT]`
- `TTL key`

## 현재 아키텍처

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

## 구성 요소 설명

### 1. App Server / Client

이 저장소에 별도 웹 애플리케이션 서버가 있는 것은 아닙니다.
여기서 App Server는 Mini Redis에 TCP 요청을 보내는 외부 애플리케이션 또는 테스트 클라이언트를 뜻합니다.

역할:

- TCP 연결 생성
- RESP 형식으로 명령 전송
- RESP 응답 수신

### 2. Mini Redis Server

`server/server.py`의 `MiniRedisServer`가 TCP 서버입니다.

역할:

- 여러 클라이언트 연결 수락
- 클라이언트별 소켓 읽기 처리
- RESP 요청 파싱
- 파싱된 명령을 worker queue에 전달
- worker 결과를 RESP 응답으로 인코딩해 반환

특징:

- 연결은 동시에 여러 개 받을 수 있습니다.
- 명령 실행은 worker 하나가 순차 처리합니다.

### 3. Worker

`server/executor.py`의 `SerialCommandExecutor`가 단일 worker 역할을 합니다.

역할:

- 클라이언트 스레드가 넣은 명령을 queue에서 하나씩 꺼냄
- `handle_command(...)`를 worker 하나에서만 실행
- 결과 또는 예외를 요청한 클라이언트 처리 흐름으로 돌려줌

의도:

- Redis의 single-threaded command execution 모델에 가깝게 동작
- storage 레이어에 별도 read/write lock을 두지 않고도 실행 순서를 직렬화
- 여러 클라이언트가 동시에 요청해도 race condition 가능성을 줄임

### 4. Command Layer

`commands/handler.py`

역할:

- 명령어 이름 검증
- 인자 개수 검증
- storage API 호출
- 순수 결과 반환

반환 예:

```python
"OK"
"123"
None
1
0
-1
-2
```

RESP 문자열 생성은 command layer가 아니라 server/protocol layer가 담당합니다.

### 5. Storage Layer

`storage/engine.py`

현재 저장 구조:

```python
@dataclass(slots=True)
class Entry:
    value: str
    expires_at: float | None = None
```

실제 저장소:

```python
dict[str, Entry]
```

의미:

- 값과 TTL 메타데이터를 한 구조에 함께 보관
- 추후 TTL 관련 기능 확장을 쉽게 하기 위한 구조
- 현재는 single worker가 storage를 소유한다고 가정

## 요청 처리 흐름

1. 클라이언트가 TCP로 서버에 연결합니다.
2. RESP 요청을 보냅니다.
3. `MiniRedisServer`가 요청을 읽고 RESP 프레임으로 파싱합니다.
4. 파싱된 명령을 `SerialCommandExecutor` queue에 넣습니다.
5. worker가 명령을 하나 꺼내 `handle_command(...)`를 실행합니다.
6. `StorageEngine`이 값을 읽거나 수정합니다.
7. 결과를 RESP 응답으로 인코딩해 클라이언트에 돌려줍니다.

## Storage 인터페이스

```python
set(key: str, value: str) -> None
get(key: str) -> str | None
delete(key: str) -> bool
expire(key: str, seconds: int, option: str | None = None) -> bool
ttl(key: str) -> int
```

## TTL 동작

- TTL은 `Entry.expires_at`에 저장됩니다.
- 만료 정리는 background sweeper가 아니라 key 접근 시점의 lazy expiration 방식입니다.
- `SET`은 기존 TTL을 제거하고 persistent key로 다시 저장합니다.
- `DEL`은 값과 TTL 메타데이터를 함께 제거합니다.
- `TTL` 반환 규칙:
  - key 없음 -> `-2`
  - key는 있지만 TTL 없음 -> `-1`
  - key가 살아 있으면 남은 초 반환

## 프로젝트 구조

```text
mini-redis/
|- README.md
|- .gitignore
|- docs/
|  |- architecture.md
|  `- meeting-notes.md
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
|- client/
|  `- client.py
`- tests/
   |- test_commands.py
   |- test_executor.py
   |- test_integration.py
   |- test_protocol.py
   `- test_storage.py
```

## 실행

서버 실행:

```bash
py -3.12 server/server.py
```

## 테스트

전체 테스트 실행:

```bash
py -3.12 -m pytest -q
```

현재 테스트 범위:

- protocol 파싱/인코딩
- command 처리
- storage 및 TTL 동작
- executor 단일 worker 직렬화
- 여러 클라이언트 동시 접속 integration
