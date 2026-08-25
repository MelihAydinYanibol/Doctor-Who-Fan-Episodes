# Serves the reader straight from GitHub — no checkout of the book required.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV DWFE_SOURCE=github \
    DWFE_CACHE_TTL=300 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "app:app"]
