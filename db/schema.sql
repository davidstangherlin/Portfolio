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

    -- Intrinsic Valuations & Margin of Safety
    dcf_intrinsic_value NUMERIC(12, 4),          -- Discounted Cash Flow valuation
    graham_number NUMERIC(12, 4),                -- Sqrt(22.5 * EPS * BVPS)
    margin_of_safety_percent NUMERIC(6, 2),      -- ((Intrinsic Value - Current Price) / Intrinsic Value) * 100

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (company_id, as_of_date)
);

-- 5. AUTOMATED HELPER VIEWS FOR VALUE SCREENING
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
    v.margin_of_safety_percent
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
