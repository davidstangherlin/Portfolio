-- PostgreSQL Schema: ASX Value Investing Database
-- Design targeted for ASX metrics (Franking credits, Dividend Yields, Debt/Equity, Intrinsic Valuation)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. COMPANIES CORE TABLE
CREATE TABLE IF NOT EXISTS companies (
    company_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticker VARCHAR(10) NOT NULL UNIQUE,          -- e.g., 'BHP.AX', 'CGF.AX'
    company_name VARCHAR(255) NOT NULL,
    sector VARCHAR(100),
    industry VARCHAR(100),
    asx_code VARCHAR(6) NOT NULL UNIQUE,         -- Pure 3-letter ASX code (e.g. 'BHP')
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    country VARCHAR(100)                         -- Domicile per Yahoo. Non-Australian companies pay no
                                                  -- franking credits (see fundamentals_ingestion.py)
);

-- Migrations for databases created before these columns existed.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS country VARCHAR(100);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS trading_currency VARCHAR(3);    -- share price currency (AUD on the ASX)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS financial_currency VARCHAR(3);  -- currency the statements are published in
-- What the company does, per Yahoo's business summary (AS_BUILT §28). NULL
-- means not fetched yet; '' means fetched and Yahoo has none.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS business_summary TEXT;
-- When the annual statements were last fetched. The nightly run refreshes
-- them weekly, a seventh of the shares each night (AS_BUILT §16).
ALTER TABLE companies ADD COLUMN IF NOT EXISTS fundamentals_fetched_at TIMESTAMP WITH TIME ZONE;
-- Why the latest statements couldn't be stored (no exchange rate for the
-- reporting currency). Set: data confidence LOW, so never a BUY (§7.7).
ALTER TABLE companies ADD COLUMN IF NOT EXISTS statements_issue VARCHAR(255);
-- SHARE, ETF (docs/AS_BUILT.md §25) or LIC (§27, listed investment companies
-- and trusts). ETFs and LICs share the price and distribution tables with
-- shares but are never valued, screened or scored as shares.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS security_type VARCHAR(5) NOT NULL DEFAULT 'SHARE';
ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_security_type_check;
ALTER TABLE companies ADD CONSTRAINT companies_security_type_check CHECK (security_type IN ('SHARE', 'ETF', 'LIC'));

-- 2. DAILY MARKET PRICE & VOLUMES
CREATE TABLE IF NOT EXISTS daily_prices (
    price_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(company_id) ON DELETE CASCADE,
    price_date DATE NOT NULL,
    close_price NUMERIC(12, 4) NOT NULL,
    volume BIGINT,
    market_cap NUMERIC(16, 2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, price_date)
);

-- 3. FINANCIAL STATEMENTS & FUNDAMENTAL METRICS (ANNUAL / HALF-YEARLY)
CREATE TABLE IF NOT EXISTS financial_reports (
    report_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(company_id) ON DELETE CASCADE,
    fiscal_year INT NOT NULL,
    period_type VARCHAR(2) CHECK (period_type IN ('FY', 'H1', 'H2')),
    report_date DATE NOT NULL,

    -- Income Statement & Cash Flow
    revenue NUMERIC(16, 2),
    ebit NUMERIC(16, 2),
    net_profit_after_tax NUMERIC(16, 2),        -- NPAT
    operating_cash_flow NUMERIC(16, 2),
    free_cash_flow NUMERIC(16, 2),
    capital_expenditure NUMERIC(16, 2),
    eps NUMERIC(10, 4),                          -- Earnings Per Share (AUD)

    -- Balance Sheet
    total_assets NUMERIC(16, 2),
    total_liabilities NUMERIC(16, 2),
    total_equity NUMERIC(16, 2),
    total_debt NUMERIC(16, 2),
    cash_and_equivalents NUMERIC(16, 2),
    net_tangible_assets NUMERIC(16, 2),          -- NTA (Crucial for ASX asset-heavy/value plays)

    -- ASX Dividend & Franking Context
    dividends_per_share NUMERIC(10, 4),          -- ordinary dividends for this financial year (abnormal one-offs excluded)
    abnormal_distributions_per_share NUMERIC(10, 4), -- one-off distributions held out of dividends_per_share
    franking_percentage NUMERIC(5, 2) DEFAULT 100.0, -- e.g., 100.00 for fully franked
    corporate_tax_rate NUMERIC(4, 2) DEFAULT 30.0,   -- Standard Australian 30% rate

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, fiscal_year, period_type)
);
ALTER TABLE financial_reports ADD COLUMN IF NOT EXISTS abnormal_distributions_per_share NUMERIC(10, 4);
-- Statement figures are stored converted into the trading currency; these record from what, and at what rate.
ALTER TABLE financial_reports ADD COLUMN IF NOT EXISTS reporting_currency VARCHAR(3);
ALTER TABLE financial_reports ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(14, 6);


