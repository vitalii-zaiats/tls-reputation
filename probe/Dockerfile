# syntax=docker/dockerfile:1.7
#
# Reputation probe server. Standard library only — no build, no dependencies.
FROM python:3.13-slim

RUN useradd --system --uid 10002 --no-create-home --shell /usr/sbin/nologin tlsrep

WORKDIR /app
COPY tlsrep_probe ./tlsrep_probe

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TLSREP_PROBE_PORT=8443

USER tlsrep
EXPOSE 8443

CMD ["python", "-m", "tlsrep_probe.main"]
