# KcpInsights API — optional container for free hosts that run Docker (e.g. Render, Hugging Face Spaces).
# Local development does not need Docker: use scripts/dev.sh.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

RUN useradd --create-home kcp && mkdir -p /app/data && chown -R kcp /app
USER kcp

ENV KCP_ENVIRONMENT=production KCP_AI_PROVIDER=deterministic PORT=8000
EXPOSE 8000
# Migrate, load the labelled synthetic demo only if the database is empty, then serve.
CMD ["sh", "-c", "python -m app.cli migrate && python -m app.cli seed-demo && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
