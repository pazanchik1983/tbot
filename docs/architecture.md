# Архитектура T-Bot

```
┌────────────────────────────────────────────────────────────────────┐
│                              UI (PyQt6)                            │
│  MainWindow  ChartWidget  SettingsDialog   (только подписан на bus)│
└──────────────────────────────▲─────────────────────────────────────┘
                               │ events (Qt signals)
                               │
┌──────────────────────────────┴─────────────────────────────────────┐
│                          Event Bus (pub/sub)                       │
│  topics: market.candle  agent.signal  order.new  trade.executed …  │
└──────▲──────────────────────▲──────────────────────────▲───────────┘
       │                      │                          │
       │ publish candles      │ publish signal/order     │ publish trade
┌──────┴──────────┐  ┌────────┴────────┐         ┌───────┴───────────┐
│ Broker Adapter  │  │ AgentRuntime    │  uses   │ Storage (SQLite)  │
│   - tinkoff     │◄─┤  - features     │────────►│  trades, candles  │
│   - stub        │  │  - base_strategy│         └───────────────────┘
│   - finam/bcs   │  │  - ml_filter ★  │
└─────────────────┘  └─────────────────┘
                              │ retrain on closed trades
                              ▼
                     ┌────────────────────┐
                     │  ML model (.pkl)   │  %APPDATA%/TBot/models/
                     └────────────────────┘
```

★ Самообучение: каждая закрытая сделка превращается в обучающий пример
(`features + side → profitable y/n`). Через каждые `auto_retrain_every_n_trades`
сделок LightGBM-классификатор переобучается.

## Принципы

1. **Ядро не знает про UI.** Любой выход — через `event_bus`. Это позволяет
   подменить UI на REST/WS-мост (`tbot/api/server.py`) для Android-клиента.
2. **Брокеры — за интерфейсом.** Меняются прямо в Настройках, токены —
   в системном keyring (Windows Credential Manager).
3. **Sandbox по умолчанию.** Боевой режим включается осознанно с
   подтверждением.
4. **Риск-менеджер — единая точка контроля.** Все ордера (агент + ручные)
   обязаны пройти через `RiskManager.check_order(...)`.
5. **Хранение данных** в `%APPDATA%/TBot/` — отдельно от установочной папки,
   поэтому обновление .exe не сносит модели и историю сделок.

## Расширения

- Добавить нового брокера → реализовать `BrokerBase` и зарегистрировать в `factory.py`.
- Заменить стратегию → подменить `base_strategy.indicator_signal()` (тот же контракт).
- Сменить ML-модель → подменить `ml_filter.MLFilter` (тот же API: `predict_proba/add_sample/retrain`).
