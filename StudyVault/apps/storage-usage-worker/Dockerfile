FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/backend-common /app/packages/backend-common
COPY apps/storage-usage-worker /app/apps/storage-usage-worker

ENV PYTHONPATH=/app/packages/backend-common:/app/apps/storage-usage-worker
WORKDIR /app/apps/storage-usage-worker

CMD ["python", "-m", "app.main"]
