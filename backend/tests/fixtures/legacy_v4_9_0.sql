PRAGMA foreign_keys = OFF;

-- Migration ledger of a supported 4.9-era install: the pre-4.9 ledger
-- expansion (001-006) is recorded as applied. 007 (data backfill) and the
-- accumulation/contract migrations (008-021) still run at resume.

CREATE TABLE schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version VARCHAR(100) NOT NULL UNIQUE,
    phase VARCHAR(32) NOT NULL,
    description TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    compatibility VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    error TEXT NULL,
    started_at TIMESTAMP NULL,
    applied_at TIMESTAMP NULL
);

INSERT INTO schema_migrations (
    version, phase, description, checksum, compatibility, status,
    started_at, applied_at
) VALUES
    ('2026-07-28-001-open-trades-expand', 'schema',
     'Add backward-compatible open-trade runtime columns.',
     'f967c880a9d7c8cc4b58730c4510aab3a22989cd498188e6c38f602bff0f0d0c',
     'expand-only:9a56ed9', 'applied',
     '2026-08-20 12:00:00+00:00', '2026-08-20 12:00:00+00:00'),
    ('2026-07-28-003-trade-ledger-expand', 'schema',
     'Add deal and campaign execution-ledger identity.',
     '04f988993c8fd42e6ef31104c209a46c5568ade6fb1f5f638bf65f4bff0f933b',
     'expand-only:9a56ed9', 'applied',
     '2026-08-20 12:00:00+00:00', '2026-08-20 12:00:00+00:00'),
    ('2026-07-28-004-upnl-expand', 'schema',
     'Add persisted locked-funds history.',
     '50efc5f140f7c4102d83c8b20731ad307d980f43f5bf3f41c71630f2f0da225a',
     'expand-only:9a56ed9', 'applied',
     '2026-08-20 12:00:00+00:00', '2026-08-20 12:00:00+00:00'),
    ('2026-07-28-005-ai-trust-expand', 'schema',
     'Add stable AI evaluation identity.',
     '712e3f4a095e08eab6d7ad9cefbba252226b429566624ce87796be2eda42338a',
     'expand-only:9a56ed9', 'applied',
     '2026-08-20 12:00:00+00:00', '2026-08-20 12:00:00+00:00'),
    ('2026-07-28-006-indexes', 'schema',
     'Create current additive and unique indexes.',
     '096fd07b7f1e7808729c89b8df0ab6ad7d8368f01480d85dca321ab04fb98566',
     'expand-only:9a56ed9', 'applied',
     '2026-08-20 12:00:00+00:00', '2026-08-20 12:00:00+00:00');

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
    side TEXT NOT NULL,
    deal_id TEXT NULL,
    campaign_id TEXT NULL
);

CREATE INDEX idx_trades_symbol ON trades (symbol);
CREATE INDEX idx_trades_deal_id_timestamp ON trades (deal_id, timestamp);
CREATE INDEX idx_trades_campaign_id_timestamp ON trades (campaign_id, timestamp);
CREATE INDEX idx_trades_symbol_baseorder ON trades (symbol, baseorder);

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
    open_date TEXT NULL,
    sold_amount REAL NOT NULL DEFAULT 0.0,
    sold_proceeds REAL NOT NULL DEFAULT 0.0,
    unsellable_amount REAL NOT NULL DEFAULT 0.0,
    unsellable_reason TEXT NULL,
    unsellable_min_notional REAL NULL,
    unsellable_estimated_notional REAL NULL,
    unsellable_since TEXT NULL,
    unsellable_notice_sent INTEGER NOT NULL DEFAULT 0,
    tp_limit_order_id TEXT NULL,
    tp_limit_order_price REAL NULL,
    tp_limit_order_amount REAL NULL,
    tp_limit_order_armed_at TEXT NULL,
    dca_sizing_mode TEXT NOT NULL DEFAULT 'legacy_factors',
    dca_policy_json TEXT NULL,
    dca_reference_price REAL NOT NULL DEFAULT 0.0,
    dca_reference_atr_percent REAL NOT NULL DEFAULT 0.0,
    dca_next_trigger_price REAL NOT NULL DEFAULT 0.0,
    dca_last_decision_json TEXT NULL,
    automation_paused INTEGER NOT NULL DEFAULT 0,
    automation_paused_at TEXT NULL,
    deal_id TEXT NULL,
    campaign_id TEXT NULL,
    execution_history_complete INTEGER NOT NULL DEFAULT 1,
    lifecycle_mode TEXT NOT NULL DEFAULT 'classic_dca',
    exposure_state TEXT NOT NULL DEFAULT 'long_exposed',
    reserved_reentry_quote REAL NOT NULL DEFAULT 0.0,
    waiting_reference_price REAL NOT NULL DEFAULT 0.0,
    waiting_reference_amount REAL NOT NULL DEFAULT 0.0,
    waiting_reference_quote REAL NOT NULL DEFAULT 0.0,
    virtual_waiting_profit REAL NOT NULL DEFAULT 0.0,
    virtual_waiting_profit_percent REAL NOT NULL DEFAULT 0.0,
    last_transition_at TEXT NULL
);

CREATE INDEX idx_opentrades_exposure_state_symbol ON opentrades (exposure_state, symbol);

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
    duration TEXT NULL,
    deal_id TEXT NULL,
    campaign_id TEXT NULL,
    close_reason TEXT NULL,
    execution_history_complete INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_closedtrades_close_date ON closedtrades (close_date);
