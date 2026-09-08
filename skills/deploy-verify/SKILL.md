---
name: deploy-verify
description: Постдеплойная проверка Octopus Browser через /health и /ready, exit-код для CI и вотчдога.
---

# Skill: Deploy Verify

Проверяет, что обновлённый Octopus Browser отвечает и здоров.

## Контракт

- Вход: `--base-url` (по умолчанию `http://127.0.0.1:8095`).
- Выход: exit 0 — все проверки зелёные; exit 1 — проблема.
- Зависимости: только стандартная библиотека Python.

## Алгоритм

1. `GET /health` → HTTP 200 и `status == ok`.
2. `GET /ready` → HTTP 200.
3. Построчная печать результата, exit-код по итогу.

## Запуск

```bash
python3 skills/deploy-verify/code/verify_deploy.py --base-url http://127.0.0.1:8095
```

## Тесты

```bash
pytest skills/deploy-verify/tests -q
```
