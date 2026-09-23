# API contract v0.1

Base URL: `http://localhost:8000`. Ответы — JSON. Все деньги в целых KZT, все показатели сети — синтетические.

| Метод | Путь | Для чего |
|---|---|---|
| GET | `/health` | Проверка сервера |
| GET | `/towers` | Маркеры и показатели вышек |
| GET | `/incidents` | Список инцидентов |
| GET | `/incidents/{incident_id}` | Карточка инцидента |
| POST | `/analyze` | Анализ и журнал действий агента |
| POST | `/simulate` | Варианты под бюджет |
| POST | `/action` | Создание work order после выбора человека |
| GET | `/work-orders/{work_order_id}` | Прочитать сохранённый work order |

## POST /analyze

Запрос: `{"area":"Astana District X","time_window_minutes":60,"complaint_text":"жалобы на медленный интернет"}`. Все поля необязательны.

Ответ:

```json
{
  "incident": {"id":"INC-1042","status":"investigating","priority":"critical","complaints_count":347,"affected_users":1823,"tower_id":17,"probable_cause":"network_congestion","assigned_team":"Network Team A","reason":"Нагрузка вышки совпадает со всплеском жалоб."},
  "recurring": true,
  "solution_options": [],
  "agent_steps": [{"status":"completed","message":"Проверены жалобы."}],
  "agent_mode": "openai",
  "data_source": "synthetic"
}
```

`agent_steps` содержит только фактически выполненные вызовы Python-инструментов с полями `tool`, `arguments`, `status`, `message`. `agent_mode` равен `openai`, `demo` или `demo_fallback`. При отсутствии жалоб анализ может опираться на явно синтетические записи инцидентов; журнал при этом показывает фактическое число прочитанных жалоб. Числа в примере иллюстрируют сценарий и должны поступать из данных или расчётов.

## POST /simulate

Запрос: `{"tower_id":17,"budget_kzt":20000000}`.

Ответ: `{"tower_id":17,"budget_kzt":20000000,"options":[...],"data_source":"synthetic_simulation"}`. Каждый вариант содержит `solution_type`, `name`, `cost_kzt`, `available`, `capacity_increase_pct`, `coverage_increase_pct`, `installation_days`, `expected_load_pct`, `affected_users_improved`.

Формулы MVP: `expected_load_pct = round(current_load_pct / (1 + capacity_increase_pct / 100))`. Это предполагает неизменный трафик и пропорциональное увеличение ёмкости. `affected_users_improved` — оценка, а не число уникальных абонентов: `round(affected_users * min(1, (current_load_pct - expected_load_pct_unrounded) / 100 + coverage_increase_pct / 100))`. Предполагается, что облегчение нагрузки и прирост покрытия помогают непересекающимся долям затронутой аудитории; сумма ограничена числом `affected_users` вышки. Набор синтетических данных не моделирует реальную топологию или поведение абонентов.

Для текущих демонстрационных кластеров жалобы дополнительно содержат `demo_age_minutes`: это относительный возраст синтетической записи, чтобы сценарий оставался повторяемым после первого часа. Фактический `timestamp` сохраняет время генерации набора. Обычные записи без `demo_age_minutes` фильтруются по `timestamp`.

## POST /action

Запрос: `{"incident_id":"INC-1042","tower_id":17,"solution_type":"upgrade_existing","budget_kzt":20000000}`.

Ответ: `{"work_order":{"id":"WO-...","team":"Network Team A","task":"Upgrade Tower #17","budget_kzt":12000000,"priority":"critical","status":"pending"},"agent_steps":[...]}`. Заказ сохраняется в локальной SQLite; `GET /work-orders/{id}` возвращает его после перезапуска backend.

Сервер проверяет, что инцидент связан с вышкой, вариант существует и укладывается в бюджет. Ошибки входных данных: HTTP 4xx, тело `{"detail":"..."}`.
