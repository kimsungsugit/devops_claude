FROM python:3.12-slim

WORKDIR /app

# System deps:
#   git        — version info, git clone fallback
#   curl       — healthcheck
#   subversion — svn checkout for Jenkins SCM sync (see backend/services/jenkins_service.py)
RUN apt-get update && apt-get install -y --no-install-recommends git curl subversion && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

ENV PYTHONPATH=. \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1

# Create cache directory with correct permissions
RUN mkdir -p /app/.devops_pro_cache && chmod 755 /app/.devops_pro_cache

EXPOSE 9000

# Healthcheck: expect /api/health to return 200
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://127.0.0.1:9000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "9000"]