CREATE INDEX idx_closedtrades_campaign_id_close_date ON closedtrades (campaign_id, close_date);
CREATE INDEX idx_closedtrades_close_reason ON closedtrades (close_reason);

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
    unsellable_since TEXT NULL,
    accumulation_inventory_json TEXT NULL,
    deal_id TEXT NULL,
    execution_history_complete INTEGER NOT NULL DEFAULT 0
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
    metadata_json TEXT NULL,
    campaign_id TEXT NULL
);

CREATE INDEX idx_tradeexecutions_deal_time ON tradeexecutions (deal_id, timestamp);
CREATE INDEX idx_tradeexecutions_campaign_time ON tradeexecutions (campaign_id, timestamp);
CREATE INDEX idx_tradeexecutions_symbol_time ON tradeexecutions (symbol, timestamp);

CREATE TABLE placement_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id VARCHAR(64) NOT NULL,
    source_operation_id VARCHAR(64) NULL,
    client_order_id VARCHAR(128) NULL,
    exchange_order_id VARCHAR(128) NULL,
    exchange_name VARCHAR(64) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    action VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL,
    deal_id VARCHAR(36) NULL,
    campaign_id VARCHAR(36) NULL,
    requested_quote REAL NOT NULL DEFAULT 0.0,
    requested_amount REAL NOT NULL DEFAULT 0.0,
    maximum_price REAL NULL,
    reserved_quote REAL NOT NULL DEFAULT 0.0,
    request_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NULL,
    reason_code VARCHAR(64) NULL,
    error_message TEXT NULL,
    reconciliation_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    submitted_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL
);

CREATE INDEX idx_placement_intents_state_symbol ON placement_intents (state, symbol);
CREATE INDEX idx_placement_intents_exchange_order_id ON placement_intents (exchange_order_id);
CREATE INDEX idx_placement_intents_deal_id ON placement_intents (deal_id);
CREATE UNIQUE INDEX uidx_placement_intents_operation_id ON placement_intents (operation_id);
CREATE UNIQUE INDEX uidx_placement_intents_client_order_id ON placement_intents (client_order_id);

-- Sidestep-era orphan: the campaign table no longer has a model, and its
-- rows are intentionally left untouched by the contract migration.
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
    profit_overall REAL NOT NULL DEFAULT 0.0,
    funds_locked REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX idx_upnl_history_timestamp ON upnl_history (timestamp);

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
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    evaluation_id TEXT NULL
);

CREATE UNIQUE INDEX uid_ai_trust_evaluation_id ON ai_trust_predictions (evaluation_id);

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
    tp_price, avg_price, open_date,
    deal_id, campaign_id, execution_history_complete, lifecycle_mode,
    exposure_state, reserved_reentry_quote, waiting_reference_price,
    waiting_reference_amount, waiting_reference_quote, virtual_waiting_profit,
    virtual_waiting_profit_percent, last_transition_at
) VALUES (
    'BTC/USDC', 0, 5.0, 5.0, 1.0, 100.0, 105.0,
    103.0, 100.0, '2024-05-03 09:00:00+00:00',
    'legacy-deal-btc-usdc', NULL, 1, 'classic_dca',
    'long_exposed', 0.0, 0.0,
    0.0, 0.0, 0.0,
    0.0, NULL
);

INSERT INTO closedtrades (
    symbol, so_count, profit, profit_percent, amount, cost, tp_price,
    avg_price, open_date, close_date, duration,
    deal_id, campaign_id, close_reason, execution_history_complete
) VALUES (
    'ETH/USDC', 1, 4.0, 4.0, 2.0, 100.0, 52.0,
    50.0, '2024-05-01 09:00:00+00:00',
    '2024-05-02 09:00:00+00:00',
    '{"days":1,"hours":0,"minutes":0,"seconds":0}',
    'legacy-deal-eth-usdc', 'campaign-eth-usdc-2024', 'take_profit', 1
);

INSERT INTO spotcampaigns (
    campaign_id, symbol, state, started_at, last_transition_at,
    current_deal_id, sidestep_count, last_exit_reason, cooldown_until,
    tp_percent, metadata_json
) VALUES (
    'campaign-eth-usdc-2024', 'ETH/USDC', 'exited', '2024-04-25 09:00:00+00:00',
    '2024-05-02 09:00:00+00:00', 'legacy-deal-eth-usdc', 2, 'take_profit',
    NULL, 5.0, NULL
);

INSERT INTO placement_intents (
    operation_id, client_order_id, exchange_name, symbol, action, side,
    order_type, state, deal_id, campaign_id, requested_quote, requested_amount,
    request_json, created_at, updated_at
) VALUES (
    'op-legacy-1', 'cli-legacy-1', 'binance', 'BTC/USDC', 'open', 'buy',
    'limit', 'submitted', 'legacy-deal-btc-usdc', 'campaign-eth-usdc-2024',
    100.0, 1.0, '{}', '2024-05-03 09:00:00+00:00', '2024-05-03 09:00:00+00:00'
);

INSERT INTO upnl_history (timestamp, upnl, profit_overall, funds_locked)
VALUES ('2024-05-03 09:00:00+00:00', 5.0, 14.0, 6.0);

INSERT INTO ai_trust_predictions (
    symbol, source_event, provider, status, provider_status, evaluation_id
) VALUES (
    'BTC/USDC', 'entry_observation', 'ollama', 'unscored', 'unscored',
    'eval-legacy-1'
);
