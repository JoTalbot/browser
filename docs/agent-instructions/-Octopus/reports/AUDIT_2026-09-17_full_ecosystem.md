# 🛡️ Полный аудит экосистемы Octopus — 2026-09-17 (arm-server-01, OCI)

> 🤖 Автор: Arena.ai Agent Mode (ubuntu@129.213.177.56). Режим: чтение + замеры; правки — только по подтверждению владельца.
> 📚 База: /mnt/agents/ (000–005, 00/01/03/04/05/13/18/42/48/51), BACKLOG.md, STATUS.md, COMPACT_CONTEXT.md.

## 1. 📊 Сводка здоровья

| Метрика | Значение | Оценка |
|---|---|---|
| SLO checker | 15/15 PASS, status=green | ✅ |
| octopus-сервисы running | 34 (failed=0, NRestarts=0) | ✅ |
| Юнит-файлы | 476 сервисов, из них 309 octopus-*; таймеров активно 144 | ✅ |
| Диск / | 59G/145G (41%), inodes 5% | ✅ |
| RAM / swap | 5.6G/23G, swap 1.1G/2G, OOM за 7д = 0 | ✅ |
| journal | 1.0G | ⚠️ можно ограничить |
| Память (packstore) | pack_index_v2 = 20524 ref, 47 pack-файлов, 528M /var/lib/octopus; pack_read_guard 50/50 OK | ✅ локально |
| Off-host копии памяти | 0 (audit: local_objects=0, s3=0, garage=0, ipfs=0, coverage=1.0) | ❌ ложно-зелёный |
| Ошибки journal за 24ч | ~1285 err: cookie-keeper 666, slo-checker 569, integration-test 24 + devpanel-шум каждые 2 мин | ⚠️ |
| octopus-browser | v0.4.0, main = origin/main, /health ok (:8095) | ✅ |
| AIOS bridge | v1.1.0, kernel running, 11 LLM-провайдеров (:9600) | ✅ |
| /opt/octopus git | main 92↔64 origin/main; HEAD 101↔64; 5 веток + worktrees | ⚠️ |

## 2. 🔴 P0 — критично

### 2.1 Публичная утечка мастер-архива (HuggingFace)
- Датасет `JoTalbot/octopus-eternal`: **private=false, gated=false**, 216 файлов, `snapshots/chunk_*` = 212 шт., **downloads=34462**.
- Проверка извне: `chunk_aa` отдаётся без авторизации (HTTP 206, содержимое — Zstandard). `dr_manifest.json`: архив `octopus-eternal-master.tar.zst`, **2345.6 MB**, 50 чанков, `bootstrap_cmd = curl ... | bash`.
- В архив packing-листа (`/opt/octopus/octopus-eternal-snapshot.py`, строка tar): `/root/agents /etc/octopus /var/lib/octopus /opt`.
- Следовательно публично доступны: **`/etc/octopus/secrets.env`** (TELEGRAM_BOT_TOKEN, AWS_ACCESS_KEY_ID/SECRET, AWS_LOGIN/AWS_PASS, CF_TUNNEL_TOKEN, CF_API_TOKEN, OCI_AUTH_TOKEN, ORACLE_CLOUD_TOKEN, HF_TOKEN, GEMINI_*, GROQ_* (~14 ключей), MISTRAL_*, CEREBRAS_*, TWO_CAPTCHA_API_KEY, RAILWAY_TOKEN, HCLOUD_TOKEN, ARENA_API_KEY, CAS_*_TOKEN, GRAFANA_ADMIN_PASS, OCTOPUS_DASH_PASS, NEXTAUTH_SECRET, DATABASE_URL), память (20.5k объектов), корпус инструкций и опыт, весь `/opt`.
- Исключений для секретов в tar-списке нет (есть только quarantine/venv/node_modules/tmp-фильтры).

### 2.2 Публичный noVNC без пароля (:6080)
- `docker inspect octopus-browser-chromium`: `6080/tcp → HostIp 0.0.0.0`, пароль в Env отсутствует; 9222 (CDP) корректно на 127.0.0.1.
- ufw-правила [16]/[30]: `6080/tcp ALLOW IN Anywhere # noVNC TEMPORARY (NO PASSWORD!) - remove after arena.ai chat export`.
- Внешняя проверка: `HTTP 200` (WebSockify, listing каталога noVNC). Риск: любой желающий получает экран/ввод браузера с активной Google-сессией (cookie-keeper держит 18 cookies в vault).

## 3. 🟠 P1 — значимо

1. **`/run/octopus/health.json` повреждён.** `/opt/octopus-health-json.sh`: python пишет JSON через `open(path,'w')` и тут же stdout (`print(...)`) редиректится в тот же файл → строка `Health JSON: svcs=...` затирает начало JSON, остаток старого файла остаётся в хвосте. Итог: файл не парсится (`json.loads` → Extra data), запись неатомарна. Потребители (дашборды/гарды) читают мусор.
2. **Шум каждые 30 сек: `octopus-devpanel.service` не существует.** `/opt/octopus-critical-guard.sh` (строки 2, 6) restart-ит юнит, вынесенный в `/opt/octopus-deploy/phase9-backup/` → ~720 ошибок/сутки.
3. **`octopus-google-cookie-keeper`**: 666 падений/24ч — `start operation timed out` (TimeoutStartSec=120) при зависшем CDP; с 03:22 скрипт отвечает `CDP down; skip` за ~1с. Нет fast-fail/таймаута на подключение к CDP → юнит «висит» 2 минуты.
4. **`octopus-slo-checker`**: 569 «падений» — при красном чеке скрипт выходит с кодом 2, systemd помечает проваленным сам чекер (в т.ч. из-за транзиентного failed-состояния cookie-keeper). Само-шум маскирует реальные инциденты.
5. **Durability памяти = 0 независимых копий**: `octopus-packstore-offhost` → targets=0 (AWS 54.145.228.26: нет ключа `/root/.ssh/octopus-aws-key-us`, permission denied); `octopus-local-s3-backup` → 203/EXEC (garage не установлен, `garage_health.json: FileNotFoundError 'garage'`); `octopus-local-backup` → нет `/opt/octopus-local-backup.py`; S3-канал eternal пропущен (`aws sts failed`). OCI Vault получает только маленький `octopus_vault_*.tar.zst` (1.4MB = skills+STEP_STATUS+nodes.json), **не packstore**. Итог: единственная вне-хостовая копия полного архива — Telegram + публичный HF.
6. **`memory_copies_audit.json` ложно-зелёный**: local_objects=0 при pack_index=20524 → coverage 0/0 = 1.0. Инвариант «≥1 независимая копия» фактически не проверяется.

