FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC \
    DIET_BOT_POLLING_HEARTBEAT_FILE=/tmp/diet_bot_polling_heartbeat.json

WORKDIR /app

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /app --no-create-home app

COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir --no-deps .
RUN pip check
RUN python -m diet_bot.healthcheck --package-data-only

USER app:app

CMD ["diet-bot-telegram"]
