# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

RUN useradd --system --uid 10003 --no-create-home --shell /usr/sbin/nologin tlsrep
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30"
COPY stunprobe ./stunprobe

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 STUNPROBE_HTTP_PORT=8100
USER tlsrep
EXPOSE 8100
CMD ["python", "-m", "stunprobe.main"]
