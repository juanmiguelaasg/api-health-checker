# API Health-Checker – headless scheduled checker
#
# The desktop app needs a display, so the container runs the checker in
# `watch` mode. History lives in /app/data, the HTML status page in /app/site.
#
#   docker build -t api-health-checker .
#   docker run -d --name api-health-checker \
#     -e BASE_URL=https://api.example.com \
#     -v ./endpoints.yaml:/app/endpoints.yaml:ro \
#     -v hc-data:/app/data -v hc-site:/app/site \
#     api-health-checker
#
# Any CLI command works too:  docker run --rm api-health-checker run --fail-on-error

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# headless mode needs no Tk / customtkinter
COPY requirements-headless.txt .
RUN pip install -r requirements-headless.txt

COPY healthcheck ./healthcheck
COPY schemas ./schemas
COPY endpoints.yaml mock_api.py ./

RUN useradd --create-home --uid 10001 hc \
    && mkdir -p data site results postman \
    && chown hc:hc data site results postman
USER hc

VOLUME ["/app/data", "/app/site"]

# healthy while scheduled runs keep happening (last run newer than 3 x interval)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "healthcheck", "heartbeat"]

ENTRYPOINT ["python", "-m", "healthcheck"]
CMD ["watch"]
