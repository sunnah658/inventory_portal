# Dockerfile - builds the portal image. Rebuild after ANY code change:
#   docker compose up -d --build
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORTAL_DATA=/data

# tzdata makes the TZ setting in .env work (correct times in the portal)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# run as a normal user, not root. /data is the persistent volume (database, files)
RUN useradd --system --uid 10001 portal \
    && mkdir /data && chown portal /data
COPY --chown=portal . .
USER portal

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4)"

# waitress is the production web server (8 threads is plenty for 200 users)
CMD ["python", "-m", "waitress", "--host=0.0.0.0", "--port=8000", "--threads=8", "app:app"]
