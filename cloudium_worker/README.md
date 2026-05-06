# Cloudium Worker

`excel_rename_gui_v2.exe` — Cloudium permission gate worker.

## 목적

이 프로세스가 떠 있어야 backend가 Cloudium 경로의 파일을 read 할 수 있다.
backend는 `tasklist`/`psutil`로 이 exe의 실행 여부를 검사하며, 실행 중일 때만
`CloudiumFileResolver`가 read를 허용한다.

## 빌드

```bash
# .venv (CPython 3.12 권장) 활성 후
pip install pyinstaller

python -m PyInstaller \
    --onefile --name excel_rename_gui_v2 \
    --distpath dist \
    --workpath build/pyinstaller \
    --specpath build/pyinstaller \
    --console --clean --noconfirm \
    cloudium_worker/dummy.py
```

산출물: `dist/excel_rename_gui_v2.exe` (약 7 MB single-file).

## 실행

```cmd
dist\excel_rename_gui_v2.exe              # idle 모드 — Ctrl+C까지 대기
dist\excel_rename_gui_v2.exe --pid        # PID 출력 후 즉시 종료 (테스트용)
dist\excel_rename_gui_v2.exe --child cmd  # cmd를 자식 프로세스로 spawn (자식 상속 검증용)
```

## 보안 정책 (W6)

worker TCP server는 기본적으로 **loopback(127.0.0.1, ::1)에서 들어온 요청만 처리**한다.
다른 PC가 LAN에서 worker port에 직접 connect해 임의 path를 read 시도하는 것을 차단.

LAN 노출이 필요하면 명시적으로 opt-in:

```cmd
set CLOUDIUM_WORKER_ALLOW_LAN=1
dist\excel_rename_gui_v2.exe
```

backend가 다른 PC에 있는 시나리오에서만 사용. 기본은 같은 PC backend ↔ worker 가정.

환경 변수:
- `CLOUDIUM_WORKER_HOST` — bind host (default `127.0.0.1`)
- `CLOUDIUM_WORKER_PORT` — bind port (default `8765`)
- `CLOUDIUM_WORKER_ALLOW_LAN` — `1`이면 비-loopback IP 허용

## 검증 시나리오

### 1. backend 게이트 detect 확인 (로컬)

```bash
# exe 실행
dist/excel_rename_gui_v2.exe &

# backend가 게이트 ON으로 detect하는지
curl -X POST http://127.0.0.1:9000/api/file-mode/check-access \
    -H "Content-Type: application/json" -d '{}'
# → "gate_running": true 기대
```

### 2. 실제 Cloudium 권한 검증 (사용자 환경)

이 exe가 진짜 Cloudium 시스템에서 권한을 부여받는지는 사용자의 Cloudium 환경에서만
검증 가능. 절차:

1. `excel_rename_gui_v2.exe`를 Cloudium 클라이언트 PC에서 실행
2. backend `/api/file-mode` POST로 cloudium 모드 + Cloudium 경로 prefix 등록
   ```json
   {"mode":"cloudium",
    "allowed_prefixes":"//cloudium-server/share/proj",
    "gate_process":"excel_rename_gui_v2.exe"}
   ```
3. 그 경로의 파일 read 시도
4. **자식 상속 모델 검증** — 자식 상속이 진짜라면 backend(별도 python 프로세스)가
   Cloudium 경로 read 가능. 실패한다면 worker IPC 모델로 전환 필요 (옵션 A).

### 3. 자식 상속 명시 검증 (옵션)

backend 자체를 worker 자식으로 spawn해 권한 강제 상속 시도:

```cmd
dist\excel_rename_gui_v2.exe --child .venv\Scripts\python.exe -m uvicorn backend.main:app --port 9000
```

→ 이렇게 했을 때만 read가 통과한다면 **자식 상속이 필수** → backend lifespan에서
worker 자동 spawn + backend가 worker child로 동작하는 구조로 변경 필요.

## 다음 단계 (가설 검증 결과에 따라)

| 가설 | 결과 | 다음 작업 |
|------|------|----------|
| (b) 자식 상속 — backend가 같은 PC의 별도 프로세스여도 read 가능 | ✅ | 현 모델 유지. dummy exe로 충분 |
| (b)' 자식 상속 — backend가 worker의 자식이어야 read 가능 | ✅ partial | lifespan에서 worker 자동 spawn + backend re-launch |
| (a) 같은 exe 안에서만 read 가능 (상속 X) | ❌ | worker IPC 모델로 전면 재작성 (TCP server) |

## 파일

- `cloudium_worker/dummy.py` — Python entry point (idle / --pid / --child)
- `dist/excel_rename_gui_v2.exe` — PyInstaller 산출물 (커밋 제외 — `.gitignore`에 dist/ 추가 권장)
- `build/pyinstaller/excel_rename_gui_v2.spec` — PyInstaller spec (재빌드 시 사용)
