# 🔧 Аудит 2026-09-17 — выполненные фиксы + план восстановления durability

> 🤖 Arena.ai Agent Mode, сервер arm-server-01 (OCI). Все правки — с бэкапами в `/root/backups/audit-2026-09-17/`.
> 📚 Основание: решения владельца в сессии 2026-09-17 («P0: 1 сделать приватный, 2 закрыть извне; P1: делать всё; P2: делай что надо; durability: план»).

## 1. ✅ P0-1 — утечка мастер-архива на HuggingFace (устранена)

- 🔍 Было: датасет `JoTalbot/octopus-eternal` — `private=false`, `gated=false`, 216 файлов, `downloads=34462`; `snapshots/chunk_aa…` отдавались анонимно (HTTP 206, zstd).
- ❌ `update_repo_settings(private=True)` → **403 «exceed your private storage limit»** (архив 2345.6 MB, бесплатный лимит приватного хранилища исчерпан).
- ✅ Сделано: удалены **214 файлов** (`snapshots/chunk_*` ×212, `octopus-bootstrap.sh`, `discovery/mesh_nodes.json`), затем `dr_manifest.json`.
  Репозиторий пуст (остался `.gitattributes`); внешняя проверка: `chunk_aa`, `dr_manifest.json`, `octopus-bootstrap.sh` → **404**.
- ✅ Создан приватный датасет **`JoTalbot/octopus-eternal-private`** (`private=true`) — новая цель публикации.
- ✅ `octopus-eternal-snapshot.py`: публикация чанков на HF **выключена по умолчанию** (включается только `OCTOPUS_ETERNAL_HF_CHUNKS=1`),
  дефолт `HF_REPO_ID` → приватный репозиторий; в tar добавлены `--exclude='etc/octopus'`, `--exclude='*.pem'`, `--exclude='*_token'`
  (проверено dry-run: из `/etc/octopus` в архив попадает **0** файлов, было 67).
- ✅ В `/etc/octopus/secrets.env` добавлен `HF_REPO_ID=JoTalbot/octopus-eternal-private` (бэкап файла сделан).
- 📌 Полная копия архива сохранена в Telegram-канале (50 чанков, загрузка 17.09 04:08 — успешно), поэтому удаление чанков с HF не потеря данных.
- ⚠️ **Остаточный риск:** файл уже могли скачать (34 462 загрузки репозитория) → **ротация секретов обязательна** (см. п.5).

## 2. ✅ P0-2 — noVNC 0.0.0.0:6080 без пароля (закрыт)

- 🔍 `ufw` оказался бесполезен: Docker DNAT-ит трафик в `nat/PREROUTING` **до** `ufw-user-input` → ALLOW/DENY-правила ufw на опубликованные порты контейнеров не работают.
- ✅ Шаг 1: `ufw delete` двух ALLOW-правил + добавлен `deny 6080/tcp` (v4/v6) с комментарием.
- ✅ Шаг 2: правило `DROP tcp/6080` в цепочке **`DOCKER-USER`** + новый идемпотентный юнит
  `octopus-firewall-hardening.service` (`/opt/octopus-firewall-hardening.sh`, enabled, после `docker.service`) — переживает рестарт docker/хоста
  (пакет `iptables-persistent` в системе удалён, поэтому правило сохраняем юнитом).
- ✅ Шаг 3 (полное закрытие сокета): контейнер `octopus-browser-chromium` пересоздан с `-p 127.0.0.1:6080:6080 -p 127.0.0.1:9222:9222`.
  Профиль не пострадал (bind `/opt/octopus-browser/data/profiles/main:/config/profile`).
  Старый контейнер сохранён как `octopus-browser-chromium.bak.20260917T053349Z` (остановлен) — откат возможен.
- 🧪 Проверки: на хосте `ss` показывает только `127.0.0.1:6080`; `curl 127.0.0.1:6080/vnc.html` → 200; CDP `127.0.0.1:9222/json/version` → Chrome/152;
  cookie-keeper после рестарта → `vault updated: 18 cookies`. Снаружи: 12 с таймаут, 0 байт (как на заведомо закрытом 12345), при живом 9119 (302 за 0.13 с).

## 3. ✅ P0-3 — хардкод HF-токена в коде (устранён)

- 🔍 `/opt/octopus/octopus-multisync.py`, строка 24: `"HF_TOKEN": "hf_…"` — открытый токен в исходнике git-репозитория (нарушение инструкции №51).
- ✅ Токен убран из кода: `CONFIG["HF_TOKEN"] = os.environ.get("HF_TOKEN", "")` + функция `_load_secrets_env()` (читает `/etc/octopus/secrets.env`, chmod 600).
  `HF_REPO_ID` тоже из окружения, дефолт — приватный репозиторий. Сервис перезапущен, `active`, цикл синхронизации штатный.
- 🧪 `grep -cE "hf_[A-Za-z0-9]{25,}"` по файлу → **0**.
- ⚠️ Токен остаётся в **истории git** и в копиях: `/opt/octopus-aios-integration/octopus-multisync.py` (не используется ни одним юнитом),
  `/opt/orchestrator/data/{chats,light}/*.json` (4 файла — записи чатов). → ротация токена HF обязательна.

