FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_ENV=production

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ARG ENV_FILE=.env.production
COPY ${ENV_FILE} /app/.env.production

COPY src /app/src

CMD ["python", "src/main.py"]
