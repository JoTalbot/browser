# 📊 STATUS — Текущий статус работы над проектом Octopus Browser

> 🔄 Обновляется каждым агентом на каждом шаге (см. `005-MULTIAGENT-PARALLEL-SKILLS.md`).
> Формат записи — добавлять новую запись сверху, не удаляя историю.

---

## 🟢 Последняя запись (2026-09-21, шаг 112 — где живёт журнал: одно правило для CLI, инструментов и юнитов)

- 🛡️ **Корень вчерашней беды — не злой gc, а молчаливый запасной путь.** `cli.py` и инструменты
  выбирали базу каждый по-своему; юнит без `EnvironmentFile=/etc/octopus/immortal-pg.env` уезжал на
  `/var/lib/octopus/immortal/ledger.db`. Пострадали два сервиса сразу: ночной gc (чужие ссылки →
  `deleted=11`) и `octopus-immortal-backup.service` — почасовой «бэкап журнала» снимал **ту базу,
  которую никто не использует**: в `/var/backups/immortal` час за часом ложились `ledger-*.db`
  вместо `ledger-*.dump`, а боевой Postgres не был заснят ни разу.
- 🤖 **Что сделано:**
  - `immortal/db.py`: `resolve_ledger_db(explicit, *, prefer_env_file, env_file)` — единое правило
    (аргумент → `IMM_DB` → `IMMORTAL_PG_DSN`/`IMM_PG_DSN` → env-файл **по запросу** → запасной путь).
    Для CLI `prefer_env_file` намеренно не включён: явный `--db` нельзя тихо подменять DSN'ом.
  - `dsn_from_env`: строка вида `КЛЮЧ = значение` (пробелы вокруг `=`) раньше не читалась —
    правка env-файла человеком молча возвращала инструмент на SQLite. Теперь читается.
  - `tools/backup_ledger.py`: база через резолвер + шаг `0) журнал: Postgres (dsn скрыт)` в начале
    вывода; `IMMORTAL_BACKUP_STRICT=1` превращает съезд на SQLite в код 1 (для тех, кто хочет, чтобы
    юнит падал, а не снимал не то).
  - Дроп-ин `/etc/systemd/system/octopus-immortal-backup.service.d/10-ledger.conf` — тот же
    `EnvironmentFile`, что у сервиса, скраббера и gc.
  - `tools/ledger_diff.py` — только читает, сверяет два журнала и площадки, и отвечает на вопрос
    «что удалит gc, если вернуть `--apply`».
- 📊 **Первая сверка:** `disk1: 11 файлов на диске, не нужны ни одному журналу — 0`,
  `disk2: 7 / 0`; ссылок только в SQLite — 29, только в Postgres — 19 (именно их gc и съедал).
  Прогон бэкапа после фикса: `0) журнал: Postgres (dsn скрыт)`, снимок `ledger-20260921T223838Z.dump` 25 910 Б,
  2 манифеста, `4) снимок положен внутрь хранилища: 872b15dde511a31f188565a53f7f7047`; SQLite за
  прогон не вырос (7 файлов / 40 ссылок как до) — почасовая запись индекса наконец идёт в живую базу.
- 🧪 145 passed на SQLite и на Postgres (+7 тестов на резолвер: приоритеты, env-файл с пробелами,
  «CLI не перехватывается»). После записи снимка `/metrics` показал `degraded_blocks 1.0` —
  `POST /v1/integrity/check` пересчитал честно: `degraded=0 lost=0 duplicate=0`; gauge
  `immortal_provider_missing_objects{provider="uguu"} = 1` остаётся, потому что это **накопительный
  счётчик** промахов с момента рестарта (uguu — бесплатный эфемерный хостинг), здоровье при этом 1.0.
- 🚀 **Что дальше:** `--apply` gc-юниту пока не возвращаю. Судя по сверке, он удалил бы ровно 8
  устаревших снимков индекса (те, что записывались в SQLite-эпоху), и больше ничего, — но решение
  о включении удаления за ночным таймером принимает владелец.

### 📜 2026-09-21, шаг 111 — ночной сборщик мусора читал не тот журнал; пин-площадка стала видимой

- 🛡️ **Главное.** `octopus-immortal-gc.service` запускал `immortal.cli … gc --apply --min-age 86400`
  **без** `EnvironmentFile=/etc/octopus/immortal-pg.env`. А `cli.py` выбирает БД так:
  `db = os.environ.get("IMMORTAL_PG_DSN") or args.db`. Без env он брал `--db` =
  `/var/lib/octopus/immortal/ledger.db` — **SQLite-журнал, оставшийся со времён до переезда на
  Postgres**, тогда как живой `octopus-immortal.service` работает с Postgres. Цифры отчёта за
  04:04 21.09 это подтверждают: `referenced` = disk1 13, disk2 7, oci 5, uguu 5, x0 7, ipfs 0 — это
  ссылки из SQLite; в Postgres на тот момент disk1 6, disk2 6, oci 6, ipfs 2, uguu 3, x0 6.
  Следствие: `deleted=11` за ночь — фрагменты, живые для Postgres, были удалены с дисков как
  «сироты». **Именно это, а не «старая потеря», дало 3 недостающие копии на disk1/disk2/oci/uguu,
  которые я нашёл вечером того же дня** (в записи шага 109 я назвал их старыми — неверно).
