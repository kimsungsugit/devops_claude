#!/bin/bash
# PostToolUse: 파일 편집 후 비밀값이 포함되었는지 검사
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ] || [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# 비밀값 패턴 검사
SECRETS_PATTERN="(API_KEY|SECRET_KEY|SECRET|PASSWORD|PASSWD|TOKEN|PRIVATE_KEY|AWS_ACCESS_KEY|AWS_SECRET|GOOGLE_API_KEY|JENKINS_TOKEN|DATABASE_URL|DSN|CONNECTION_STRING|AUTH_SECRET)\s*=\s*['\"][^'\"]{8,}"

if grep -qEi "$SECRETS_PATTERN" "$FILE_PATH" 2>/dev/null; then
  echo "WARNING: Possible secret/credential detected in $FILE_PATH. Review before committing." >&2
fi
exit 0
