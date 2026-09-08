# Vision benchmark — 2026-09-05

## Методика

- Сервер: `arm-server-01`, OCI ARM.
- Изображение: синтетический PNG 64×64, без данных браузера и аккаунтов.
- Один короткий prompt: `Return exactly OK.`
- Секреты и ответы моделей в отчёт не записывались.
- Замерялась полная HTTP-задержка запроса до ответа API; это не полноценный performance study.

## Наблюдения

| Провайдер/модель | Результат | Измеренная задержка |
|---|---:|---:|
| Gemini 2.5 Flash | HTTP 200 | 612.8 ms |
| Gemini 3.5 Flash Lite | HTTP 200 | 620.4 ms |
| Gemini 3.1 Flash Lite | HTTP 200 | 2001.1 ms |
| Gemini 2.5 Flash Lite | HTTP 404 | недоступна для текущего API-ключа |
| Groq Qwen 3.8 27B, inline PNG | HTTP 200 | 647.5 ms |
| Groq Qwen 3.8 27B, external URL | HTTP 200 | 358.9 ms; не сопоставимо с inline screenshot |
| Groq Qwen 3.6 27B, external URL | HTTP 200 | 506.6 ms; не сопоставимо с inline screenshot |

## Решение адаптера

- Primary для реальных Playwright/CDP screenshot: `gemini-2.5-flash`.
- Fallback: `qwen/qwen3.8-27b` через Groq.
- Причина: для browser automation кадр передаётся как inline base64; в этом режиме Gemini 2.5 Flash был немного быстрее успешного Qwen 3.8 и уже используется в AIOS vision pipeline.
- Benchmark нужно повторить после деплоя на 10–20 одинаковых кадрах; модель выбирается конфигурацией, а не зашивается в секреты.

## Ограничения

- Primary CDP `127.0.0.1:9222` на момент проверки недоступен; secondary CDP `127.0.0.1:9224` подключается и содержит одну вкладку.
- Реальные Google-скриншоты в benchmark не использовались.
- Передача реальных кадров внешнему API включается только через `OCTOPUS_BROWSER_ALLOW_EXTERNAL_VISION=1`.
