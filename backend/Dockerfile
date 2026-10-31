# KcpInsights API — optional container for hosts that run Docker. Local development does not need Docker: use scripts/dev.sh.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Tesseract (open source, local) lets the document pipeline OCR scanned prospectus pages; without it those pages are reported, not read.
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

RUN useradd --create-home kcp && mkdir -p /app/data && chown -R kcp /app
USER kcp

ENV KCP_ENVIRONMENT=production PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=4)"
# Migrate, load the labelled synthetic demo only if the database is empty, then serve (the scheduler runs in this process).
CMD ["sh", "-c", "python -m app.cli migrate && python -m app.cli seed-demo && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