- 🔄 **Что сделано сразу:** дроп-ин `/etc/systemd/system/octopus-immortal-gc.service.d/10-ledger-and-dryrun.conf` — `EnvironmentFile=/etc/octopus/immortal-pg.env`
  (gc смотрит на тот же журнал, что и сервис) и `--apply` снят (режим отчёта). Проверено прогоном
  юнита: `referenced` совпали с Postgres, `deleted=0`. Сам файл юнита не изменён, бэкап рядом.
  Возвращать `--apply` можно только после сведения двух журналов в один: `tools/backup_ledger.py`
  по-прежнему пишет снимки в SQLite (`DB = os.environ.get("IMM_DB") or …`), и его копии лежат в тех
  же каталогах disk1/disk2 — при gc на Postgres они станут «сиротами».
- 🤖 **Видимость пин-площадки.** `IpfsProvider.list_objects()` + `parse_pin_ls()`: Kubo 0.43 отвечает
  одним JSON со словарём `Keys`, 0.25..0.30 — списком `[{"Cid": {"/": …}}]`, старые — потоком
  строк; параметры читаются из **query-строки** и только на POST (form-body нода игнорирует: без
  `?type=recursive` `pin/ls` отдаёт 726 записей вместо 179 — все indirect-пины).
  `delete_object` = `pin rm`; «not pinned» — не отказ площадки; байты остаются до `repo gc`,
  откат = `pin add` по списку.
- 📊 **Первая в истории перепись:** 179 recursive-пинов, живых ссылок 2, сирот **177**: 170 —
  каталожные корни эпохи битого `ipfs.put`, и **7 файлов на 5,6 МБ**, которые кому-то нужны.
  Классификация чтением через сам провайдер (`/api/v0/object/stat` в 0.43 удалён), поэтому слепое
  `--apply` не запускался: он снял бы эти 7. Отчёт и скрипт отката:
  `/var/backups/immortal/ipfs-{pins,repin}-20260921T222038Z.json|.sh`.
- 🧱 **Новое правило безопасности в `Store.gc`:** объекты, о которых провайдер не может сказать
  возраст (`mtime == 0` — так отдаёт IPFS-пин, и так же у пары объектов в OCI пустой
  `time_modified`), не удаляются, пока явно не передан `allow_unknown_age` (в CLI —
  `--allow-unknown-age`). Причина: пин ставится раньше, чем в журнале появляется строка.
  Побочный эффект, о котором надо знать: OCI-объекты с пустым `time_modified` теперь тоже берегутся
  (сегодня это 2 штуки, которые прежний gc удалял).
- 📚 **Заодно исправлено:** `/opt/octopus-ipfs-gc.sh` разыскивал контейнер
  `octopus_ipfs_ipfs_node.1.wm61v638laaxiwsjfmmx8ky0w` (времен swarm), не находил, печатал
  «SKIP: container not found» и выходил 0 — т.е. `repo gc` не выполнялся никогда, а юнит делал
  вид, что работает. Теперь он говорит с API ноды, пишет `блоков/МБ/пинов` каждый запуск, а само
  удаление требует `IMMORTAL_IPFS_REPO_GC=1` в `/etc/octopus/ipfs-gc.env` (сейчас 0).
- 🧪 13 новых тестов, **138 passed** на SQLite и на Postgres. Бэкапы: `.bak.20260921T222038Z` у
  `ipfs.py`, `store.py`, `cli.py`, `octopus-ipfs-gc.sh`, `octopus-immortal-gc.service`, STATUS.md,
  STEP_STATUS.json, PROGRESS.md.
- 🚀 **Что дальше:** свести `tools/backup_ledger.py` на Postgres (одна строка) и только потом
  включать `--apply` обратно; решить, чьи 7 файловых пинов на ноде; `degraded/lost` по-прежнему 0.

### 📜 2026-09-21, шаг 110 — публичный контур: домен-монитор оказался заглушкой

- 🛡️ **Что нашли:** `/opt/octopus-domain-monitor.sh` был **заглушкой на 8 строк** — он дописывал
  в `/var/log/octopus-tg-suppressed.log` строку «policy: direct_chat_push_disabled_wave2» и выходил
  с кодом 0, не проверяя ничего. Юнит назывался `Octopus Public Domain Monitor (autosklo.org.ua)`,
  таймер честно срабатывал каждые 5 минут. Именно поэтому висящий с 19.09 публичный сайт не был виден
  ни в логе, ни в `health.json`, ни в интеграционном тесте.
- 📊 **Настоящее положение публичного контура (замерено с сервера, 2026-09-21T19:51:26Z):**
  `autosklo.org.ua` и `www.autosklo.org.ua` → **HTTP 522** от Cloudflare через ~19 с (край жив,
  TLS-handshake проходит, сертификат валиден ещё 36 дн., A-запись отдаётся — 104.21.76.233/
  172.67.202.19), т.е. **origin за proxied-записями не принимает соединения**;
  `api.autosklo.org.ua` → 302 (тот же IP Cloudflare, origin отвечает);
  `store.autosklo.org.ua` → 200 (сервер 129.213.177.56, DNS-only).
  Причина — вне этой машины: в зоне Cloudflare/на другом origin. Правки зоны и DNS не делались.
- 🤖 **Что сделано:**
  - `octopus-domain-monitor.sh` переписан: для 4 адресов — HTTP-код, A-запись через внешний
    резолвер 1.1.1.1 (сервер сам себе не судья), дней до конца сертификата; запись атомарно
    (`tmp` + `os.replace`) в `/run/octopus/domain_status.json`; `DOMAIN ALERT` в
    `/var/log/octopus-domain.log` только при СМЕНЕ состояния; намерение уведомить по-прежнему
    ложится в suppressed-лог (автономные пуши в чат запрещены политикой, это не обход).
    Первый таймаут 12 с не досматривал до конца: край CF отвечает 522 на ~19 с → поднято до 30 с.
  - `/opt/octopus-unified-health.py`: добавлены секции `agents` (шина hermes с хостового
    `:9725/metrics`: `bus_up`, `nodes_known`, `agents_defined`, `pending`, `pending_overdue`) и
    `domain` (читает JSON монитора). В `overall` домен намеренно НЕ входит: origin apex живёт не
    здесь, а красить весь статус — способ научить команду игнорировать красный цвет.
  - Проверено: `py_compile`, прогон вручную (40 с), запуск через `systemd-run` (юнит не падает),
    `agents.ok = true` (3 узла, `pending_overdue = 0`), `domain.ok = false` с обоими 522.
