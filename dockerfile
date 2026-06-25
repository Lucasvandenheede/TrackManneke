FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY src /app/src

# Expect runtime env vars: DISCORD_TOKEN, GUILD_ID, ENVIRONMENT, TOTD_CHANNEL_ID,
# COTD_CHANNEL_ID, DATABASE_URL (optional, fallback to SQLite),
# NADEO_SERVICE_ACCOUNT_LOGIN, NADEO_SERVICE_ACCOUNT_PASSWORD,
# OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, USER_AGENT, TIMEZONE

CMD ["python", "src/main.py"]
