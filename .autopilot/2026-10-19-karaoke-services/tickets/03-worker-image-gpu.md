# 03 — Образ worker: UltraSinger из ветки, PyTorch для Pascal, проверка GPU

**Требования:** R15, R17, R18, R24, R26, R30, R31
**Blocked by:** 01
**Зона:** `worker/Dockerfile` · `worker/karaoke_worker/gpucheck.py`, `selfcheck.py`, CLI-вход `__main__` · `scripts/export-ultrasinger-patch.ps1` · `patches/` · сервис `worker` в `docker-compose.yml`
**Волна:** 2
**Status:** ready

## Что должно заработать

`docker --context desktop-linux compose build worker` собирает образ:
- база `nvidia/cuda:12.6.x-cudnn-runtime-ubuntu22.04`, Python 3.12 (deadsnakes), ffmpeg;
- UltraSinger берётся из `ULTRASINGER_GIT` через `additional_contexts` (git URL ветки `karaoke-local` или локальная папка);
- зависимости UltraSinger, затем torch, torchaudio и torchvision 2.8.0/0.23.0 с cu126, `numpy<2.5`;
- пакет `core`.

Сборка падает с понятным сообщением, если в `torch.cuda.get_arch_list()` нет `sm_61`. Кэши моделей (`HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME`, словари pyhyphen) направлены в том `/models`.

`docker --context desktop-linux compose run --rm worker gpucheck` печатает:
- версии torch и CUDA, список архитектур;
- GPU и VRAM;
- результат умножения тензоров на cuda;
- CUDA-устройства ctranslate2 и поддержку int8.

Код выхода 0 только при полном успехе.

`selfcheck` подтверждает, что правки на месте: флаги `--lyrics`/`--vad_onset`/`--vad_offset`, импорт `lyrics_alignment`, `midi_creator` на сегменте нулевой длины. Скрипт `export-ultrasinger-patch.ps1` кладёт `git format-patch origin/main..karaoke-local` из `D:/Projects/UltraSinger` в `patches/`. В репозиторий UltraSinger он ничего не пишет.

## Из брифа, дословно

> «Worker: UltraSinger с нашими правками, GPU … Образ собирать из моей копии репозитория (сохранить локальные правки; предусмотреть, как переносить их при обновлении upstream).»
> «Проверь, что GPU реально доступен в контейнере (`torch.cuda.is_available()` и тестовый тензор на cuda) — PyTorch-сборка должна поддерживать Pascal (sm_61).»
> «Кэш моделей (Whisper, Demucs, wav2vec2, HuggingFace) — в постоянном томе»
> «numba требует `numpy<2.5`.»

## Разделы спецификации

Истории 53–58; Решения §1, §3 (том models), §12.

## Критерии приёмки

- [ ] Образ реально собран на этой машине; хвост вывода сборки приложен к отчёту таска
- [ ] `compose run --rm worker gpucheck` на реальной GTX 1080 даёт код 0: `cuda.is_available() == True`, `sm_61` в списке архитектур, тензор посчитан на cuda, ctranslate2 видит устройство и int8; вывод приложен
- [ ] `selfcheck` зелёный на текущей ветке; при отсутствии флага или модуля даёт понятную ошибку (тест с подменой)
- [ ] `HF_HOME`, `TORCH_HOME`, `XDG_CACHE_HOME` в контейнере указывают в `/models`; содержимое тома переживает пересоздание контейнера
- [ ] `scripts/export-ultrasinger-patch.ps1` создаёт `patches/karaoke-local.patch`, соответствующий текущей ветке
- [ ] Сервис `worker` в compose: `restart: unless-stopped`, GPU-резервирование nvidia count 1, тома `data` и `models`