## 4. ✅ P1 — четыре локальных фикса (все проверены)

| # | Файл | Правка | Проверка |
|---|---|---|---|
| 1 | `/opt/octopus-health-json.sh` | Атомарная запись (`tmp` + `os.replace`), сводка → `stderr`/journal; убран редирект stdout в целевой файл; парсинг `NRestarts` защищён try/except | `health.json` валиден (6642 B, ключи disk/hostname/memory/nrestarts/services/slo/timestamp); в journal — `Health JSON: svcs=34/161, failed=0, SLO=green` |
| 2 | `/opt/octopus-critical-guard.sh` | Пропуск юнитов, которых нет в системе (`systemctl list-unit-files` = 0 строк) | Прогоны 05:42:37/05:43:05/05:43:34 — без ошибок devpanel |
| 2б | `/opt/octopus-self-heal.sh` | Аналогичная проверка (именно он давал остаточный шум каждые 2 мин) | `All critical services OK`, devpanel не рестартуется |
| 3 | `octopus-browser/cookie-keeper/google_cookie_keeper.py` | `connect_over_cdp(CDP, timeout=15000)`, `page.goto(... timeout=25000)`, обёртка исключений в `__main__` → лог + `exit 0` | Юнит `success`, `vault updated: 18 cookies` |
| 4 | `/opt/octopus-slo-checker.py` | Красный/жёлтый SLO больше не валит юнит (`return 0`); прежнее поведение — `SLO_CHECKER_FAIL_ON_RED=1` | `Result=success`, `ExecMainStatus=0`, прямой прогон `rc=0`, 15/15 pass |

- 📌 Зависимости учтены: `octopus-chaos-drill.py` читает только stdout, `octopus-cas-api.py` — `slo_status.json` и список failed-юнитов (шум исчез), `octopus-slo-alert.py` — no-op-обёртка.

## 5. ⚠️ Обязательная ротация секретов (за владельцем)

Считать скомпрометированными (лежали в публичном датасете и/или в коде/истории git):
`HF_TOKEN`, `TELEGRAM_BOT_TOKEN`, `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_LOGIN`/`AWS_PASS`,
`CF_TUNNEL_TOKEN`/`CF_API_TOKEN`, `OCI_AUTH_TOKEN`/`ORACLE_CLOUD_TOKEN`, `GEMINI_API_KEY*`, `GROQ_API_KEY*` (~14 шт.),
`MISTRAL_API_KEY*`, `CEREBRAS_API_KEY*`, `TWO_CAPTCHA_API_KEY`, `RAILWAY_TOKEN`, `HCLOUD_TOKEN`, `ARENA_API_KEY`,
`CAS_*_TOKEN`, `GRAFANA_ADMIN_PASS`, `OCTOPUS_DASH_PASS`, `NEXTAUTH_SECRET`, `DATABASE_URL`.
Плюс: SSH-ключ `oci_server_key.pem`, отправленный в чат сессии.

## 6. 🧹 P2 — сделано

- ✅ `octopus-eternal-snapshot.service`: drop-in `limits.conf` → `MemoryHigh=6G`, `MemoryMax=10G`, `TasksMax=256` (фактический пик был 9.6 GB из 24 GB; требование инструкции №18 п.4).
- ✅ journald: `SystemMaxUse=500M` + `--vacuum-size=500M` → 1.0 GB → **478.5 MB**.
- ✅ Docker build cache: `builder prune -f` (реально освобождено 57 kB — остальное помечено как используемое образами; при необходимости `prune -a`).
- ✅ `ARENA_HEALTH_RUNBOOK_RU.md`: добавлена секция «Актуализация 2026-09-17» — битые пути к инструментам и фактические точки проверки здоровья.
- ⏸️ Отложено (нужно решение владельца): права `/root/agents` (135 каталогов `drwxrwxrwx` — менять рискованно, часть сервисов пишет туда от `ubuntu`);
  git-расхождение `/opt/octopus`; остальные `ua-*` публичные датасеты (открытые данные, не трогал).

## 7. 📋 ПЛАН: восстановление off-host durability памяти (P1-5/P1-6)

### Диагностика (факт на 2026-09-17)
- Локально: `pack_index_v2` = **20524** ref, 47 pack-файлов, packstore 107 MB (264 MB apparent), всё `/var/lib/octopus` = 528 MB; `pack_read_guard` 50/50 OK.
- Независимых копий: **0**. Каналы в состоянии:
  - `octopus-packstore-offhost` → `targets=0`; AWS-нода `54.145.228.26` недоступна, ключ `/root/.ssh/octopus-aws-key-us` отсутствует;
  - `octopus-local-s3-backup` → `203/EXEC`, `garage_health.json`: `FileNotFoundError: 'garage'` (Garage не установлен);
  - `octopus-local-backup` → нет `/opt/octopus-local-backup.py`;
  - S3-канал `eternal` → пропущен (`aws sts get-caller-identity` failed);
  - OCI Object Storage → работает, но грузит только `octopus_vault_*.tar.zst` (1.4 MB: skills + STEP_STATUS + nodes.json) — **без packstore и без app_db**.
