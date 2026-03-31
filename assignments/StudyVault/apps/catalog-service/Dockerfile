FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY packages/backend-common /app/packages/backend-common
COPY apps/catalog-service /app/apps/catalog-service

ENV PYTHONPATH=/app/packages/backend-common:/app/apps/catalog-service
WORKDIR /app/apps/catalog-service

EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
