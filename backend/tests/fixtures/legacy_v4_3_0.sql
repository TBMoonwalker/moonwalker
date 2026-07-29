PRAGMA foreign_keys = OFF;

CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ordersize REAL NOT NULL,
    fee REAL NOT NULL,
    precision INTEGER NULL,
    amount REAL NOT NULL,
    amount_fee REAL NOT NULL,
    price REAL NOT NULL,
    symbol TEXT NOT NULL,
    orderid TEXT NOT NULL,
    bot TEXT NOT NULL,
    ordertype TEXT NOT NULL,
    baseorder INTEGER NULL,
    safetyorder INTEGER NULL,
    order_count INTEGER NULL,
    so_percentage NUMERIC NULL,
    direction TEXT NOT NULL,
    side TEXT NOT NULL
);

CREATE TABLE opentrades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(50) NOT NULL UNIQUE,
    so_count INTEGER NOT NULL DEFAULT 0,
    profit REAL NOT NULL DEFAULT 0.0,
    profit_percent REAL NOT NULL DEFAULT 0.0,
    amount REAL NOT NULL DEFAULT 0.0,
    cost REAL NOT NULL DEFAULT 0.0,
    current_price REAL NOT NULL DEFAULT 0.0,
    tp_price REAL NOT NULL DEFAULT 0.0,
    avg_price REAL NOT NULL DEFAULT 0.0,
    open_date TEXT NULL
);

CREATE TABLE closedtrades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(50) NOT NULL,
    so_count INTEGER NULL,
    profit REAL NULL,
    profit_percent REAL NULL,
    amount REAL NULL,
    cost REAL NULL,
    tp_price REAL NULL,
    avg_price REAL NULL,
    open_date TEXT NULL,
    close_date TEXT NULL,
    duration TEXT NULL
);

CREATE TABLE unsellabletrades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(50) NOT NULL,
    so_count INTEGER NOT NULL DEFAULT 0,
    profit REAL NOT NULL DEFAULT 0.0,
    profit_percent REAL NOT NULL DEFAULT 0.0,
    amount REAL NOT NULL DEFAULT 0.0,
    cost REAL NOT NULL DEFAULT 0.0,
    current_price REAL NOT NULL DEFAULT 0.0,
    avg_price REAL NOT NULL DEFAULT 0.0,
    open_date TEXT NULL,
    unsellable_reason TEXT NULL,
    unsellable_min_notional REAL NULL,
    unsellable_estimated_notional REAL NULL,
    unsellable_since TEXT NULL
);

CREATE TABLE tradeexecutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id VARCHAR(36) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(8) NOT NULL,
    role VARCHAR(32) NOT NULL,
    timestamp TEXT NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    ordersize REAL NOT NULL DEFAULT 0.0,
    fee REAL NOT NULL DEFAULT 0.0,
    order_id TEXT NULL,
    order_type TEXT NULL,
    order_count INTEGER NULL,
    so_percentage REAL NULL,
    signal_name TEXT NULL,
    strategy_name TEXT NULL,
    timeframe TEXT NULL,
    metadata_json TEXT NULL
);

CREATE TABLE spotcampaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id VARCHAR(36) NOT NULL UNIQUE,
    symbol VARCHAR(50) NOT NULL,
    state VARCHAR(32) NOT NULL,
    started_at TEXT NOT NULL,
    last_transition_at TEXT NOT NULL,
    current_deal_id VARCHAR(36) NULL,
    sidestep_count INTEGER NOT NULL DEFAULT 0,
    last_exit_reason TEXT NULL,
    cooldown_until TEXT NULL,
    tp_percent REAL NOT NULL DEFAULT 0.0,
    metadata_json TEXT NULL
);

CREATE TABLE upnl_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP NOT NULL,
    upnl REAL NOT NULL DEFAULT 0.0,
    profit_overall REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE ai_trust_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol VARCHAR(50) NOT NULL,
    deal_id VARCHAR(36) NULL,
    trade_id INTEGER NULL,
    event_timestamp TEXT NULL,
    source_event VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'ollama',
    model_name VARCHAR(128) NULL,
    prompt_version VARCHAR(32) NOT NULL DEFAULT 'ai_trust_v1',
    schema_version VARCHAR(32) NOT NULL DEFAULT '1',
    status VARCHAR(32) NOT NULL DEFAULT 'unscored',
    provider_status VARCHAR(64) NOT NULL DEFAULT 'unscored',
    risk_score INTEGER NULL,
    confidence REAL NULL,
    would_warn INTEGER NULL,
    warning_severity VARCHAR(16) NOT NULL DEFAULT 'none',
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    operator_note TEXT NULL,
    feature_bundle_json TEXT NOT NULL DEFAULT '{}',
    outcome_status VARCHAR(32) NOT NULL DEFAULT 'open',
    bad_entry INTEGER NULL,
    bad_entry_reasons_json TEXT NOT NULL DEFAULT '[]',
    outcome_profit REAL NULL,
    outcome_profit_percent REAL NULL,
    outcome_duration_hours REAL NULL,
    outcome_so_count INTEGER NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO trades (
    timestamp, ordersize, fee, precision, amount, amount_fee, price, symbol,
    orderid, bot, ordertype, baseorder, safetyorder, order_count,
    so_percentage, direction, side
) VALUES (
    '1714726800000', 100.0, 0.1, 8, 1.0, 0.0, 100.0, 'BTC/USDC',
    'legacy-buy-1', 'legacy_asap', 'market', 1, 0, 0,
    NULL, 'long', 'buy'
);

INSERT INTO opentrades (
    symbol, so_count, profit, profit_percent, amount, cost, current_price,
    tp_price, avg_price, open_date
) VALUES (
    'BTC/USDC', 0, 5.0, 5.0, 1.0, 100.0, 105.0,
    103.0, 100.0, '2024-05-03 09:00:00+00:00'
);

INSERT INTO closedtrades (
    symbol, so_count, profit, profit_percent, amount, cost, tp_price,
    avg_price, open_date, close_date, duration
) VALUES (
    'ETH/USDC', 1, 4.0, 4.0, 2.0, 100.0, 52.0,
    50.0, '2024-05-01 09:00:00+00:00',
    '2024-05-02 09:00:00+00:00',
    '{"days":1,"hours":0,"minutes":0,"seconds":0}'
);

INSERT INTO upnl_history (timestamp, upnl, profit_overall)
VALUES ('2024-05-03 09:00:00+00:00', 5.0, 14.0);

INSERT INTO ai_trust_predictions (
    symbol, source_event, provider, status, provider_status
) VALUES (
    'BTC/USDC', 'entry_observation', 'ollama', 'unscored', 'unscored'
);
