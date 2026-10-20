# Образ worker: CUDA 12.6 + cuDNN 9, Python 3.12, ffmpeg, UltraSinger из ULTRASINGER_GIT,
# PyTorch 2.8.0 с индекса cu126 (код Pascal / GTX 1080), deno (для yt-dlp),
# пакеты karaoke_core и karaoke_worker.
#
# Исходники UltraSinger приходят как именованный контекст сборки `ultrasinger`
# (docker-compose.yml → additional_contexts: git-URL ветки или локальная папка).
# Собирать: docker --context desktop-linux compose build worker

FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=600 \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_PYTHON=python3.12 \
    UV_SYSTEM_PYTHON=1

# Python 3.12 (deadsnakes), ffmpeg, компилятор (для пакетов без колёс), git, tzdata.
# PPA подключается вручную (без add-apt-repository и API launchpad — меньше точек отказа сети).
ARG DEADSNAKES_KEY=F23C5A6CF475977595C89F51BA6932366A755776
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL --retry 5 "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${DEADSNAKES_KEY}" \
        | gpg --dearmor -o /usr/share/keyrings/deadsnakes.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/deadsnakes.gpg] https://ppa.launchpadcontent.net/deadsnakes/ppa/ubuntu jammy main" \
        > /etc/apt/sources.list.d/deadsnakes.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 python3.12-dev python3.12-venv \
        ffmpeg git tzdata build-essential \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3

# uv — быстрый установщик пакетов (тот же, что использует UltraSinger).
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

# 1) PyTorch строго с индекса cu126: Linux-колёса cu128 собраны без Pascal.
#    Кэш uv в cache-mount: оборванная загрузка не начинается заново с нуля.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cu126
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --index-url "${TORCH_INDEX}" torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0

# Сборка падает с понятным сообщением, если в torch нет кода для GTX 1080 (sm_61 / sm_60).
COPY worker/build/check_torch_arch.py worker/karaoke_worker/gpucheck.py /tmp/archcheck/
RUN python /tmp/archcheck/check_torch_arch.py

# 2) Зависимости UltraSinger из его pyproject.toml (без -e: исходники кладём отдельно).
#    Версии фиксируются по uv.lock UltraSinger (uv export), кроме наших пинов:
#    torch/torchaudio/torchvision cu126 (+ их nvidia-*, triton) и numpy<2.5 — см. lock_constraints.py.
COPY --from=ultrasinger pyproject.toml uv.lock /app/UltraSinger/
COPY worker/build/lock_constraints.py /tmp/archcheck/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /app/UltraSinger \
    && uv export --frozen --no-hashes --no-dev --no-emit-project --no-header --no-annotate \
        -o /tmp/us-lock.txt \
    && python /tmp/archcheck/lock_constraints.py /tmp/us-lock.txt /etc/uv-constraints.txt \
    && uv pip install -r /app/UltraSinger/pyproject.toml "numpy<2.5" \
        --constraint /etc/uv-constraints.txt \
        --extra-index-url "${TORCH_INDEX}" --index-strategy unsafe-best-match \
    && python /tmp/archcheck/check_torch_arch.py

# 2б) Данные NLTK: whisperx.align грузит tokenizers/punkt_tab/<язык> (ru → russian, иначе english),
#     а в рантайме докачать их некуда/неоткуда. punkt — для старых путей *.pickle. Проверяет selfcheck.
RUN python -m nltk.downloader -d /usr/local/share/nltk_data punkt_tab punkt \
    && test -d /usr/local/share/nltk_data/tokenizers/punkt_tab/russian \
    && test -d /usr/local/share/nltk_data/tokenizers/punkt_tab/english

# 3) Исходники UltraSinger (ветка с нашими правками).
COPY --from=ultrasinger . /app/UltraSinger

# 3б) deno — JS-рантайм для yt-dlp (импорт: без него YouTube отдаёт не все форматы).
#     Фиксированная версия, бинарь в PATH; проверяет selfcheck (deno --version).
COPY --from=denoland/deno:bin-2.5.6 /deno /usr/local/bin/deno

# 3в) yt-dlp — всегда последняя версия: YouTube регулярно ломает старые (HTTP 403 на загрузке).
#     Версия из uv.lock UltraSinger снята в lock_constraints.py. Обновить, не пересобирая остальное:
#     ./scripts/compose.ps1 build --build-arg YTDLP_REFRESH=<сегодняшняя дата> worker
ARG YTDLP_REFRESH=2026-10-20
RUN --mount=type=cache,target=/root/.cache/uv \
    echo "yt-dlp: обновление ${YTDLP_REFRESH}" \
    && uv pip install --upgrade "yt-dlp[default]" \
    && python -m yt_dlp --version

# 4) Наши пакеты.
COPY core/ /app/core/
COPY worker/ /app/worker/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --constraint /etc/uv-constraints.txt -e /app/core -e /app/worker \
    && sed -i 's/\r$//' /app/worker/build/entrypoint.sh

# Кэши моделей — в постоянном томе /models (каталоги создаёт entrypoint при старте).
ENV ULTRASINGER_DIR=/app/UltraSinger \
    MODELS_DIR=/models \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch \
    XDG_CACHE_HOME=/models/xdg \
    PYHYPHEN_DIR=/models/hyphen

# Словари pyhyphen: каталог словарей пакета → /models/hyphen (симлинк).
RUN python /app/worker/build/link_hyphen_dir.py "${PYHYPHEN_DIR}"

# Правки UltraSinger на месте — иначе сборка падает с названием пропавшей правки.
RUN python -m karaoke_worker selfcheck

WORKDIR /app/UltraSinger/src
ENTRYPOINT ["sh", "/app/worker/build/entrypoint.sh"]
CMD ["run"]
