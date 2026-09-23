# Контракт модулей v1 — Beeline Tariff Campaigns

## Вход и результат

`Agent.act(env) -> list[dict]`. Метод пользуется только публичными `env.customer_profile`, `env.tariffs`, `env.channels`, `env.remaining_budget`, `env.remaining_contacts`, `env.pilots_left`, `env.pilot_history`, `env.run_pilot`.

Кампания: `campaign_name`, обязательные `target_tariff` (из `env.tariffs.tariff_plan_code`) и `channel` (`push`, `sms`, `digital_ads`, `call`). Необязательные фильтры: `filter_current_tariff` (один тариф либо несколько через `;`), `filter_arpu_segment` (`LOW/MID/HIGH`), `filter_data_segment` (`NON_USER/LITE/HEAVY`), `filter_call_segment` (`LOW/MEDIUM/HIGH`). Отсутствующий фильтр не ограничивает сегмент. Иные поля и explicit_ids в финальных кампаниях не использовать.

## Ноутбук 2 → ноутбук 1

```python
from research.candidates import build_candidates
candidates = build_candidates(profile, tariffs, history_path=None)
```

Чистая детерминированная функция: не изменяет входы, не вызывает пилоты, сеть или LLM. По умолчанию читает выданную `data/change_tariff.csv`. Возвращает упорядоченный список словарей, лучший кандидат первым:

```json
{"filter_current_tariff":"tariff_4","filter_arpu_segment":"MID","target_tariff":"tariff_8","prior_lift_ratio":0.12,"history_support":40,"priority":125000.0}
```

Числа здесь — пример структуры. `prior_lift_ratio` — историческое относительное изменение среди сменивших тариф, доля (0.12 = 12%), не измеренный эффект кампании с конверсией. `history_support` — число исторических записей. `priority` — сравнительная оценка для отбора пилотов, не прибыль. Разрешены дополнительные стандартные фильтры. Канал выбирает ноутбук 1. В baseline каждый кандидат охватывает 10–5000 абонентов. Сохранять разнообразие сегментов; после изменений контракт и тесты должны совпадать.

## Пилоты и планирование

`env.run_pilot(target_tariff, channel, n_customers, **filters)` возвращает `observed_lift_ratio`, `observed_lift_total`, `n_customers`, `cost`, остатки лимитов. `observed_lift_ratio` уже содержит эффект выбранного канала и шум. Не умножать его повторно на конверсию того же канала. Точный перенос на другой канал нельзя предполагать без учёта ограничения вероятности конверсии единицей.

Внутри planner можно использовать `select_segment(profile, campaign)` для разрешённых фильтров. Бюджет и охват env списываются пилотами. Финальные кампании ещё не списаны: planner резервирует их самостоятельно. Повторные контакты учитываются в охвате и затратах, даже если прибыль дедуплицируется. Порядок кампаний важен при ограничениях. Нельзя ориентироваться на число строк общих деталей скоринга как на число финальных кампаний: там присутствуют пилоты.

## Ноутбук 1 → ноутбук 3

`python tools/report.py --seed 42 --output artifacts/report.json` запускает официальный локальный оценщик и сохраняет JSON:

- `schema_version`: 1;
- `mode`: `mock`, `seed`: integer;
- `metrics`: результат официального local_eval (net_arpu_gain, total_cost, total_contacts и прочие поля);
- `final_campaigns`: фактически возвращённый Agent список;
- `pilot_history`: публичные наблюдения пилотов.

NaN/Infinity заменяются на null для валидного JSON (например, ROI при бесплатных контактах). Отчёт разрешено использовать для демонстрации, нельзя передавать истинные mock-метрики обратно агенту. Демонстрация должна отличать наблюдаемый пилотный эффект от локального оценённого результата. Старого HTTP API больше нет. Если нужен UI, сначала достаточно чтения этого JSON.