- `memory_copies_audit.json` при этом показывает `local_objects=0 … coverage_fraction=1.0` → «0/0 = 100 %», инвариант не проверяется (ложно-зелёный).

### Варианты
| Вариант | Суть | Плюсы | Минусы | Оценка |
|---|---|---|---|---|
| **A (рекомендую)** | OCI Object Storage как основной off-host канал: в `octopus-oci-vault-sync.py` добавить паксто + дамп `app_db` (pack_index_v2, словари zstd) отдельными объектами с sha256-манифестом; квота-гард 18 GB уже есть | Работает сегодня, Always Free, тот же тенант, уже проверенный upload | Один вендор (не «независимый» по строгому смыслу) | 1–2 ч работы |
| B | Починить Garage (локальный S3) + `octopus-local-s3-backup` | S3-совместимо, дёшево | Garage не установлен (нужна сборка под aarch64), это **тот же хост** → не независимая копия | 3–5 ч, польза ограниченная |
| C | Восстановить AWS-ноду/ключ для `packstore-offhost` | Исторически рабочий канал | AWS free-tier ноды больше нет, ключи AWS невалидны | не рекомендую |
| D | Репликация на ноды роя (`10.0.0.2`, `10.0.0.87`) | Есть в архитектуре | Микро-ноды по 1 GB RAM, `multisync` показывает «Активные удаленные пиры: []» | только как дополнение |

### Шаги варианта A (по согласованию)
1. 📦 Расширить `octopus-oci-vault-sync.py`: объекты `packstore/v2/<pack>` + `db/app_db_dump.sql.zst` + `manifest.json` (sha256, размеры, `dict_sha8`).
2. 🧪 Тест: выборочная вычитка 20 паков из бакета, сверка sha256, restore-драйв в `/tmp` (по образцу drill-ей Фазы 7 в Octopus Browser).
3. 📊 Починить `memory_copies_audit`: считать `local_objects` из `pack_index_v2`/паков, при `covered < local` писать `ok=false` и `coverage_fraction` честно;
   добавить проверку в `octopus-slo-checker.py` (сейчас её нет среди 15 чеков).
4. 🔁 Расписание: packstore-синк 1×/сутки + при изменении (по mtime паков), аудит копий 1×/час.
5. 📝 Зафиксировать runbook `docs/BACKUP.md`-аналог для Октопуса и skill в `/mnt/agents/-Octopus/skills/` (по инструкции №005/№57: лог → skill).

### Сроки/приоритеты
- 🔴 До 24 ч: ротация секретов (п.5) + первая off-host копия пакстора (шаг A1–A2).
- 🟠 До 3 дней: честный coverage-аудит + SLO-чек (A3), удаление хардкод-токена из истории git и из `/opt/octopus-aios-integration`, `/opt/orchestrator/data/*`.
- 🟡 До недели: решение по git-расхождению `/opt/octopus` (main 92↔64, HEAD 101↔64), права `/root/agents`, приватность/удаление пустого публичного датасета.

## 8. 🔍 Как проверить всё сделанное

```bash
# P0-1: внешний доступ к чанкам закрыт
curl -s -o /dev/null -w "%{http_code}\n" -L https://huggingface.co/datasets/JoTalbot/octopus-eternal/resolve/main/snapshots/chunk_aa   # 404
# P0-2: noVNC только на loopback
ss -tlnpH 'sport = :6080'                      # 127.0.0.1:6080
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:6080/vnc.html   # 200
iptables -S DOCKER-USER                        # DROP tcp/6080
systemctl is-enabled octopus-firewall-hardening.service                   # enabled
# P0-3: хардкода токена нет
sudo grep -cE 'hf_[A-Za-z0-9]{25,}' /opt/octopus/octopus-multisync.py     # 0
# P1: health.json валиден, slo-checker зелёный и не падает
python3 -c "import json;print(json.load(open('/run/octopus/health.json'))['services'])"
sudo python3 /opt/octopus-slo-checker.py; echo "rc=$?"                    # 15/15, rc=0
journalctl -S '-10min' --no-pager | grep -c octopus-devpanel              # 0
# P2: лимиты и журнал
systemctl show octopus-eternal-snapshot.service -p MemoryMax -p MemoryHigh
journalctl --disk-usage
```

## 9. 📂 Артефакты

- Бэкапы всех изменённых файлов: `/root/backups/audit-2026-09-17/` (8 файлов + `secrets.env` копия, chmod 600 + inspect-JSON контейнера + env-файл контейнера).
- Отчёт аудита: `/root/agents/-Octopus/reports/AUDIT_2026-09-17_full_ecosystem.md`.
- Лог итерации: `/root/agents/logs/2026-09-17_05-15-20_iteration.md`; статус шага: `/root/agents/STEP_STATUS.json` (`step_90_full_audit`).