-- 4. VALUATION DERIVATIVES & VALUE INVESTING METRICS
CREATE TABLE IF NOT EXISTS valuation_metrics (
    valuation_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID REFERENCES companies(company_id) ON DELETE CASCADE,
    as_of_date DATE NOT NULL,

    -- Classic Ratios
    pe_ratio NUMERIC(10, 2),
    pb_ratio NUMERIC(10, 2),
    price_to_fcf NUMERIC(10, 2),
    ev_to_ebit NUMERIC(10, 2),
    roe NUMERIC(6, 2),                          -- Return on Equity (%)
    roic NUMERIC(6, 2),                         -- Return on Invested Capital (%)
    debt_to_equity NUMERIC(10, 2),
    current_ratio NUMERIC(6, 2),

    -- Dividend & Gross Yield (ASX Specific)
    uncapped_dividend_yield NUMERIC(6, 2),
    grossed_up_dividend_yield NUMERIC(6, 2),     -- Yield including Franking Credits
    payout_ratio NUMERIC(6, 2),                  -- (dividends_per_share / EPS) * 100. A value well over 100%
                                                  -- flags a likely special/one-off dividend rather than a
                                                  -- sustainable, repeatable payout - read high yields alongside
                                                  -- this column, don't take yield alone at face value.

    -- Intrinsic Valuations & Margin of Safety
    dcf_intrinsic_value NUMERIC(12, 4),          -- Discounted Cash Flow (or Dividend Discount Model -
                                                  -- see valuation_method) intrinsic valuation per share
    graham_number NUMERIC(12, 4),                -- Sqrt(22.5 * EPS * BVPS)
    margin_of_safety_percent NUMERIC(6, 2),      -- ((Intrinsic Value - Current Price) / Intrinsic Value) * 100
    valuation_method VARCHAR(4),                 -- 'DCF' or 'DDM' - which intrinsic-value model priced
                                                  -- dcf_intrinsic_value. Financial Services and Real Estate
                                                  -- companies use a Dividend Discount Model instead of the
                                                  -- standard FCF-based DCF, since "free cash flow" isn't a
                                                  -- meaningful value driver for banks/insurers/REITs (their
                                                  -- balance-sheet movements dominate it rather than
                                                  -- reinvestment capex). NULL means neither model could be
                                                  -- computed (e.g. no usable FCF or dividend history).

    -- Trend indicators ("momentum into value" / value-trap warning)
    margin_of_safety_trend NUMERIC(6, 2),        -- change in margin_of_safety_percent vs ~trend_days days
                                                  -- ago (percentage points; see run_valuation.py
                                                  -- --trend-days, default 30). Rising = getting cheaper
                                                  -- relative to intrinsic value since that snapshot - the
                                                  -- "catch it before others" signal. NULL until a
                                                  -- valuation_metrics row at least that old exists for the
                                                  -- company, i.e. until daily automation (scripts/
                                                  -- daily_refresh.ps1) has been running that long - this is
                                                  -- an expected cold-start gap, not a bug.
    fundamentals_trend VARCHAR(10),               -- 'IMPROVING' / 'STABLE' / 'DECLINING' - ROE and revenue
                                                  -- direction across the financial_reports window used for
                                                  -- the DCF/DDM average (see fcf_average_years), independent
                                                  -- of price. A company with margin_of_safety_percent
                                                  -- passing but fundamentals_trend = 'DECLINING' is a
                                                  -- candidate value trap: cheap because the business is
                                                  -- deteriorating, not because the market has mispriced it.
                                                  -- NULL if fewer than 2 distinct FY reports are available.

    -- Decision markers (src/valuation/markers.py, docs/AS_BUILT.md §8.7)
    cash_conversion NUMERIC(10, 2),              -- operating cash flow / NPAT across the fcf_average_years
                                                  -- window, as a %. Profit that doesn't turn into cash is a
                                                  -- red flag P/E and ROE can't show. NULL for loss-makers and
                                                  -- for Financial Services/Real Estate (OCF isn't meaningful
                                                  -- there, same reason the DCF isn't).
    earnings_quality VARCHAR(10),                -- 'STRONG' (>=100%) / 'ADEQUATE' (>=80%) / 'WEAK' from cash_conversion
    price_vs_200d NUMERIC(10, 2),                -- % above (+) or below (-) the 200-trading-day average close.
                                                  -- NULL with fewer than 200 daily prices stored.
    range_position_52w NUMERIC(6, 2),            -- where today's close sits in its 52-week low-high range,
                                                  -- 0 (at the low) to 100 (at the high)
    dividend_trend VARCHAR(10),                  -- 'GROWING' / 'STEADY' / 'CUT' / 'NONE' across up to 5 FY reports
    data_confidence VARCHAR(6),                  -- 'HIGH' / 'MEDIUM' / 'LOW': share of key inputs actually present

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, as_of_date)
);

