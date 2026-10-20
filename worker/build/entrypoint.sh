#!/bin/sh
# Вход контейнера worker: каталоги кэшей моделей в томе /models, затем команда karaoke_worker.
# Аргументы gpucheck | selfcheck | run уходят в `python -m karaoke_worker`; любая другая
# команда (bash, python …) выполняется как есть.
set -e
mkdir -p "$HF_HOME" "$TORCH_HOME" "$XDG_CACHE_HOME" "$PYHYPHEN_DIR"
case "$1" in
    gpucheck|selfcheck|run) exec python -m karaoke_worker "$@" ;;
    *) exec "$@" ;;
esac
