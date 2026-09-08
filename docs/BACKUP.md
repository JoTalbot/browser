# 💾 Backup, rotation & rollback runbook

Операционные процедуры восстановления Octopus Browser. Проверены drill-ями Фазы 7 (2026-09-08), evidence — в `docs/PRODUCTION-GATE.md`.

## Шифрованный бэкап `data_dir`

Формат: AESGCM-конверт (`SessionVault`, associated data `octopus-backup-v1`), внутри — tar.gz + sha256-манифест + список каталогов. Пустые каталоги сохраняются.

```bash
# 1. Ключ (один раз; хранить в secrets, НЕ коммитить)
python scripts/backup.py genkey   # -> OCTOPUS_BACKUP_KEY=...

# 2. Бэкап (откажет, если out существует)
export OCTOPUS_BACKUP_KEY='...'
python scripts/backup.py backup --data-dir /opt/octopus-browser/data --out /tmp/prod-$(date +%F).obak

# 3. Проверка без записи
python scripts/backup.py verify --in /tmp/prod-....obak

# 4. Восстановление ТОЛЬКО в пустой каталог (защита прода — в непустой откажет)
python scripts/backup.py restore --in /tmp/prod-....obak --to-dir /tmp/restored
diff -r /opt/octopus-browser/data /tmp/restored   # строгая сверка
```

## Ротация ключей vault (сессии)

```bash
# Процедура: перешифровать каждый *.session старым ключом -> новым (associated_data = session id).
# Drill: save/load с ключом A -> rotate A->B -> load с B ok, load с A -> ValueError.
# Продьюс: остановить запись сессий (maintenance), rotate, сменить SESSION_ENCRYPTION_KEY, рестарт, verify.
```

## Ротация proxy credentials

Через API (`POST /proxies/credentials` с тем же `ref` перезаписывает) или `ProxyCredentials.set()` — drill показал old→new без простоя чтений.

## Ротация OCTOPUS_API_KEY (процедура, выполнение ждёт первичного ключа)

1. Сгенерировать новый ключ, положить рядом как `OCTOPUS_API_KEY_NEW` (двойной приём не поддерживается — окно ротации = рестарт).
2. Заменить `OCTOPUS_API_KEY`, `systemctl restart octopus-browser`, проверить защищённый `/metrics` новым ключом (200) и старым (401).
3. Разослать новый ключ потребителям (AIOS), удалить старый из всех хранилищ.

## Откат релиза

- Артефакт отката = git-тег (бинарных ассетов у релизов нет): `git archive vX.Y.Z` ставится в чистое окружение и smoke-проверяется (drill v0.3.2: import/jobs/vault/version OK).
- Откат прода — ТОЛЬКО revert-PR через штатный deploy (`main` → watchdog применит). Никогда `git checkout <old>` на проде: watchdog увидит расхождение и вступит в борьбу.
- После отката: `/health` + `/ready` 200, `APPLIED==HEAD`, smoke защищённых роутов (503/401/200 по наличию ключа).

## Sandbox-хаос (рецепт drill-я)

```bash
DATA_DIR=/tmp/chaos-data APP_PORT=18095 OCTOPUS_API_KEY=<throwaway> PYTHONPATH=src \
  .venv/bin/python -m octopus_browser.main &
# мутации (профиль/лиз/прокси/задача) -> kill -9 -> рестарт -> сверить лиз/задачи/события/метрики
```
