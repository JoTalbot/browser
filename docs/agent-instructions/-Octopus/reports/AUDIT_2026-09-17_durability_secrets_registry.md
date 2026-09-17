# Отчёт: durability памяти + реестр секретов + зачистка утечек (аудит 2026-09-17, часть 2)

Агент: Arena Agent Mode (arm-server-01, OCI). Основание: решения владельца в сессии 2026-09-17
(«P1 — делать всё», «P2 — делай что надо», «durability — делать всё», «секреты Октопус должен помнить все
и всегда — какие они, зачем, откуда», «можешь закрыть репо на гитхабе»).
Значения секретов в отчёте отсутствуют (инструкция №51).

## 1. Независимая копия памяти (главный результат)
- Канал `octopus-packstore-offhost` был мёртв: rsync на AWS-ноды memory-replica, в nodes.json все `en=false` → targets=0.
- Новый скрипт `/opt/octopus-packstore-offhost-oci.py`: инкрементальная загрузка `/var/lib/octopus/packstore/`
  в OCI Object Storage `octopus-vault-immortal` (prefix `packstore/`), sha256 в `manifest.json`, proof-of-read.
- Контрольный прогон: 45 файлов / 270.8 MB, missing=0, verify 5/5 sha256 OK, 8.3 c, MemoryMax=200M (пик 19.5 MB),
  CPU 5.7 c. Состояние: `/run/octopus/packstore_offhost.json`.
- Ротация бакета настроена так, чтобы НЕ удалять `packstore/` (живая копия, а не версии снимков).

## 2. Честный аудит копий памяти
- `/opt/octopus-memory-copies-audit.py`: добавлен учёт packstore (количество файлов и покрытие off-host-копией),
  бэкенд `oci_object_storage` (был только `oci` с rsync-логикой), креды Garage вынесены из хардкода в env,
  пустой memory_pool больше не считается покрытием (0/0 ≠ 1.0). Запись результата — атомарная.
- Факт: `packstore_files=45, packstore_covered=45, packstore_coverage_fraction=1.0, pack_index_v2_refs=20524, ok=true`.

## 3. SLO
- Добавлены: `packstore_offhost_copies` (P0, `packstore_files>0`, `covered==files`, `missing==0`),
  `packstore_offhost_sync_recent` (P1, <15 ч), `memory_copies_audit_fresh` (P2, <1 ч).
- Исправлен ложно-зелёный `memory_independent_copy_coverage_1_0`.
- Итог: **18/18 PASS, status=green**.

## 4. Снимок OCI Vault
- `databases.sql` был 0 байт: `pg_dumpall -U postgres` от root падал на peer-auth (тихо). Теперь
  `sudo -u postgres pg_dumpall -f /tmp/...` + перенос в staging + chmod 600 → **18.3 MB в архиве**.
- `list_objects` без `fields='name,size,timeCreated'` возвращал `size=None/time_created=None`:
  квота всегда 0 (ротация не срабатывала), `sorted()` по `time_created` упал бы. Исправлено в обоих местах.
- Реестр секретов добавлен в список файлов снимка; бакет: 0.30 GB из 18 GB (порог), 64 объекта.

## 5. Реестр секретов (требование владельца)
- Инструмент: `/opt/octopus/secrets-registry/octopus-secrets-registry.py` (`scan|list|show|fingerprint|hunt`).
- Данные: `/var/lib/octopus/secrets_registry.json` + `.md` (chmod 600). **125 записей: 64 секрета + 61 служебная переменная;
  у всех 64 секретов описано назначение.** Значения не сохраняются — только `sha256[:12]`, длина, источник (файл),
  тип (`dotenv/yaml/env/gitconfig/shell`), `first_seen`, `last_seen`, `rotated_at` и история смены отпечатка.
- Классификация: `is_secret` (отсекает `*_URL/_URI/_ENDPOINT/_HOST/_PATH/_DIR/_API/_RECEIVER` и пустые значения).
- Ежедневный скан: `octopus-secrets-registry.timer` (02:40). Репликация: файл реестра копируется в снимок OCI Vault.
- `hunt`: 30 находок хардкода (sk-or-* в config.yaml и его .bak-копиях, приватные ключи в /opt/octopus/.swarm_keys,
  /etc/octopus/id, aws-node.pem, дубли HF-токена в ingest.env и secrets.env.bak). Значения не печатались.