- 📚 **Важно для следующих шагов:** `/opt/octopus-*.py|sh` (мониторы, health, интеграционный тест)
  **не лежат ни в одном git-репозитории** — `git -C /opt/octopus ls-files | grep -c unified-health` = 0.
  Правки там живучи (watchdog их не трёт), но версионирования нет: после каждой правки держать
  `.bak.<UTC>` рядом и не удалять 48 ч.
- ⚠️ **Мой предыдущий вывод требует уточнения:** я писал «apex/www недоступны извне» как про
  недоступность сервиса. Точная формулировка: сервис отвечает — это Cloudflare сообщает, что не может
  достучаться до origin (522). Разница принципиальна: чинить надо не nginx на этой машине.
- 🚀 **Что дальше:**
  - Владельцу: проверить в Cloudflare, на что указывают proxied-записи `@` и `www` (origin-хост/порт,
    есть ли там живая машина), либо перевести apex/www на этот же origin, что и `api.`.
  - Решить, входить ли домен должен в `overall` (одна строка в `/opt/octopus-unified-health.py`).
  - `list_objects` для IPFS-площадок + 173 сироты на пининг-ноде (шаг 111, задуман).

### 📜 2026-09-21, шаг 109 — IPFS-площадки снова отдают своё, «нет файла» ≠ «узел сломан»

- 🖥️ **Агент/машина:** Arena Agent (hermes-node-01 / arm-server-01)
- 🎯 **Шаг:** догнать хранилище до состояния «ноль тревог»: починить чтение на IPFS-площадках,
  разделить «копии нет» и «площадка мертва», приоритет якорей при ремонте, правда в мониторинге,
  swap, `--init` на нодах, перевыпуск ssh-ключа.
- 🐞 **Найдено (корень всех «вечных» деградаций с 19.09):**
  - `providers/ipfs.py` разбирал ответ `/api/v0/add` как один JSON, а Kubo отвечает **потоком
    JSON-строк** (файл + каталог). `resp.json()` падал с «Extra data», поэтому IPFS не мог
    записать ни одной копии; объект при этом успевал запиниться → сироты на ноде.
  - `put` слал имя вида `<file_id>/<блок>/<фрагмент>`; IPFS/Pinata заворачивают путь в **каталог**,
    корень DAG — директория, а `cat` по её CID отвечает «this dag node is a directory», и шлюз
    отдаёт HTML-листинг с кодом 200. Отсюда «площадка записала, но перечитать невозможно»,
    и ремонт отбраковывал копию.
  - отсутствие объекта (`local: нет объекта`, 404 у бесплатных хостингов, 404 в OCI) записывалось
    в `stats.fail` → здоровье живого диска падало до 0.05/0.0, `ImmortalProviderUnhealthy` горел
    сутками, а placement обходил нормальные площадки.
- ✅ **Сделано (шаг 109, `/opt/octopus/immortal-store`):**
  - `providers/base.py`: новый `ObjectMissing(ProviderError)`, `ProviderStats.miss` и
    `record_miss()`; `safe_get()` на «нет объекта» не включает cooldown и не портит здоровье.
  - `providers/ipfs.py`: плоское имя (`_flat`), разбор потока JSON (`root_hash`) с явным
    запретом возвращать CID каталога, `cat` 404/«no link» → `ObjectMissing`.
  - `providers/pinning.py`: то же плоское имя в `put`, `get` больше не принимает HTML-страницу
    шлюза за данные (`_is_gateway_page`), «нет ни на одном шлюзе» → `ObjectMissing`.
  - `providers/anon.py` (6 мест чтения), `providers/local.py`, `providers/oci_native.py`:
    404/410/отсутствие файла → `ObjectMissing`.
  - `store.py`: `Store._repair_site_order()` — свои якоря первыми, эфемерные (`uguu`, `x0`,
    протухающие через сутки) в конце; отчёт `repair` теперь `{repaired, failed, unrecoverable,
    unverified, reasons[]}`, где `unverified` = «записали, но вернули другие байты».
  - `metrics.py`: `immortal_provider_missing_objects{provider=…}` — число отсутствующих копий
    видно отдельно от здоровья.
  - тесты: `tests/test_step109_ipfs_and_missing.py` (15 шт.) — **125 passed** на SQLite и
    **125 passed** на Postgres (`immortal_test`). Их `test_repair_tries_another_provider_when_first_refuses`
    сначала сломался моим `q.tier` (у тестового двойника нет атрибута) — поправлено на
    `getattr(q, "tier", "anchor")`, тест зелёный.
- 📊 **Результат в проде (`repair_now.py` после деплоя):** `cas-object.bin` → `repaired: 1`,
  `live.bin` → `repaired: 2`, «после: целых=1/2, деградировало=0». Метрики:
  `immortal_degraded_blocks 0`, `immortal_lost_blocks 0`, `immortal_duplicate_provider_chunks 0`,
  здоровье всех 7 площадок 1.0. Невосстановимые демо-строки сняты с активной версии
  (`versions.supersede`, откат `versions.restore`), `_manifests.jsonl` пересоздан их же
  `tools/backup_ledger.py`; страховка реестра —
  `/var/backups/immortal/ledger-before-repair-20260921T183155Z-full.sql.gz`.
