# Network Intelligence Agent

MVP для HackAlem: синтетические жалобы → инцидент → диагностика вышки → варианты улучшения → work order. Данные и прогнозы демонстрационные.

## Начать новую сессию

Сначала прочитайте [`AGENTS.md`](AGENTS.md), затем [`STATUS.md`](STATUS.md), этот README, [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) и свой файл участника: [Рамазан](docs/README_1_RAMAZAN.md) · [Абыл](docs/README_2_ABYL.md) · [Манс](docs/README_3_MANS.md). `STATUS.md` содержит актуальное состояние и следующий шаг; README — общую картину проекта.

## Команда

| Участник | Зона ответственности | Папки |
|---|---|---|
| Участник 1 | FastAPI, агент и вызовы инструментов, инциденты и заказы | `backend/app/` |
| Абыл | Синтетические данные и расчёты | `backend/data/`, `backend/app/services/` |
| Манс | Один dashboard и подключение к API | `frontend/` |

## Первые стыки

1. **Схема данных:** `tower_id` — число, `incident_id` — строка, `solution_type` — одно из `upgrade_existing`, `additional_equipment`, `new_tower`. Деньги — целое число KZT; нагрузка и прирост — проценты.
2. **Расчёты:** Абыл предоставляет чистые Python-функции. Backend вызывает их напрямую. AI и frontend не придумывают метрики.
3. **API:** Манс подключается к контракту в [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md). При изменении поля обновляется контракт и сообщается команде.
4. **Действие:** `POST /action` получает явный выбор человека, проверяет бюджет и создаёт локальный work order.

## Быстрый запуск

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API: http://localhost:8000; документация: http://localhost:8000/docs. Пока backend содержит минимальные синтетические fixtures; Абыл заменяет их на 3–5 тысяч жалоб и 30–50 вышек. `POST /analyze` вызывает инструменты через OpenAI Responses API, если заданы `OPENAI_API_KEY` и `OPENAI_MODEL`. Без них работает явно помеченный demo-режим с теми же Python-инструментами. Work orders и изменения инцидентов сохраняются в локальный `backend/data/state.sqlite3` (файл игнорируется Git).

Скопируйте `backend/.env.example` в `backend/.env` и внесите ключ и ID модели только локально. Не добавляйте ключи, ссылки на биллинг и токены в репозиторий или frontend. Работу с реальным OpenAI API нужно проверить с ключом в окружении команды; без него можно проверить demo-режим.
