#!/bin/bash
# PreToolUse: API 호출 시 백엔드가 실행 중인지 확인
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# curl로 백엔드 API 호출하는 경우만 체크
if echo "$COMMAND" | grep -q "curl.*127.0.0.1:8000\|curl.*localhost:8000"; then
  # 백엔드 상태 확인
  if ! curl -s --connect-timeout 2 http://127.0.0.1:8000/api/health > /dev/null 2>&1; then
    echo "WARNING: Backend server (port 8000) is not responding. Start it first: cd backend && uvicorn main:app --reload --port 8000" >&2
  fi
fi
exit 0
