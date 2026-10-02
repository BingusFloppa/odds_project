CREATE TABLE IF NOT EXISTS leagues (
    id BIGSERIAL PRIMARY KEY,
    league_key VARCHAR(150) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    sport VARCHAR(50) NOT NULL DEFAULT 'soccer',
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bookmakers (
    id BIGSERIAL PRIMARY KEY,
    bookmaker_key VARCHAR(150) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    calc_odds BOOLEAN NOT NULL DEFAULT FALSE,
    for_bets BOOLEAN NOT NULL DEFAULT FALSE,
    build_clusters BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS odds_data (
    id BIGSERIAL PRIMARY KEY,
    period TIMESTAMP NOT NULL,
    league VARCHAR(200),
    match VARCHAR(200),
    bookmaker VARCHAR(200),
    market_type VARCHAR(50),
    odds_1 NUMERIC(10, 3),
    odds_x NUMERIC(10, 3),
    odds_2 NUMERIC(10, 3),
    margin NUMERIC(10, 6),
    t_line NUMERIC(5, 2),
    odds_over NUMERIC(10, 3),
    odds_under NUMERIC(10, 3),
    h_line NUMERIC(10, 2),
    odds_h1 NUMERIC(10, 3),
    odds_h2 NUMERIC(10, 3),
    league_key VARCHAR(150),
    commence_time TIMESTAMP,
    match_result VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS biv_cache (
    hash_key VARCHAR(255) PRIMARY KEY,
    l1 NUMERIC(10, 3),
    l2 NUMERIC(10, 3),
    rho NUMERIC(10, 3),
    error NUMERIC(10, 6)
);

CREATE TABLE IF NOT EXISTS bets (
    id BIGSERIAL PRIMARY KEY,
    commence_time TIMESTAMP,
    league VARCHAR(200),
    match VARCHAR(200),
    bookmaker VARCHAR(200),
    market VARCHAR(50),
    market_size VARCHAR(20),
    odds NUMERIC(10, 3),
    true_odds NUMERIC(10, 3),
    diff NUMERIC(10, 3),
    match_result VARCHAR(50),
    profit NUMERIC(10, 3),
    UNIQUE (match, bookmaker, market, market_size)
);

-- Reference links added for the database-backed leagues/bookmakers migration.
ALTER TABLE odds_data ADD COLUMN IF NOT EXISTS league_id BIGINT;
ALTER TABLE odds_data ADD COLUMN IF NOT EXISTS bookmaker_id BIGINT;
ALTER TABLE odds_data ADD COLUMN IF NOT EXISTS bookmaker_key VARCHAR(150);

ALTER TABLE bets ADD COLUMN IF NOT EXISTS league_id BIGINT;
ALTER TABLE bets ADD COLUMN IF NOT EXISTS bookmaker_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_odds_data_league_key ON odds_data(league_key);
CREATE INDEX IF NOT EXISTS idx_odds_data_bookmaker_key ON odds_data(bookmaker_key);
CREATE INDEX IF NOT EXISTS idx_odds_data_commence_time ON odds_data(commence_time);
CREATE INDEX IF NOT EXISTS idx_bets_commence_time ON bets(commence_time);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'odds_data_league_id_fkey'
    ) THEN
        ALTER TABLE odds_data
        ADD CONSTRAINT odds_data_league_id_fkey
        FOREIGN KEY (league_id) REFERENCES leagues(id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'odds_data_bookmaker_id_fkey'
    ) THEN
        ALTER TABLE odds_data
        ADD CONSTRAINT odds_data_bookmaker_id_fkey
        FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'bets_league_id_fkey'
    ) THEN
        ALTER TABLE bets
        ADD CONSTRAINT bets_league_id_fkey
        FOREIGN KEY (league_id) REFERENCES leagues(id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'bets_bookmaker_id_fkey'
    ) THEN
        ALTER TABLE bets
        ADD CONSTRAINT bets_bookmaker_id_fkey
        FOREIGN KEY (bookmaker_id) REFERENCES bookmakers(id);
    END IF;
END $$;