- 🧾 **Эксплуатация:**
  - swap 2 GiB (63.7 % занято) → добавлен `/swapfile2` 4 GiB, всего **6 GiB**, запись в
    `/etc/fstab` (бэкап `fstab.bak.20260921T193727Z`); `vm.swappiness=15` не трогал.
  - зомби: `hermes-node-02/03` пересозданы **с `--init`** через `docker commit` слоя
    (`local/<нода>:snap-20260921T193727Z`), PID 1 = `docker-init`, демоны подняты, `hermes_nodes_known=3`,
    `pending_overdue=0`. Старые контейнеры сохранены как `<нода>-preinit` (откат).
  - `/opt/octopus-integration-test.sh`: две проверки вели в никуда (`:9550` — юнит
    `octopus-devpanel` удалён, `:9087` — статуса nginx нет). Заменены на реальные
    (`immortal /health`, `шина :9725/metrics`, `CAS :9540/`); проверка наружного сайта
    оставлена: `autosklo.org.ua` и `www.` не отвечают с 19.09 (проверено с сервера и извне,
    `api.` 302 и `store.` 200 живые). Результат: **8 pass / 1 fail** вместо «5 pass / 3 fail».
  - `/opt/octopus-unified-health.py`: те же мёртвые адреса убраны, добавлены `immortal` и
    `agent_bus`; `cas` проверяется по `/` (на `/health` там 401 — под ключом).
  - секреты: выпущен новый ed25519-ключ и добавлен в `~/.ssh/authorized_keys` (бэкап файла
    сохранён); старый RSA-ключ (`SHA256:HpoCySL5YAQkK5vblU89h9RKyABVxpmHL+lJfkcGKCw`),
    который светился в чате, **ещё работает и ждёт удаления владельцем**.
- 🔍 **Как проверить:**
  `cd /opt/octopus/immortal-store && sudo env -u IMMORTAL_PG_DSN -u IMM_PG_DSN IMM_DB=$(mktemp -d)/l.db
   /opt/octopus-ingest-venv/bin/python -m pytest -q tests` — 125 passed;
  `curl -s 127.0.0.1:8123/metrics | grep -E "^immortal_(lost|degraded|duplicate|provider_health|provider_missing)"`;
  `sudo docker exec hermes-node-02 ps -o pid,comm -p 1` → `docker-init`;
  `sudo /opt/octopus-integration-test.sh` → 8 pass / 1 fail.
- ⚠️ **Остерегающие выводы (для тех, кто придёт после):**
  1. `db.dsn_from_env()` при пустом окружении читает `/etc/octopus/immortal-pg.env` → любой
     `tools/*.py` без явного `IMM_DB` идёт в прод. Тесты безопасны (без `IMM_TEST_PG_DSN`
     `Ledger` в `:memory:`), инструменты — нет.
  2. `promtool`/`/api/v1/rules` в Prometheus 3.x не принимает `?type=alerting` — только `?type=alerts`.
  3. Watchdog (`cron`, раз в 2 мин) делает `git checkout main` и перетирает `/root/agents/` из
     репозитория: правка документации, не дошедшая до `main`, исчезает при следующем проходе.
  4. «Площадка здорова» и «копия на месте» — два разных факта; смешивать их в одном счётчике
     нельзя: получишь вечно горящий алерт и placement, обходящий живые диски.
- 📚 **Дальше:** влить 9 открытых dependabot-PR (в `#23` next→16.3.3, в `#6` next-auth→4.24.15 —
  это 3 critical: неаутентифицированный RCE в Next.js); решить про apex/www сайта; `list_objects`
  для ipfs, чтобы сборщик мусора видел сироты на пининг-ноде.

---

### 📜 2026-09-21, шаг 108 — ссылка «на запись» и порядок на ноде

- 🖥️ **Агент/машина:** Arena Agent (сервер `arm-server-01`, OCI, `129.213.177.56`)
- 🎯 **Шаг:** step_108 — права на запись в общую папку, лимиты папки, закрытие зомби, догонка документации за 105–107
- ✅ **Сделано:**
  - 🔐 `shares` научился правам: `allow_write`, `allow_delete`, `allow_overwrite` и лимитам
    `max_uploads`, `max_total_bytes`; ведутся счётчики `uploads`/`bytes_written`, в ответ
    отдаётся остаток (`uploads_left`, `bytes_left`, `downloads_left`).
  - 🚪 Новые концы: `PUT /d/{token}/{путь}` и `POST /d/{token}` (голое тело или форма —
    та самая форма загрузки на странице папки), `DELETE /d/{token}/{путь}` по `allow_delete`,
    `GET /v1/shares/{token}` (права и расход), `PUT /v1/shares/{token}/limits`
    (поменять права и лимиты, не пересоздавая ссылку).
  - 🧱 Три обязательные границы: права самой ссылки, **квота владельца** (аноним не должен
    раздувать чужое хранилище) и потолок одного запроса (`IMM_SHARE_MAX_UPLOAD`, по
    умолчанию 1 ГиБ); пишем во временный файл, а не в память.
  - 🛡️ Имя фильтруется до записи: `..`, абсолютный путь, управляющие символы, длина; файл
    всегда попадает внутрь `prefix` и принадлежит владельцу папки. Чужие файлы той же
    папки не видны и не удаляются.
  - 🩺 Миграция стала самолечащейся: `ALTER TABLE ... ADD COLUMN` на Postgres рождал
    `int4`, и счётчик байтов переполнялся на 2 ГиБ — теперь колонки объявлены `BIGINT`, а
    узкая колонка в живой базе расширяется при старте. Прод-база проверена: все четыре колонки стали bigint.
  - 🧪 Тесты: **110/110** и на SQLite, и на Postgres (добавлено 29). Живая HTTP-проверка
    отдельным uvicorn-инстансом на `immortal_test` (прод не тронут): 20/20, включая
    multipart-форму, `root_path` в ссылках, 429 по лимиту загрузок и 413 по лимиту байтов.
  - 🧹 Порядок на хосте: 8 зомби в `hermes-node-02/03` закрыты; внутри нод оставлен
    `/root/relaunch-daemons.sh` + `/root/node-daemons.env`, копии на хосте в
    `/root/hermes-nodes/<узел>/` — раньше демоны нод не поднимал никто после рестарта.
  - 📚 Документация: `STATUS.md` догнан за 105–107 (отставал на 13 дней), `STEP_STATUS.json`
    дополнен шагом 108, код хранилища поставлен в git (был полностью untracked).
