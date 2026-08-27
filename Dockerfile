FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY . .

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY:-2}"]
