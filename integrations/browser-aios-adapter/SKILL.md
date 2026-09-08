---
name: octopus-browser-aios-adapter
version: 0.1.0
description: CDP-подключение к пользовательским профилям без копирования cookies и bounded vision/action loop для AIOS.
triggers: [browser_task, visual_testing, aios_browser]
dependencies: [playwright, httpx]
---

# Skill: Octopus Browser AIOS Adapter

## Границы

- Подключает только уже запущенный Chrome через CDP.
- Не экспортирует и не копирует `Cookies`, `Local State`, `user-data-dir` или storage state.
- `navigate`, `click`, `fill` требуют `approved=true`.
- Передача изображения внешнему vision API отключена по умолчанию и включается отдельной настройкой.
- LLM balancer подключается только как OpenAI-compatible vision backend и не снимает внешний privacy gate.
- Live Google/финансовые/деструктивные операции не выполняются автоматически.

## Проверки

```bash
pytest -q
curl http://127.0.0.1:9615/health
curl http://127.0.0.1:9615/status
```

## Runtime

Пакет находится в `integrations/browser-aios-adapter/` и предоставляет `AIOSBrowserAdapter`. Сервисный пример находится в `systemd/`. Секреты берутся только из защищённого окружения.
