FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/backend-common /app/packages/backend-common
COPY apps/purge-worker /app/apps/purge-worker

ENV PYTHONPATH=/app/packages/backend-common:/app/apps/purge-worker
WORKDIR /app/apps/purge-worker

CMD ["python", "-m", "app.main"]
