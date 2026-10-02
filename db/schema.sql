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
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

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
    dividends_per_share NUMERIC(10, 4),
    franking_percentage NUMERIC(5, 2) DEFAULT 100.0, -- e.g., 100.00 for fully franked
    corporate_tax_rate NUMERIC(4, 2) DEFAULT 30.0,   -- Standard Australian 30% rate

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, fiscal_year, period_type)
);

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
WHERE c.is_active = TRUE;

-- INDEXES FOR SPEED
CREATE INDEX IF NOT EXISTS idx_companies_asx ON companies(asx_code);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(company_id, price_date DESC);
CREATE INDEX IF NOT EXISTS idx_financials_year ON financial_reports(company_id, fiscal_year DESC);
CREATE INDEX IF NOT EXISTS idx_holdings_asx ON holdings(asx_code);
