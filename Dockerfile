FROM python:3.12-slim

ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="Bröllopsplaneraren" \
      org.opencontainers.image.description="Självhostad bröllopsplanerare för Unraid" \
      org.opencontainers.image.source="https://github.com/BraXhn/wedding-planner" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_VERSION=${APP_VERSION} \
    DATA_DIR=/data \
    TMPDIR=/data/.tmp \
    PUID=99 \
    PGID=100 \
    TZ=Europe/Stockholm \
    TRUSTED_PROXIES=172.16.0.0/12,10.0.0.0/8,192.168.0.0/16

# tzdata: utan den ignoreras TZ och appen räknar i UTC – då blir "idag" fel mellan 00 och 02
# (nedräkning, försenade uppgifter och sista dag för OSA).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && command -v setpriv >/dev/null \
 && mkdir -p /data

COPY app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh && python -m compileall -q app

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

# entrypoint.sh ger /data rätt ägare och släpper sedan root → appen kör som PUID:PGID utan capabilities.
# En worker: rate-limitern och utskicksjobbet ligger i minnet. Räcker gott för ett bröllop.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips \"$TRUSTED_PROXIES\" --no-server-header --no-date-header --timeout-keep-alive 5 --limit-concurrency 100"]