## 6. Зачистка утечек
- HF: публичный датасет `JoTalbot/octopus-eternal` удалён (`delete_repo`, внешняя проверка → 401). Приватным стать не мог
  (`403 exceed your private storage limit`). Канонический канал — `JoTalbot/octopus-eternal-private`.
- `/etc/octopus` полностью исключён из мастер-архива (убран из списка путей tar + exclude-паттерны).
- Данные оркестратора: 546 файлов просканировано, 17 изменено, **43 вхождения секретов** → `<REDACTED:тип>`
  (бэкапы `/root/backups/audit-2026-09-17/orchestrator-chats-20260917T060513Z/`, 64 MB, 600). Проверка: 0 остатков, 0 сломанных JSON.

## 7. Git
- `/opt/octopus`: правки закоммичены `16b5767` в ветку `arena/audit-2026-09-17-security-hardening`, запушена в origin.
- ⚠️ Локальная `main` (92 коммита) и `origin/main` (64 коммита) **не имеют общего предка** (корни 6dfecb2 vs 802ca7e),
  diff 3966 файлов; прод-сервисы работают из локального дерева. Склейка — только по решению владельца (см. варианты ниже).
- `/opt/octopus-browser`: статус и логи зафиксированы в ветке `docs/audit-2026-09-17-status-and-logs` + PR
  (иначе `/root/agents/STATUS.md` перезаписывается cron-зеркалом каждые 2 минуты).

## 8. Требуют решения владельца
- 🔴 Ротация секретов (утечка была публичной, токен был в коде и в чатах).
- 🔴 Dependabot `JoTalbot/octopus`: 36 открытых (3 critical: Next.js RCE <15.5.24 ×2, next-auth email-normalizer <0.41.3).
- 🟠 Варианты склейки git: (a) локальная история канонична → заменить origin/main (force, деструктивно для чужого среза);
  (b) две линии + cherry-pick нужного; (c) merge `--allow-unrelated-histories` (3966 файлов конфликтов).
- 🟡 Публичные `ua-*` датасеты/модели HF (7 шт.) анонимно читаемы — по смыслу открытые данные, секретов не найдено; оставлены.
- 🟡 `/opt/octopus-aios-integration` — worktree с незакоммиченным патчем (мёртвая копия multisync с прежним хардкодом).

## 9. Воспроизводимость
- Skill: `skills/core/octopus-exposure-audit-2026-09-17` (алгоритм + `code/check_public_exposure.py` + `tests/test_contract.py` 6/6 + `references/incident_2026-09-17.md`).
- Бэкапы всех изменённых файлов: `/root/backups/audit-2026-09-17/` (`.bak.<ts>`).

## 10. Постскриптум того же дня (~06:15–06:25 UTC)
- 🔴 Найден и закрыт **второй канал к noVNC**: `novnc8443.service` (socat `0.0.0.0:8443 → 172.17.0.2:6080`, запущен 03:42 UTC,
  комментарий в юните «REMOVE AFTER CHAT EXPORT»). На момент находки `http://<host>:8443/vnc.html` отвечал `200` (15 KB) —
  т.е. закрытие 6080 не закрывало доступ. Юнит остановлен + disabled + файл в бэкапы; ufw ALLOW 8443 (v4/v6) удалён, добавлен DENY;
  `DOCKER-USER`: ровно по одному DROP на 6080 и 8443 (скрипт `/opt/octopus-firewall-hardening.sh` переписан на идемпотентный).
  Внешняя проверка 6080/8443/9222 — недоступны, 22 отвечает.
- 🟡 Хронический провал `octopus-integration-test.service` (не связан с аудитом, «4 pass, 4 fail» уже 16.09 12:15):
  `127.0.0.1:9550` (DevPanel API) и `127.0.0.1:9087` (Nginx Status) никто не слушает — `octopus-devpanel-tunnel.service` disabled,
  в конфигах nginx нет `stub_status`/`nginx_status`; `https://autosklo.org.ua/` за Cloudflare → `523 Origin Unreachable`.
  Требует решения: поднять сервисы/статус-эндпоинт и оpиджин для CF либо скорректировать тест. Из-за этого SLO-чек
  `no_octopus_failed_or_autorestart_units` красный (17/18) — не регрессия аудита.