- 🔍 **Как проверить:**
  - `cd /opt/octopus/immortal-store && sudo /opt/octopus-ingest-venv/bin/python -m pytest -q tests`
  - `curl -s 127.0.0.1:8123/health`, `curl -s 127.0.0.1:8123/metrics | grep immortal_share`
  - ссылка с записью: `POST /v1/shares {"prefix":"Обмен/","allow_write":true,"max_uploads":5}`
    → `PUT /immortal/d/{token}/файл.txt`; отказ без прав: тот же запрос → 403.
  - зомби: `ps -eo stat --no-headers | grep -c "^Z"` → 0.
- ⚠️ **Замечания:** swap 63.7 % (1.3/2 ГиБ) — пора либо расширить, либо ограничить
  `chrome`/`ipfs`/`grafana` (№18.4); PID 1 в `hermes-node-02/03` — `sleep infinity`, он не
  пожинает детей, поэтому зомби будут возвращаться (~4/сут на узел), пока контейнеры не
  пересозданы с `--init`; GitHub-PAT лежит в `.git/config` обоих репозиториев — под ротацию.
- 🚀 **Что дальше:** решить swap/`MemoryMax`; пересоздать ноды с `--init` (окно ~10 с);
  второй якорь вместо Pinata; превью PDF/видео; второй сервер для настоящей избыточности.

- 🚨 **Найдено по ходу (21.09, вечер) — требует решения владельца:**
  - **Хранилище хронически недореплицировано** (`lost_blocks` 3, `degraded_blocks` 3,
    здоровье `uguu` 0.05). Первоначальный диагноз — «`Store.repair` возвращает фрагмент на ту
    же площадку, а uguu не принимает больше 1 МБ» — **оказался неверным**: код ремонта уже
    исключает площадки блока и ищет свободные (`placement.choose(3, exclude=used)`), а uguu
    принимает и 1,4 МБ. Настоящая причина вскрыта на шаге 109: обе IPFS-площадки не могли
    отдать то, что записали, — свободных здоровых площадок не оставалось вовсе.
  - **Два демо-файла восстановить было нельзя в принципе:** `Демо/заметка.txt` (62 Б) и
    `Демо/картинка.png` (5,4 КБ) — у блока выжила 1 копия из 5 при k=3, а уцелевшая копия
    оказалась чётным (паритетным) фрагментом, так что байты не собираются. Разбор (шаг 109):
    `live.bin` и `cas-object.bin` починились, `_manifests.jsonl` пересоздан `backup_ledger.py`,
    невосстановимые строки сняты с активной версии через `versions.supersede` (откат —
    `versions.restore`), их байты на `x0` не тронуты. Решение за владельцем: перезалить демо-файлы с исходника
    или признать потерей и убрать их из реестра. Перед любым ремонтом дамп лежит в
    `/var/backups/immortal/ledger-before-repair-20260921T183155Z*.sql.gz`.
  - **Ложная тревога, которую стоит запомнить:** после моих прогонов число файлов в
    `GET /v1/stats` казалось уменьшившимся (13 → 5). Ничего не терялось: `immortal_files_total`
    = 5 с 19.09 16:45 без провалов, в продовом Postgres те же 5 строк, в SQLite-зеркале тот
    же список из 7 файлов; удалённых строк нет (за смену прибавилось 3 блока и 1 запись
    `shards` — следствие ремонта 18:31, и у одной строки `files` сменился `file_id` при
    пересоздании версии). Тестовый набор безопасен по умолчанию: `tests/conftest.py`
    переключается на Postgres **только** при `IMM_TEST_PG_DSN`, а без него `Ledger` живёт в
    `:memory:`. Опасность в другом: **отдельные инструменты** (`tools/*.py`, в том числе наш
    `live_check_share_write.py`) зовут `db.dsn_from_env()`, которая при пустом окружении сама
    читает `/etc/octopus/immortal-pg.env`, — то есть идут в прод. Перед прогоном инструмента
    вне `tests/` явно ставьте `IMM_DB=$(mktemp -d)/l.db` и убирайте `IMMORTAL_PG_DSN`
    и `IMM_PG_DSN`, либо используйте тестовую базу из `/etc/octopus/immortal-pg-test.env`.
  - **Их же почасовой тест красен с 19.09 16:15:** `octopus-integration-test.service` —
    5 pass / 3 fail (`DevPanel API :9550` — юнит `octopus-devpanel-tunnel.service` мёртв,
    порт не слушается; `Nginx Status :9087/nginx_status` — such a listen-блок в конфиге
    отсутствует; `Public Site HTTPS https://autosklo.org.ua/` — Cloudflare не отвечает
    отсюда). Кто-то регулярно делает `reset-failed`, поэтому в `systemctl --failed` пусто
    и алерт не рождается: тихий отказ в системе, которая как раз от тихих отказов и защищена.
  - **GitHub:** в default-ветке `JoTalbot/octopus` 36 уязвимостей Dependabot
    (3 critical, 21 high, 12 moderate) — https://github.com/JoTalbot/octopus/security/dependabot.
    Сам я там ничего не ставил и `pip install -U` не делал: латать зависимости надо вместе
    с прогоном тестов.
