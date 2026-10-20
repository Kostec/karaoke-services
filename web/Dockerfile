# Образ web: FastAPI + Uvicorn, общий пакет karaoke_core и статический фронтенд.
# Сборка из корня репозитория (контекст `.` в docker-compose.yml).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data WEB_STATIC_DIR=/srv/web/static
WORKDIR /srv

# yt-dlp — данные по ссылке на музыку (POST /api/link/inspect). Не через pyproject: в образе tests
# yt_dlp быть не должно. Всегда последняя версия, как в worker/Dockerfile (3в); обновить:
# ./scripts/compose.ps1 build --build-arg YTDLP_REFRESH=<сегодняшняя дата> web
ARG YTDLP_REFRESH=2026-10-20
RUN echo "yt-dlp: обновление ${YTDLP_REFRESH}" \
    && pip install -U "yt-dlp[default]" \
    && python -m yt_dlp --version

COPY core/ /srv/core/
RUN pip install /srv/core

COPY web/pyproject.toml /srv/web/pyproject.toml
COPY web/app/ /srv/web/app/
RUN pip install /srv/web

COPY web/static/ /srv/web/static/

EXPOSE 8080
CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "5"]
