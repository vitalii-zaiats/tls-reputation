# syntax=docker/dockerfile:1.7
#
# Collector proxy. Standard library only — no dependency install, no builder
# stage, nothing to resolve at build time.

FROM python:3.13-slim

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin tlsrep

WORKDIR /app
COPY tlsrep_proxy ./tlsrep_proxy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TLSREP_LISTEN_PORT=24761

USER tlsrep
EXPOSE 24761

CMD ["python", "-m", "tlsrep_proxy.main"]
