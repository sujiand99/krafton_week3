# Mini Redis

간단한 Redis 스타일 key-value 서버를 직접 구현하는 팀 프로젝트입니다.

## MVP

- `SET key value`
- `GET key`
- `DEL key`

## 레포 구조

```text
mini-redis/
├─ README.md
├─ .gitignore
├─ docs/
│  ├─ architecture.md
│  └─ meeting-notes.md
├─ server/
│  └─ server.py
├─ protocol/
│  ├─ resp_parser.py
│  └─ resp_encoder.py
├─ commands/
│  ├─ handler.py
│  └─ registry.py
├─ storage/
│  ├─ engine.py
│  ├─ hash_table.py
│  └─ ttl.py
├─ client/
│  └─ client.py
└─ tests/
   ├─ test_protocol.py
   ├─ test_storage.py
   ├─ test_commands.py
   └─ test_integration.py
```

## 브랜치 전략

- `main`: 항상 실행 가능한 최종 안정 버전
- `dev`: 기능 통합 브랜치
- 기능 브랜치
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

### Parser output

```python
["SET", "mykey", "123"]
["GET", "mykey"]
["DEL", "mykey"]
```

### Command handler output

RESP 응답 문자열로 통일합니다.

```text
+OK\r\n
$3\r\n123\r\n
$-1\r\n
:1\r\n
-ERR unknown command\r\n
```

## 작업 흐름

1. 기본 폴더 구조와 README를 `main`에 올립니다.
2. `dev` 브랜치를 생성합니다.
3. 각자 `dev`에서 기능 브랜치를 생성합니다.
4. 각자 작업 후 `dev`로 PR을 올립니다.
5. 리뷰 후 `dev`에 merge 합니다.
6. 마지막에 `dev`를 `main`에 반영합니다.

## 현재 상태

초기 프로젝트 골격만 세팅되어 있으며, 구현은 각 기능 브랜치에서 진행합니다.
