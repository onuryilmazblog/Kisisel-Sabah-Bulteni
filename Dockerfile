FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATA_DIR=/data
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY bulten ./bulten
RUN pip install --no-deps . && useradd --create-home --uid 10001 bulten && mkdir -p /data && chown bulten /data

USER bulten
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/saglik', timeout=4)" || exit 1
CMD ["bulten", "web", "--host", "0.0.0.0", "--port", "8000"]