---

### 📜 2026-09-19 — шаги 105–107 (дописано задним числом 21.09 — см. `STEP_STATUS.json`)

- 🖥️ **Агент/машина:** Arena Agent (та же нода)
- 🎯 **Шаг:** Postgres-журнал, мониторинг с алертами, раскладка копий и шаринг папок
- ✅ **Сделано:**
  - **105:** журнал переведён на Postgres (`immortal_db`) с SQLite-запасом, слой
    совместимости в `immortal/db.py` (плейсхолдеры, upsert, autocommit), 173 строки
    мигрированы, `GET /metrics`, 63/63 теста на обеих базах.
  - **106:** Prometheus + алерты (7 правил) + дашборд на 13 панелей, `GET /v1/search`,
    честный контроль целостности (реальное чтение и сверка sha256) вместо просмотра
    журнала, `pg_dump` вместо копирования устаревшего SQLite-файла, починка пробует до
    трёх площадок. 70/70 тестов.
  - **107:** копии одного блока больше не садятся на одну площадку (запись, повтор,
    починка, перенос), `Store.rebalance`, чтение с неверной суммой = отказ площадки
    (Pinata потеряла доверие), шаринг папок `POST /v1/shares` + `GET /d/{token}`,
    кириллица в `Content-Disposition`, превью картинок и текста. 81/81 тестов.
- 🔍 **Как проверить:** `/opt/octopus-monitoring/{rules,dashboards}/immortal-*`,
  `python3 /opt/octopus/immortal-store/tools/drill_integrity.py`, `rebalance_now.py`.
- ⚠️ **Замечания:** запись этих трёх шагов в `STATUS.md` не была сделана вовремя —
  нарушен п.5 свода правил; сейчас разрыв закрыт.

---

### 📜 2026-09-08 — Фаза 7 evidence (была последней)

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 7 — Production Gate evidence: drills + вердикт гейта
- ✅ **Сделано:**
  - 💾 Бэкап: фикс пустых каталогов + тест; drill на прод-данных: backup/verify/restore, строгий diff MATCHES.
  - 📦 Откат: v0.3.2 без бинарных ассетов → tag-as-artifact drill (install + jobs/vault/version OK); процедура revert-PR.
  - 🔑 Ротация: сессии A→B (B читает, A отвергнут) + proxy creds old→new; runbook docs/BACKUP.md.
  - 🔌 Mock-proxy live: health/cooldown/rotation/stats на прод-хосте (частичное evidence пункта 4).
  - 💥 Хаос: sandbox kill -9 → state survived (лиз/задача/события); prod restart 08:48 → active + 200/200.
  - 📊 Soak: suite 2× + load 3× зелёные; deploy runs evidence; health/ready 200 (0.4.0), protected 503 fail-closed.
  - 📝 Гейт: checked 1/5/6/7/8; open 2 (нет ключа, partial), 3 (skip), 4 (mock, partial). v1.0.0 BLOCKED.
- 🔍 **Как проверить:** PR → Actions зелёный; после merge — тег v0.4.0 → релиз-артефакт для будущих откатов.
- ⚠️ **Замечания:** v1.0.0 ждёт OCTOPUS_API_KEY + решения по E2E-браузерам и live-proxy; v0.3.x без бинарных ассетов.
- 🚀 **Что дальше:** merge → тег v0.4.0 → план закрыт кроме заблокированных пунктов; следующие шаги за пользователем.

---

### 📜 2026-09-08 — Фаза 7 инструмент бэкапа (был последним)

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 7 — Production Gate: инструмент шифрованного бэкапа + версия 0.4.0
- ✅ **Сделано:**
  - 💾 backup.py: AESGCM-конверт, sha256-манифест, verify без записи, restore только в пустой каталог; CLI backup/restore/verify/genkey.
  - 🧪 tests/test_backup.py: round-trip, tamper/wrong-key, защита назначения, CLI-цикл через subprocess.
  - 🔢 Версия 0.4.0: pyproject + api + CHANGELOG синхронны; решения пользователя по скоупу гейта (E2E пропустить, mock-live, рестарт прод ок, откат в песочнице).
- 🔍 **Как проверить:** PR → Actions зелёный; после merge — drill бэкапа прод-данных в /tmp.
- ⚠️ **Замечания:** evidence гейта — следующим PR после прогона drill-ей; пункты 2/3/4 частично заблокированы (нет OCTOPUS_API_KEY, нет браузеров, proxy=mock).
- 🚀 **Что дальше:** merge → deploy → drills (backup/rollback/rotation/mock-proxy/chaos/restart/soak) → PR evidence → тег v0.4.0.

---

