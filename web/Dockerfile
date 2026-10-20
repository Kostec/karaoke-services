# Образ web: FastAPI + Uvicorn, общий пакет karaoke_core и статический фронтенд.
# Сборка из корня репозитория (контекст `.` в docker-compose.yml).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data WEB_STATIC_DIR=/srv/web/static
WORKDIR /srv

COPY core/ /srv/core/
RUN pip install /srv/core

COPY web/pyproject.toml /srv/web/pyproject.toml
COPY web/app/ /srv/web/app/
RUN pip install /srv/web

COPY web/static/ /srv/web/static/

EXPOSE 8080
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "5"]