-- Safe to re-run against an existing database: adds any column this schema
-- was applied before existed (CREATE TABLE IF NOT EXISTS above won't
-- retrofit a column onto an already-created table).
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS payout_ratio NUMERIC(6, 2);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS valuation_method VARCHAR(4);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS margin_of_safety_trend NUMERIC(6, 2);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS fundamentals_trend VARCHAR(10);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS cash_conversion NUMERIC(10, 2);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS earnings_quality VARCHAR(10);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS price_vs_200d NUMERIC(10, 2);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS range_position_52w NUMERIC(6, 2);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS dividend_trend VARCHAR(10);
ALTER TABLE valuation_metrics ADD COLUMN IF NOT EXISTS data_confidence VARCHAR(6);

-- 4b. DIVIDEND PAYMENTS (per ex-dividend date, trading currency)
-- The individual payments behind financial_reports.dividends_per_share,
-- kept so the web GUI can mark them on the price chart. `abnormal` marks a
-- one-off held out of every dividend figure (dividend_history.py).
CREATE TABLE IF NOT EXISTS dividend_payments (
    company_id UUID NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    ex_date DATE NOT NULL,
    amount NUMERIC(12, 4) NOT NULL,
    abnormal BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (company_id, ex_date)
);

-- 5a. PORTFOLIOS (docs/AS_BUILT.md §19.1)
-- Each parcel belongs to one portfolio, and each portfolio has the tax type
-- of whoever owns it, which sets its CGT discount: individual or trust 50%,
-- self-managed super fund (SMSF) 33 1/3%, company none. A portfolio with
-- sales is archived rather than deleted, because the ATO expects records
-- kept for five years after each sale.
CREATE TABLE IF NOT EXISTS portfolios (
    portfolio_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(60) NOT NULL UNIQUE,
    tax_type VARCHAR(10) NOT NULL DEFAULT 'INDIVIDUAL'
        CHECK (tax_type IN ('INDIVIDUAL', 'TRUST', 'SMSF', 'COMPANY')),
    archived_at TIMESTAMP WITH TIME ZONE,          -- NULL while active
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. PERSONAL HOLDINGS (CGT record keeping - see portfolio.py, docs/AS_BUILT.md §19)
-- One row per parcel: every buy, DRP allocation or transfer-in is its own
-- parcel with its own acquisition date, because Australian CGT (including
-- the 12-month discount test) is assessed per parcel. Selling part of a
-- parcel splits it: the sold portion becomes its own row (split_from_id
-- points back to the original) and the original row keeps the units still
-- held, with brokerage apportioned by units so the cost base is preserved.
-- Keyed on asx_code rather than a companies FK so you can record any
-- holding, whether or not it's on the screening watchlist.
CREATE TABLE IF NOT EXISTS holdings (
    holding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    asx_code VARCHAR(6) NOT NULL,
    units NUMERIC(14, 4) NOT NULL CHECK (units > 0),
    acquisition_method VARCHAR(10) NOT NULL DEFAULT 'PURCHASE'
        CHECK (acquisition_method IN ('PURCHASE', 'DRP', 'BONUS', 'TRANSFER', 'OTHER')),
    buy_date DATE NOT NULL,
    buy_price NUMERIC(12, 4) NOT NULL CHECK (buy_price >= 0),  -- per share
    buy_brokerage NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (buy_brokerage >= 0),  -- part of the CGT cost base
    sell_date DATE,
    sell_price NUMERIC(12, 4) CHECK (sell_price >= 0),  -- per share
    sell_brokerage NUMERIC(10, 2) CHECK (sell_brokerage >= 0),  -- reduces capital proceeds
    broker VARCHAR(50),                           -- which broker/account holds the parcel
    notes TEXT,
    split_from_id UUID REFERENCES holdings(holding_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CHECK ((sell_date IS NULL) = (sell_price IS NULL)),
    CHECK (sell_date IS NULL OR sell_date >= buy_date)
);

-- Parcels recorded before portfolios existed move into a first portfolio,
-- "My portfolio" (individual), created only if there are parcels to move.
ALTER TABLE holdings ADD COLUMN IF NOT EXISTS portfolio_id UUID REFERENCES portfolios(portfolio_id) ON DELETE RESTRICT;
INSERT INTO portfolios (name, tax_type)
    SELECT 'My portfolio', 'INDIVIDUAL'
    WHERE NOT EXISTS (SELECT 1 FROM portfolios)
      AND EXISTS (SELECT 1 FROM holdings WHERE portfolio_id IS NULL);
UPDATE holdings SET portfolio_id = (SELECT portfolio_id FROM portfolios ORDER BY created_at, name LIMIT 1)
    WHERE portfolio_id IS NULL;
ALTER TABLE holdings ALTER COLUMN portfolio_id SET NOT NULL;

-- 5c. WATCHLISTS (docs/AS_BUILT.md §22)
-- Named lists of companies to follow without owning them, kept from the
-- web GUI. Each entry can carry a note and up to two triggers; an entry is
-- "triggered" while the company's margin of safety is above mos_above, or
-- its price is at or below price_below. Separate from the nightly ticker
-- file (allords.txt), which decides which companies are valued at all.
CREATE TABLE IF NOT EXISTS watchlists (
    watchlist_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(60) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS watchlist_items (
    watchlist_id UUID NOT NULL REFERENCES watchlists(watchlist_id) ON DELETE CASCADE,
    company_id UUID NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    note TEXT,
    mos_above NUMERIC(6, 2),                     -- trigger: margin of safety above this %
    price_below NUMERIC(12, 4) CHECK (price_below > 0),  -- trigger: price at or below this
    added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (watchlist_id, company_id)
);
-- ETFs only (§26): trigger when the trailing 12-month distribution yield is above this %.
ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS yield_above NUMERIC(6, 2);   -- ETFs and LICs (§27)
-- LICs only (§27): trigger when the price is at least this % below the last NTA.
ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS nta_discount_above NUMERIC(6, 2);

-- 5d. SCENARIOS (admin console what-ifs, docs/AS_BUILT.md §24)
-- A named set of setting changes to try against today's data. Only the
-- changed settings are stored, in the admin console's units (rates as
-- percents). Running one never writes to any other table.
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(60) NOT NULL UNIQUE,
    notes TEXT,
    overrides JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5e. ETF FACTS (docs/AS_BUILT.md §25)
-- One row per ETF per month from the ASX Investment Products report
-- (src/etf/asx_report.py): what the ASX says about the fund that month.
-- Kept for good, so fees, size and reported returns have a history.
-- Percent columns are whole-number percents (0.07 = 0.07%); money in AUD.
-- `raw` keeps every column of the report row, headed as in the report,
-- so nothing the ASX publishes is lost if a column isn't mapped.
CREATE TABLE IF NOT EXISTS etf_monthly (
    company_id UUID NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    report_month DATE NOT NULL,                  -- first day of the month the report covers
    fund_name VARCHAR(255),
    issuer VARCHAR(120),
    product_type VARCHAR(80),
    category VARCHAR(120),
    sub_category VARCHAR(120),
    benchmark VARCHAR(255),
    mer_percent NUMERIC(7, 3),
    fum_aud NUMERIC(18, 2),
    net_flows_aud NUMERIC(18, 2),
    avg_spread_percent NUMERIC(8, 3),
    value_traded_aud NUMERIC(18, 2),
    distribution_yield NUMERIC(8, 2),
    distribution_frequency VARCHAR(40),
    listing_date DATE,
    return_1m NUMERIC(10, 2),
    return_3m NUMERIC(10, 2),
    return_6m NUMERIC(10, 2),
    return_1y NUMERIC(10, 2),
    return_3y NUMERIC(10, 2),
    return_5y NUMERIC(10, 2),
    return_10y NUMERIC(10, 2),
    return_since_inception NUMERIC(10, 2),
    raw JSONB NOT NULL DEFAULT '{}',
    source_file VARCHAR(255),
    loaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, report_month)
);
-- LICs and LITs (§27) share this table: net tangible assets per share
-- before tax on unrealised gains, its date, the price's premium (+) or
-- discount (-) to it at that date, and whether there's a performance fee.
-- For LICs, fum_aud holds market capitalisation.
ALTER TABLE etf_monthly ADD COLUMN IF NOT EXISTS nta_pre_tax NUMERIC(12, 4);
ALTER TABLE etf_monthly ADD COLUMN IF NOT EXISTS nta_date DATE;
ALTER TABLE etf_monthly ADD COLUMN IF NOT EXISTS nta_premium_percent NUMERIC(8, 2);
ALTER TABLE etf_monthly ADD COLUMN IF NOT EXISTS performance_fee VARCHAR(10);

-- 5g. ASX REPORT LOADS (docs/AS_BUILT.md §25.2)
-- Which version of the report reader loaded each month. When the reader
-- learns to take more from the report (as it did for LICs), the newest
-- month is loaded again from the saved file, so nothing waits a month.
CREATE TABLE IF NOT EXISTS asx_report_loads (
    report_month DATE PRIMARY KEY,
    source_file VARCHAR(255),
    reader_version INT NOT NULL,
    etfs INT NOT NULL DEFAULT 0,
    lics INT NOT NULL DEFAULT 0,
    loaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Benchmark index returns from the ASX report's index rows (Australian
-- indices only, such as the S&P/ASX 200 Accumulation), to the report's
-- month end, compared with each fund's own report figures (§26.2).
CREATE TABLE IF NOT EXISTS asx_index_returns (
    report_month DATE NOT NULL,
    code VARCHAR(20) NOT NULL,
    name VARCHAR(120) NOT NULL,
    return_1m NUMERIC(10, 2),
    return_3m NUMERIC(10, 2),
    return_6m NUMERIC(10, 2),
    return_1y NUMERIC(10, 2),
    return_3y NUMERIC(10, 2),
    return_5y NUMERIC(10, 2),
    return_10y NUMERIC(10, 2),
    PRIMARY KEY (report_month, code)
);

-- 5i. FUND PROFILES (docs/AS_BUILT.md §26.3)
-- What each ETF or LIC holds, from Yahoo Finance's fund data (Morningstar),
-- refreshed weekly: a seventh of the funds each night. LICs get the
-- description only, since Yahoo lists them as companies. Percents as percents.
CREATE TABLE IF NOT EXISTS fund_profiles (
    company_id UUID PRIMARY KEY REFERENCES companies(company_id) ON DELETE CASCADE,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    stock_percent NUMERIC(7, 2),
    bond_percent NUMERIC(7, 2),
    cash_percent NUMERIC(7, 2),
    other_percent NUMERIC(7, 2),
    sector_weightings JSONB,                 -- {"technology": 32.1, ...} (JSONB doesn't keep order: sort when shown)
    bond_ratings JSONB,                      -- {"aaa": 40.2, ...}
    duration_years NUMERIC(8, 2),
    maturity_years NUMERIC(8, 2),
    top10_percent NUMERIC(7, 2)
);
-- A feeder fund's holdings are the fund it invests in, looked through (the
-- ASX's IVV holds the US IVV): which fund, and how much of this one it is.
ALTER TABLE fund_profiles ADD COLUMN IF NOT EXISTS look_through_symbol VARCHAR(30);
ALTER TABLE fund_profiles ADD COLUMN IF NOT EXISTS look_through_name VARCHAR(255);
ALTER TABLE fund_profiles ADD COLUMN IF NOT EXISTS look_through_percent NUMERIC(7, 2);

-- The top 10 holdings, replaced on each fetch.
CREATE TABLE IF NOT EXISTS fund_holdings (
    company_id UUID REFERENCES companies(company_id) ON DELETE CASCADE,
    rank SMALLINT NOT NULL,
    symbol VARCHAR(30),
    name VARCHAR(255) NOT NULL,
    weight_percent NUMERIC(7, 2),
    PRIMARY KEY (company_id, rank)
);

-- 5f. ETF PERFORMANCE (docs/AS_BUILT.md §25)
-- Sift's own figures from daily prices and distributions
-- (src/etf/performance.py), recalculated nightly; one row per ETF.
-- Total returns with distributions reinvested on the ex-date, in percent;
-- 3, 5 and 10 years and since first price (when over a year) annualised.
-- check_* compare Sift's 1-year return at the report's month end with
-- the ASX report's own figure.
CREATE TABLE IF NOT EXISTS etf_performance (
    company_id UUID PRIMARY KEY REFERENCES companies(company_id) ON DELETE CASCADE,
    as_of_date DATE NOT NULL,
    first_price_date DATE,
    return_1m NUMERIC(10, 2),
    return_3m NUMERIC(10, 2),
    return_6m NUMERIC(10, 2),
    return_1y NUMERIC(10, 2),
    return_3y NUMERIC(10, 2),
    return_5y NUMERIC(10, 2),
    return_10y NUMERIC(10, 2),
    return_since_inception NUMERIC(10, 2),
    distributions_12m NUMERIC(12, 4),
    distribution_yield_12m NUMERIC(8, 2),
    check_month DATE,
    check_return_1y NUMERIC(10, 2),
    reported_return_1y NUMERIC(10, 2),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- Every period checked against the ASX report at its month end, as
-- {"return_1y": [sift, asx], ...}, and the latest one-day price move too
-- big to be real (a data fault in the price history) (§26.1).
ALTER TABLE etf_performance ADD COLUMN IF NOT EXISTS report_checks JSONB;
ALTER TABLE etf_performance ADD COLUMN IF NOT EXISTS price_jump_date DATE;
ALTER TABLE etf_performance ADD COLUMN IF NOT EXISTS price_jump_percent NUMERIC(10, 2);

-- 5h. ANALYST AND HOLDER INSIGHTS (docs/AS_BUILT.md §29)
-- From Yahoo Finance, refreshed weekly (a seventh of the shares each night).
-- Shown on the company page for context; never used in valuations, scores
-- or signals. Percentages are stored as percents (12.5 = 12.5%).
CREATE TABLE IF NOT EXISTS company_insights (
    company_id UUID PRIMARY KEY REFERENCES companies(company_id) ON DELETE CASCADE,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recommendation_key VARCHAR(20),          -- Yahoo's consensus: strong_buy, buy, hold, underperform, sell
    recommendation_mean NUMERIC(4, 2),       -- 1 = strong buy ... 5 = strong sell
    analyst_count INT,                       -- analysts behind the price targets
    target_low NUMERIC(14, 4),
    target_mean NUMERIC(14, 4),
    target_median NUMERIC(14, 4),
    target_high NUMERIC(14, 4),
    insiders_percent NUMERIC(8, 4),
    institutions_percent NUMERIC(8, 4),
    institutions_float_percent NUMERIC(8, 4),
    institutions_count INT
);

-- Buy, hold and sell counts by month: Yahoo gives the latest four months,
-- and keeping each fetch's months builds a longer history over time.
CREATE TABLE IF NOT EXISTS analyst_ratings (
    company_id UUID REFERENCES companies(company_id) ON DELETE CASCADE,
    rating_month DATE NOT NULL,
    strong_buy INT NOT NULL DEFAULT 0,
    buy INT NOT NULL DEFAULT 0,
    hold INT NOT NULL DEFAULT 0,
    sell INT NOT NULL DEFAULT 0,
    strong_sell INT NOT NULL DEFAULT 0,
    PRIMARY KEY (company_id, rating_month)
);

-- Top 10 mutual fund and institutional holders, replaced on each fetch.
CREATE TABLE IF NOT EXISTS top_holders (
    company_id UUID REFERENCES companies(company_id) ON DELETE CASCADE,
    holder_kind VARCHAR(12) NOT NULL CHECK (holder_kind IN ('FUND', 'INSTITUTION')),
    rank SMALLINT NOT NULL,
    holder VARCHAR(255) NOT NULL,
    shares NUMERIC(20, 0),
    percent_held NUMERIC(8, 4),
    value NUMERIC(20, 2),                    -- as Yahoo reports it, at the report date
    percent_change NUMERIC(12, 4),           -- change in the holding since the previous report
    date_reported DATE,
    PRIMARY KEY (company_id, holder_kind, rank)
);

-- 5j. INTERFACE PREFERENCES (docs/AS_BUILT.md §20)
-- Choices made in the web pages that should follow you to any browser,
-- such as the dashboard's widget order, hidden widgets and widths. One JSON
-- value per key; validated by src/preferences.py before it's stored.
CREATE TABLE IF NOT EXISTS ui_preferences (
    pref_key VARCHAR(60) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5k. SEARCH INDEX (docs/AS_BUILT.md §32)
-- One row per searchable thing across Sift: shares, ETFs, LICs, fund
-- managers, watchlists, portfolios, help articles, pages and settings.
-- Rebuilt by src/search/indexer.py: everything nightly, personal data the
-- moment it's saved, help and pages when Sift starts, and on demand (Admin,
-- or python -m src.search.reindex). owner_id is NULL for what everyone may
-- see; personal rows carry their owner once Sift has user accounts.
-- pg_trgm adds typo tolerance; without it (no permission to add it) search
-- still works, matching whole and partial words only.
DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm not available: search works without typo tolerance';
END $$;
CREATE TABLE IF NOT EXISTS search_index (
    doc_id VARCHAR(160) PRIMARY KEY,           -- e.g. share:BHP, help:dcf, watchlist:{uuid}
    area VARCHAR(12) NOT NULL,                 -- market, coattail, personal, help, pages: the unit of a rebuild
    kind VARCHAR(12) NOT NULL,                 -- share, etf, lic, manager, watchlist, portfolio, help, page, setting
    owner_id UUID,                             -- NULL: everyone's
    code VARCHAR(20),
    title TEXT NOT NULL,
    subtitle TEXT,
    body TEXT,
    url TEXT NOT NULL,
    facets JSONB NOT NULL DEFAULT '{}',        -- sector, category, recommendation, topic, codes
    rank_boost REAL NOT NULL DEFAULT 0,
    search_vector TSVECTOR,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_search_vector ON search_index USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_search_area ON search_index (area);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS idx_search_title_trgm ON search_index USING GIN (lower(title) gin_trgm_ops);
    END IF;
END $$;
-- AI-ready (§32): content_hash fingerprints each row's text, so a rebuild
-- keeps an unchanged row's embedding and only new or changed rows are
-- embedded again. embedding is the row's meaning as numbers, filled only
-- when an embedder is switched on (src/search/embeddings.py). A plain REAL[]
-- works on any PostgreSQL; on a host with pgvector it can become vector(n).
ALTER TABLE search_index ADD COLUMN IF NOT EXISTS content_hash VARCHAR(40);
ALTER TABLE search_index ADD COLUMN IF NOT EXISTS embedding REAL[];
ALTER TABLE search_index ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(80);

-- Search learning (§32): what was searched, what was clicked and how
-- results were rated, so clicked and liked results rise for that search,
-- and Admin can show searches that found nothing. Kept for a year.
CREATE TABLE IF NOT EXISTS search_queries (
    query_id BIGSERIAL PRIMARY KEY,
    owner_id UUID,
    query TEXT NOT NULL,
    norm TEXT NOT NULL,                        -- the query's words, lower case, as matched
    results INTEGER NOT NULL,
    searched_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_search_queries_norm ON search_queries (norm, searched_at DESC);
CREATE TABLE IF NOT EXISTS search_clicks (
    query_id BIGINT NOT NULL REFERENCES search_queries(query_id) ON DELETE CASCADE,
    doc_id VARCHAR(160) NOT NULL,
    position SMALLINT,
    clicked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_search_clicks_query ON search_clicks (query_id);
CREATE TABLE IF NOT EXISTS search_feedback (
    owner_key VARCHAR(40) NOT NULL DEFAULT '',  -- owner_id as text, '' while Sift has one user
    norm TEXT NOT NULL,
    doc_id VARCHAR(160) NOT NULL,
    vote SMALLINT NOT NULL CHECK (vote IN (-1, 1)),
    voted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (owner_key, norm, doc_id)
);
-- Words that mean the same thing to a searcher (CBA, Commonwealth Bank):
-- searching any one also finds the others. Managed in Admin.
CREATE TABLE IF NOT EXISTS search_synonyms (
    synonym_id SERIAL PRIMARY KEY,
    terms TEXT[] NOT NULL,                      -- lower case, two or more
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_index_runs (
    run_id SERIAL PRIMARY KEY,
    area VARCHAR(12) NOT NULL,
    trigger VARCHAR(20) NOT NULL,              -- nightly, startup, saved, manual
    items INTEGER NOT NULL,
    seconds NUMERIC(8, 2) NOT NULL,
    finished_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5b. SIGNAL SNAPSHOTS (prediction track record - see src/tracking/signals.py, docs/AS_BUILT.md §21)
-- What Sift said about each company on each valuation date: the suggested
-- action, valuation status, estimate and scores, exactly as shown that
-- night. Written once by the nightly job and never edited (ON CONFLICT DO
-- NOTHING), so later rule changes can't rewrite history: rules_version
-- records which rules produced each row. The track record compares these
-- against what the price did next. Kept for 14 months; monthly summaries
-- are kept for good (src/tracking/outcomes.py).
CREATE TABLE IF NOT EXISTS signal_snapshots (
    company_id UUID NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    snapshot_date DATE NOT NULL,                 -- the price date the valuation used
    price NUMERIC(12, 4) NOT NULL,               -- close on snapshot_date: the starting point for outcomes
    action VARCHAR(12) NOT NULL,
    action_reason TEXT,
    held BOOLEAN NOT NULL DEFAULT FALSE,         -- held actions (SELL/REVIEW/ACCUMULATE/HOLD) differ from the rest
    valuation_status VARCHAR(12) NOT NULL,       -- Undervalued / Fair value / Overvalued / No estimate
    margin_of_safety_percent NUMERIC(6, 2),
    estimated_value NUMERIC(12, 4),
    valuation_method VARCHAR(4),
    score_total SMALLINT NOT NULL,               -- score wheel, out of 30
    score_value SMALLINT NOT NULL,
    score_performance SMALLINT NOT NULL,
    score_health SMALLINT NOT NULL,
    score_dividend SMALLINT NOT NULL,
    score_momentum SMALLINT NOT NULL,
    mos_ok BOOLEAN NOT NULL,                     -- the four value tests
    roe_ok BOOLEAN NOT NULL,
    de_ok BOOLEAN NOT NULL,
    yield_ok BOOLEAN NOT NULL,
    red_flags TEXT[] NOT NULL DEFAULT '{}',
    rules_version VARCHAR(10) NOT NULL,          -- date the screening rules last changed
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, snapshot_date)
);

-- 5b2. SIGNAL OUTCOMES AND THE MONTHLY TRACK RECORD (docs/AS_BUILT.md §21)
-- What happened after a signal, at 1, 3, 6 and 12 months: total return
-- including dividends, the average total return of every company screened
-- that same night (the benchmark), and the difference (excess return).
-- Only scorecard signals get outcomes: each company's first signal of each
-- month (is_cohort) and any night its action changed (is_change). Filled
-- by the nightly job once the market data reaches each horizon; deleted
-- with their snapshot after 14 months.
CREATE TABLE IF NOT EXISTS signal_outcomes (
    company_id UUID NOT NULL,
    snapshot_date DATE NOT NULL,
    horizon_months SMALLINT NOT NULL CHECK (horizon_months IN (1, 3, 6, 12)),
    is_cohort BOOLEAN NOT NULL,
    is_change BOOLEAN NOT NULL,
    end_date DATE NOT NULL,                      -- the close used: last trading day on or before the horizon
    end_price NUMERIC(12, 4) NOT NULL,
    dividends NUMERIC(12, 4) NOT NULL DEFAULT 0, -- every dividend with an ex-date in the period, one-offs included
    total_return NUMERIC(10, 2),                 -- % : (end price + dividends - signal price) / signal price
    benchmark_return NUMERIC(10, 2),             -- % : average total return of every company screened that night
    excess_return NUMERIC(10, 2),                -- percentage points: total_return - benchmark_return
    gap_closed NUMERIC(10, 2),                   -- % of the gap from price to estimated value closed (undervalued signals only)
    delisted BOOLEAN NOT NULL DEFAULT FALSE,     -- no price within 10 days of the horizon: scored at its last price
    universe_size INT NOT NULL,                  -- companies in that night's benchmark
    computed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, snapshot_date, horizon_months),
    FOREIGN KEY (company_id, snapshot_date) REFERENCES signal_snapshots(company_id, snapshot_date) ON DELETE CASCADE
);
-- One row per month, action, horizon and rules version, from the monthly
-- (cohort) signals. Kept for good: the long-run record survives the
-- 14-month deletion of the daily detail.
CREATE TABLE IF NOT EXISTS track_record_monthly (
    month DATE NOT NULL,                         -- first day of the month the signals were given
    action VARCHAR(12) NOT NULL,
    horizon_months SMALLINT NOT NULL,
    rules_version VARCHAR(10) NOT NULL,
    signals INT NOT NULL,
    beat_benchmark INT NOT NULL,                 -- signals whose excess return was above zero
    avg_return NUMERIC(10, 2),
    avg_excess NUMERIC(10, 2),
    median_excess NUMERIC(10, 2),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (month, action, horizon_months, rules_version)
);

-- 6. AUTOMATED HELPER VIEWS FOR VALUE SCREENING
CREATE OR REPLACE VIEW asx_value_screener AS
SELECT
    c.asx_code,
    c.company_name,
    c.sector,
    p.close_price AS current_price,
    v.pe_ratio,
    v.pb_ratio,
    v.roe,
    v.debt_to_equity,
    v.grossed_up_dividend_yield,
    v.dcf_intrinsic_value,
    v.graham_number,
    v.margin_of_safety_percent,
    v.payout_ratio,
    v.valuation_method,
    v.margin_of_safety_trend,
    v.fundamentals_trend,
    v.cash_conversion,
    v.earnings_quality,
    v.price_vs_200d,
    v.range_position_52w,
    v.dividend_trend,
    v.data_confidence  -- every column from payout_ratio on is appended at the end, never
                        -- inserted mid-list: CREATE OR REPLACE VIEW can only add columns at the
                        -- end - confirmed the hard way (ERROR: cannot change name of view
                        -- column) when payout_ratio was first placed mid-list and tested
                        -- against a pre-existing database
FROM companies c
JOIN daily_prices p ON c.company_id = p.company_id
    AND p.price_date = (SELECT MAX(price_date) FROM daily_prices WHERE company_id = c.company_id)
JOIN valuation_metrics v ON c.company_id = v.company_id
    AND v.as_of_date = (SELECT MAX(as_of_date) FROM valuation_metrics WHERE company_id = c.company_id)
WHERE c.is_active = TRUE
  AND c.security_type = 'SHARE';  -- ETFs are kept out of the share screener (§25)

-- INDEXES FOR SPEED
CREATE INDEX IF NOT EXISTS idx_companies_asx ON companies(asx_code);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(company_id, price_date DESC);
CREATE INDEX IF NOT EXISTS idx_financials_year ON financial_reports(company_id, fiscal_year DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_asx ON holdings(asx_code);
CREATE INDEX IF NOT EXISTS idx_holdings_portfolio ON holdings(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_signal_snapshots_date ON signal_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_watchlist_items_company ON watchlist_items(company_id);