### 📜 2026-09-08 — Фаза 6 (была последней)

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 6 — AIOS интеграция (события, координация, durable-очередь)
- ✅ **Сделано:**
  - 🔍 Разведка: octopus-aios-bridge v1.1.0 жив (:9600, kernel running); events-ingress нет → решение 8 (pull + опциональный push).
  - 🔗 aios.py: AIOSEvent (envelope v1) + EventLog (JSONL, cursor, prune) + EventDispatcher (HMAC/idempotency/pending/outbox/flush) + AIOSBridge probe.
  - 🔒 leases.py: ProfileLeaseManager (TTL, персистентность, refresh); API лизов 201/409/404; opt-in require_lease в agent jobs.
  - 📦 JobManager: JSON-персистентность + восстановление после рестарта; jobs_queued; Retry-After на 429.
  - 🔌 API: /aios/events, /aios/events/flush, /aios/status; события started/finished/failed/leased/released; capabilities +3.
  - 🧪 tests/test_aios.py: лог/пуш/лизы/durable/backpressure/E2E webhook с проверкой HMAC.
- 🔍 **Как проверить:** PR → Actions зелёный; после merge — GET /aios/status (нужен OCTOPUS_API_KEY), живой бридж отвечает.
- ⚠️ **Замечания:** push идёт только если задан AIOS_EVENTS_WEBHOOK_URL; live E2E задач ждёт OCTOPUS_API_KEY.
- 🚀 **Что дальше:** Фаза 7 — Production Gate.

---

### 📜 2026-09-08 — Фаза 5 (была последней)

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 5 — Agent runtime hardening (pre/postconditions, retries, recovery, cancel, deadlines, verification)
- ✅ **Сделано:**
  - 🤖 agent.py: AgentPlanner-абстракция, ActionValidationError со структурированными issues, bounded retries (backoff) + recoveries (reload/re-observe), stale-классификация.
  - 🤖 Отмена (threading.Event, кооперативная), дедлайны (инжектируемый clock), верификация цели (verify_fn + confidence gate), состояния CANCELLED/TIMEOUT.
  - 🔌 API: кооперативная отмена running-задач, deadline_seconds в AgentTaskIn, retries/recoveries/verified в результатах, метрики agent_*.
  - 🧪 tests/test_agent_hardening.py (16 тестов) + tests/test_agent_load.py (100 задач: 90 done / 5 cancelled / 5 timeout).
  - 📝 ROADMAP Phase 3 закрыта полностью; CHANGELOG/STATUS обновлены.
- 🔍 **Как проверить:** PR → Actions зелёный; после merge — POST /agent/jobs + cancel running-задачи (нужен OCTOPUS_API_KEY).
- ⚠️ **Замечания:** отмена кооперативная (проверки на границах шагов/ретраев); live E2E с реальным браузером — после ключа API.
- 🚀 **Что дальше:** Фаза 6 — AIOS интеграция; Фаза 7 — Production Gate.

---

### 📜 2026-09-08 — микрофикс vision-логирования (был последним)

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Диагностика live-vision — логирование упавших failover-ног VisionRouter
- ✅ **Сделано:**
  - 🔍 Live-проверка: `POST /vision/analyze` → 200 через gemini-fallback (latency ~1.2s); нога balancer падает молча.
  - 📝 Адаптер `vision.py`: `log.warning` на каждую упавшую ногу (провайдер + тип ошибки + усечённое сообщение, без секретов).
  - 📝 STATUS: исправлено имя теста `tests/test_vision.py` → `tests/test_browser_vision.py`.
  - 📝 HTTP-ошибки ног включают усечённый ответ гейтвея (диагностика balancer HTTP 400).
- 🔍 **Как проверить:** после merge — live `/vision/analyze` + `journalctl -u octopus-browser-aios-adapter | grep 'vision leg'`.
- ⚠️ **Замечания:** ключи vision берутся из `/etc/octopus/secrets.env` (unit читает его первым); значения ключей не читались.
- 🚀 **Что дальше:** по причине из журнала — чинить balancer-ветку или оставить gemini-fallback; затем Фаза 5.

---

### 📜 2026-09-08 — Фаза 4 (была последней)

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 4 revised — Vision через внешний API адаптера (без локальных моделей, решение 7)
- ✅ **Сделано:**
  - 🔌 Адаптер: POST /vision/analyze поверх VisionRouter (gemini/groq/balancer + failover) + тесты 200/400/503.
  - 👁️ Браузер: VisionProvider (adapter/openai/mock), VisionFrame fusion, VisionGrounding, VisionBudget, VisionCache, реестр промптов.
  - 🔌 API: POST /vision/analyze (describe/decide/ground), GET /vision/status; метрики vision_*; capability vision-analyze.
  - 🧪 tests/test_browser_vision.py: провайдеры на MockTransport, failover, бюджет, кэш, граундинг, API (400/422/429).
  - 📝 DECISIONS.md #7; ROADMAP Phase 4 почти закрыта (кроме OCR — deferred).
- 🔍 **Как проверить:** PR → Actions зелёный; после merge + ключей — GET /vision/status, live /vision/analyze.
- ⚠️ **Замечания:** live-проверка требует ключей в /etc/octopus/browser-aios-adapter.env + ALLOW_EXTERNAL_VISION=1 (ставит пользователь); OCR отложен.
- 🚀 **Что дальше:** Фаза 5 — Agent hardening; Фаза 6 — AIOS интеграция; Фаза 7 — Production Gate.

---