## 4. 🟡 P2 — гигиена

- `octopus-eternal-snapshot`: `MemoryMax=infinity`, пик **9.6G** из 24G, 38 минут работы (нарушение №18 п.4 про лимиты тяжёлых сервисов). Без лимитов также multisync/rag-search/aios/browser.
- Docker build cache 1.46G (reclaimable); images 5.98G; `/var/log` 1.9G (syslog 547M, journal 1.1G).
- `/root/agents`: 135 каталогов с правами `drwxrwxrwx` (world-writable) — любой локальный пользователь может подменить инструкции агентов (prompt-injection в рой).
- Git `/opt/octopus`: расхождение main 92/64 и HEAD 101/64 с origin/main, ветка `arena/tg-bot-aios-fix-and-multisync-selfloop` + 4 локальных, worktrees `/home/ubuntu/{batch18,batch19,batch20}-oci`, `wt*`, в дереве 2 untracked файла.
- Документация: `ARENA_HEALTH_RUNBOOK_RU.md` ссылается на отсутствующие `tools/octopus-arena-health-report.py` и `/usr/local/sbin/octopus-production-guard-report`.
- UFW открыт наружу (помимо 22): 8010/udp, 9010/udp, 10010/tcp, 8300:8310/udp, 9301/udp, 10301/tcp (P2P-рой), 6080, 9119 (Hermes, по решению владельца 15.09 — с паролем). Наружу из интернета реально отвечают только 6080 и 9119 (остальное фильтрует OCI Security List).
- Секреты в текстах инструкций: открытых значений не найдено (только плейсхолдеры `ghp_xxxx`, `sk-adju...` в доках и фикстура теста) — №51 соблюдается.

## 5. ✅ Что хорошо

- SLO 15/15, ноль failed-юнитов, ноль авторестартов, OOM нет, диск 41%.
- `octopus-browser` v0.4.0 синхронен с origin/main, health ok; AIOS-бридж жив, 11 LLM-провайдеров.
- Вечный снимок отрабатывает (03:00→04:08, 50 чанков в Telegram — успешно), OCI Vault-синк загружает снапшот, квота-гард 18GB.
- Автономия ограничена по №18: dev-loop/auto-projects/rag-sync/obsidian-sync/audio-sync таймеры выключены; `human_consent.env` на месте.
- CDP браузера (9222) и Postgres (5434) наружу не доступны; pg_hba — только local/127.0.0.1 со scram-sha-256.

## 6. 🚀 План исправлений (ждёт подтверждения)

| # | Приоритет | Действие | Обратимость |
|---|---|---|---|
| 1 | P0 | Закрыть HF-датасет `JoTalbot/octopus-eternal` (private=true) через API с `HF_TOKEN`; затем решить: удалить чанки или перезалить без секретов | Обратимо (можно вернуть public) |
| 2 | P0 | Исключить `/etc/octopus` (и `*.pem`, `*_token`) из мастер-архива `octopus-eternal-snapshot.py`; бэкап скрипта `.bak.<ts>` | Обратимо |
| 3 | P0 | Ротация всех секретов из `secrets.env` (считать скомпрометированными): Telegram-бот, Cloudflare, OCI, HF, Groq/Gemini/Mistral/Cerebras, 2Captcha, Railway, Grafana, NEXTAUTH, DB | Требует времени владельца |
| 4 | P0 | Закрыть 6080: `ufw delete` правил + перевести публикацию порта на `127.0.0.1:6080` (или включить пароль noVNC) | Обратимо |
| 5 | P1 | Починить `octopus-health-json.sh`: атомарная запись (tmp + `os.replace`), статусная строка → stderr | Обратимо |
| 6 | P1 | Убрать `octopus-devpanel` из `octopus-critical-guard.sh` или добавить проверку существования юнита | Обратимо |
| 7 | P1 | cookie-keeper: таймаут подключения к CDP (fast-fail 10с) вместо 120с висения | Обратимо |
| 8 | P1 | slo-checker: не завершать юнит кодом 2 (писать статус в JSON/алерт-канал), чтобы не плодить failed-юнит | Обратимо |
| 9 | P1 | Вернуть off-host-реплики packstore: Garage (установить/починить) или OCI Object Storage как основной канал; честный coverage-аудит (учитывать packstore, не 0/0=1.0) | Средняя сложность |
| 10 | P2 | `MemoryMax`/`CPUQuota` для eternal-snapshot и тяжёлых сервисов; `docker builder prune`; лимит journal (SystemMaxUse=500M); убрать world-writable у `/root/agents` | Обратимо |
| 11 | P2 | Решение по git-расхождению `/opt/octopus` (новая ветка+PR vs форс-пуш) и по worktrees | Только с владельцем |
| 12 | P2 | Актуализировать `ARENA_HEALTH_RUNBOOK_RU.md` (пути к инструментам) | Обратимо |