### 📜 2026-09-08 — Фаза 2

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 2 — ProxyProvider + mock + vault-credentials + health-rotation (по решению 1)
- ✅ **Сделано:**
  - 🧩 Абстракция ProxyProvider: StaticListProvider (PROXY_LIST) + MockProxyProvider (скриптованный, без сети).
  - 🔐 ProxyCredentialStore: credentials в шифрованном JSON через SessionVault; secret_ref в entry; redact везде.
  - 🔀 Health-aware ротация: scoring, экспоненциальный cooldown, refresh_health(), персистентность data_dir/proxies.json.
  - 🔌 API: GET/POST/DELETE /proxies, GET /proxies/health, POST /proxies/rotate, POST /proxies/credentials; метрики proxies_*.
  - 🧪 tests/test_proxy.py: unit + API-тесты (mock, vault-roundtrip, backoff, персистентность, 400/404/503).
- 🔍 **Как проверить:** PR → Actions зелёный; после merge — GET /proxies/health, skill deploy-verify.
- ⚠️ **Замечания:** live-провайдеры — отдельным решением (mock по DECISIONS.md #1); refresh_health с реальными прокси — последовательные проверки.
- 🚀 **Что дальше:** Фаза 4 — Vision на локальном Ollama (Фаза 3 пропущена по решению 2).

---

### 📜 2026-09-08 — Фаза 1

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 1 — адаптер AIOS в монорепо + skills/deploy-verify
- ✅ **Сделано:**
  - 📦 Импортирован /opt/octopus-browser-aios-adapter в integrations/browser-aios-adapter/ (ветка feat/phase1-adapter-monorepo).
  - ⚙️ Добавлен CI-job adapter; quality-job ставит оба пакета.
  - 🚀 deploy/server-update.sh ставит systemd-unit адаптера из Git и рестартит сервис.
  - 🔧 Починен рестарт деплоя: grep -q под pipefail умирал по SIGPIPE (exit 141) и рестарт не выполнялся никогда — прод висел на коде от 03.09; теперь предикат через systemctl cat, применение через .applied_commit, защита от гонок через flock; quality-гейты deploy/release тоже ставят пакет адаптера.
  - 🧬 Создан skills/deploy-verify (SKILL.md + verify_deploy.py + тесты).
  - 📝 CHANGELOG: секция [Unreleased].
- 🔍 **Как проверить:** PR → Actions зелёный; после merge — systemctl status octopus-browser-aios-adapter и /health адаптера.
- ⚠️ **Замечания:** старый каталог /opt/octopus-browser-aios-adapter переместим в .bak только после проверки нового юнита.
- 🚀 **Что дальше:** Фаза 2 — ProxyProvider + mock (по решению 1).

---

### 📜 2026-09-08 — Фаза 0

- 🖥️ **Агент/машина:** Arena Agent (сервер arm-server-01, OCI, 129.213.177.56)
- 🎯 **Шаг:** Фаза 0 — фиксация продуктовых решений в docs/DECISIONS.md
- ✅ **Сделано:**
  - 📋 Получены 6 решений: proxy=mock, VPN=отложен, vision=только локальный Ollama, адаптер=монорепо, без OIDC, Web UI позже.
  - 📄 Создан docs/DECISIONS.md (PR из ветки feat/phase0-decisions).
- 🔍 **Как проверить:** cat docs/DECISIONS.md; GitHub → PR → Actions зелёный.
- ⚠️ **Замечания:** нет.
- 🚀 **Что дальше:** Фаза 1 — адаптер в монорепо + skills/.

---

## 📜 Предыдущие записи

- 🖥️ **Агент/машина:** Arena Agent (сервер `arm-server-01`, OCI, `129.213.177.56`)
- 🎯 **Шаг:** Первичная установка Octopus Browser на сервер + активация авто-деплоя
- ✅ **Сделано:**
  - 🔀 Смержен PR #1 (каркас проекта + агентские инструкции) в `main`.
  - 📥 Репозиторий склонирован на сервер в `/opt/octopus-browser`.
  - 🐍 Установлено виртуальное окружение и зависимости (`requirements.txt`).
  - ⚙️ Создан и запущен systemd-сервис `octopus-browser` (порт `8095`, `8090` был занят).
  - 🧲 Настроен резервный cron-watchdog (`*/2 * * * *` → `deploy/server-update.sh`).
  - 🚀 Активирован workflow `.github/workflows/deploy.yml` (push в `main` → сервер).
  - 🔑 Пересоздан выделенный deploy-ключ `octopus-browser-deploy` (только для `ubuntu`,
    не совпадает с root-only ключом `oci-arm-server`); обновлён `DEPLOY_SSH_KEY`,
    `DEPLOY_USER=ubuntu`, `DEPLOY_PATH=/opt/octopus-browser` в GitHub Secrets.
  - 📚 Инструкции синхронизированы в `/root/agents/` на сервере.
  - 📄 Добавлены `005-MULTIAGENT-PARALLEL-SKILLS.md` и этот файл статуса.
- 🔍 **Как проверить:**
  - `curl http://<host>:8095/health` → `{"status":"ok", ...}`
  - GitHub → Actions → `Deploy Octopus` → последний запуск зелёный.
  - На сервере: `cat /var/log/octopus-update.log`, `systemctl status octopus-browser`.
- ⚠️ **Замечания:**
  - Реальные интеграции прокси/VPN/vision — ещё заглушки (см. `docs/ARCHITECTURE.md`,
    раздел Roadmap).
  - Порт по умолчанию в `.env.example` (`8090`) занят на этом сервере другим сервисом;
    на этом сервере используется `8095` (см. `/opt/octopus-browser/.env`).
- 🚀 **Что дальше:**
  - Создать каталог `skills/` и первый Skill по итогам первичного деплоя.
  - Реализовать реальные модули: proxy-провайдеры, VPN-адаптер, vision-модель.
  - Подключить интеграцию с `JoTalbot/octopus` / `JoTalbot/AIOS` (webhook/модуль).
