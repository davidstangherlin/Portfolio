/* Builds docs/ASX_Value_Screener_Rules_and_Methodology.docx.

     cd scripts && npm install && node build_rules_doc.js

   The glossary (Appendix A) comes from web/knowledge.json, the same source
   as Sift's Help page and hover explanations: edit a definition there, not
   here. Everything else in the document is written below. */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, ShadingType,
  HeadingLevel, AlignmentType, LevelFormat, BorderStyle, Footer, PageNumber, TabStopType,
} = require("docx");

const REPO = path.join(__dirname, "..");
const OUT = path.join(REPO, "docs", "ASX_Value_Screener_Rules_and_Methodology.docx");
const KNOWLEDGE = JSON.parse(fs.readFileSync(path.join(REPO, "web", "knowledge.json"), "utf8"));
const byName = (a, b) => a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
const ACRONYMS = KNOWLEDGE.entries.filter((e) => e.glossary === "acronym")
  .sort((a, b) => byName(a.abbreviation, b.abbreviation)).map((e) => [e.abbreviation, e.full, e.definition]);
const TERMS = KNOWLEDGE.entries.filter((e) => e.glossary === "term")
  .sort((a, b) => byName(a.glossary_title, b.glossary_title)).map((e) => [e.glossary_title, e.definition]);
const CONTENT = 9638; // A4 width 11906 less 2 x 1134 margins
const NAVY = "1F3864";
const HEADER_FILL = "D9E2F3";
const BAND_FILL = "F2F5FA";
const GRID = "BFC9D9";

// ---------- helpers ----------
function runs(text, opts = {}) {
  // **bold** segments inside a string
  return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((part) =>
    part.startsWith("**")
      ? new TextRun({ text: part.slice(2, -2), bold: true, ...opts })
      : new TextRun({ text: part, ...opts }));
}
const p = (text, opts = {}) => new Paragraph({ children: runs(text), spacing: { after: 120 }, ...opts });
const h1 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] });
const h2 = (text) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
const bullet = (text) => new Paragraph({ numbering: { reference: "bullets", level: 0 }, children: runs(text), spacing: { after: 60 } });
const note = (text) => new Paragraph({ children: runs(text, { italics: true, size: 18, color: "555555" }), spacing: { before: 60, after: 160 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: GRID };
const borders = { top: border, bottom: border, left: border, right: border };

function cell(text, width, { header = false, fill } = {}) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders,
    shading: header ? { fill: HEADER_FILL, type: ShadingType.CLEAR, color: "auto" }
      : fill ? { fill, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: String(text).split("\n").map((line) => new Paragraph({
      children: header ? [new TextRun({ text: line, bold: true, size: 18, color: NAVY })] : runs(line, { size: 18 }),
      spacing: { after: 0 },
    })),
  });
}

function table(headers, rows, fractions) {
  const widths = fractions.map((f) => Math.floor(CONTENT * f));
  widths[widths.length - 1] += CONTENT - widths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: CONTENT, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], { header: true })) }),
      ...rows.map((r, ri) => new TableRow({
        cantSplit: true,
        children: r.map((c, i) => cell(c, widths[i], { fill: ri % 2 ? BAND_FILL : undefined })),
      })),
    ],
  });
}
const gap = () => new Paragraph({ children: [], spacing: { after: 120 } });

// ---------- content ----------
const body = [];
const add = (...items) => body.push(...items);

// Title block
add(
  new Paragraph({ children: [new TextRun({ text: "ASX Value Screener", bold: true, size: 44, color: NAVY })], spacing: { after: 60 } }),
  new Paragraph({ children: [new TextRun({ text: "Rules and Methodology Reference", size: 30, color: "404040" })], spacing: { after: 120 } }),
  new Paragraph({
    children: [new TextRun({ text: "As at 6 October 2026  |  Research tool, not financial advice", size: 18, color: "666666" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: NAVY, space: 6 } },
    spacing: { after: 240 },
  }),
);

// 1. Executive summary
add(
  h1("1. Executive Summary"),
  p("This document sets out every rule applied by the ASX Value Screener, a research tool for shares listed on the Australian Securities Exchange (ASX), from raw market data through to the suggested action for each company, so that any output can be traced back to a defined test and threshold."),
  p("In short, the application:"),
  bullet("**Values** around 500 ASX-listed companies every trading day using two-stage cash flow models, choosing the model to suit the sector."),
  bullet("**Tests** each company against four classic Graham/Buffett value criteria, showing a pass or fail for every company rather than filtering any out."),
  bullet("**Checks quality and direction** with trend fields and four decision markers, to separate genuine mispricing from value traps."),
  bullet("**Recommends a next step** for each company, with the reason, and assesses shares you hold separately, including capital gains tax (CGT) timing."),
  bullet("**Shows the results in a browser** on your PC or phone: a filterable screener and a page per company with a score wheel built from 30 named checks."),
  p("Every rule is deliberately simple and explainable. The outputs are research prompts to direct attention, not buy or sell instructions."),
  p("Acronyms are spelled out at first use and listed, with other key terms, in Appendix A: Glossary."),
);

// 2. Summary methodology
add(
  h1("2. Summary Methodology"),
  h2("2.1 How a result is produced"),
  p("Each nightly run moves every company through seven stages. Each stage only uses the outputs of the stages before it."),
  table(["Stage", "What happens", "Fields produced"], [
    ["1. Ingest", "Daily closing prices and annual financial statements are pulled from Yahoo Finance, along with each company's country of domicile.", "Prices, financial reports, company profile"],
    ["2. Value", "Intrinsic value per share is estimated with a discounted cash flow (DCF) model or a dividend discount model (DDM), depending on sector, and compared with the share price.", "dcf_intrinsic_value, valuation_method, margin_of_safety_percent, graham_number"],
    ["3. Measure", "Profitability, leverage, valuation multiples and dividend yield are calculated from the latest annual report.", "pe_ratio, pb_ratio, price_to_fcf, ev_to_ebit, roe, roic, debt_to_equity, yields, payout_ratio"],
    ["4. Trend", "Change in margin of safety over 30 days, and the direction of return on equity (ROE) and revenue over three years.", "margin_of_safety_trend, fundamentals_trend"],
    ["5. Quality", "Four decision markers test cash backing of profit, price direction, dividend reliability and data completeness.", "earnings_quality, price_signal, dividend_trend, data_confidence"],
    ["6. Screen", "Four pass/fail value tests, a momentum indicator, a value-trap indicator and six red flags.", "mos_ok, roe_ok, de_ok, yield_ok, overall, momentum_ok, trap_risk"],
    ["7. Act", "A rule-based action and plain-English reason. Shares you hold are assessed with a separate rule set that includes CGT timing.", "action, reason"],
  ], [0.13, 0.52, 0.35]),
  gap(),
  h2("2.2 Design principles"),
  bullet("**Show everything, hide nothing.** Every company appears with a Y (yes) or N (no) result per test, so you can see how close a company is to passing."),
  bullet("**Missing data never passes.** A blank value fails the test it feeds, so gaps cannot produce a false positive."),
  bullet("**Right model for the sector.** Banks, insurers and real estate investment trusts (REITs) are valued on dividends, because their free cash flow reflects balance-sheet movements rather than business performance."),
  bullet("**Blank is better than misleading.** Implausible results (for example a margin of safety beyond plus or minus 5,000%) are stored as blank rather than shown."),
  bullet("**Cheap is not enough.** A low price is always checked against the direction and quality of the underlying business before it can earn a BUY."),
  bullet("**Every action explains itself.** Fixed, published thresholds and a stated reason for every suggestion, rather than an opaque score."),
  h2("2.3 Daily operating cycle"),
  p("The scheduled job runs after ASX close (6:00 pm) and performs seven steps in order: apply any database schema updates, ingest prices and financials, collect ETF prices and distributions and, once a month, the ASX's ETF report (section 11.7), recalculate every valuation, record that night's signals for the track record, score earlier signals whose 1, 3, 6 or 12 months have passed (section 11.4), and produce the action report. Each step runs even if an earlier one has problems. Output is written to a timestamped log in the logs folder and kept for 30 days."),
);

// 3. Data inputs
add(
  h1("3. Data Inputs and Assumptions"),
  table(["Item", "Rule"], [
    ["Price", "Latest daily closing price from Yahoo Finance."],
    ["Financial statements", "Annual reports only, one per financial year (FY). The latest FY report drives every ratio."],
    ["Averaging window", "The three most recent FY reports, used for the valuation base, cash conversion and fundamentals trend. Years with missing values are skipped."],
    ["Dividend history", "Up to the five most recent FY reports."],
    ["Dividend per FY", "Ordinary dividends per share for each financial year: the twelve months of ex-dividend dates ending four months after the balance date, capturing the interim paid during the year and the final paid after it. If those four months have not passed yet, the twelve months to today are used."],
    ["Abnormal distributions", "A single payment more than twice the company's typical annual dividend (the median twelve-month total of its other payments within three years) is excluded from every dividend figure and stored separately. Needs at least two comparable payments. The web interface shows any excluded amount."],
    ["Price history", "Closing prices from the last 365 calendar days, used for the price markers."],
    ["Shares on issue", "Market capitalisation divided by closing price. If unavailable: net profit divided by earnings per share (EPS)."],
    ["Franking", "0% for companies whose Yahoo-reported country is not Australia. Otherwise 100% (fully franked), unless corrected by hand. Manual corrections survive later data refreshes."],
    ["Corporate tax rate", "30%, used to gross up franked dividends."],
    ["Currency", "Financial statements published in another currency (US dollars for most large miners, New Zealand dollars for NZ listings) are converted into the share price's currency at the exchange rate on each report's balance date. Dividends are already in the share price's currency and are not converted. If no exchange rate is available, that company's statements are not updated for the day rather than stored in the wrong currency."],
    ["Storage safeguard", "Any value too large for its database column is stored as blank, with a warning in the log."],
  ], [0.25, 0.75]),
);

// 4. Intrinsic value
add(
  h1("4. Intrinsic Value and Margin of Safety"),
  h2("4.1 Model selection"),
  table(["Sector (per Yahoo)", "Model", "Why"], [
    ["Financial Services, Real Estate", "Two-stage dividend discount model (DDM)", "Free cash flow for banks, insurers and REITs is driven by loan books, policy reserves and property revaluations, so it is not a meaningful valuation base. Dividends are."],
    ["All other sectors", "Two-stage discounted cash flow (DCF)", "Free cash flow is the cash genuinely available to shareholders."],
  ], [0.25, 0.27, 0.48]),
  note("valuation_method records DCF or DDM. It is blank when neither model could run (for example, negative average free cash flow or no dividends)."),
  h2("4.2 Two-stage DCF"),
  bullet("**Base:** average free cash flow (FCF) over the last three FY reports. Must be greater than zero, otherwise no value is produced."),
  bullet("**Stage 1:** the base is grown at the stage 1 growth rate for five years, and each year is discounted back at the discount rate."),
  bullet("**Terminal value:** year-five cash flow × (1 + terminal growth) ÷ (discount rate − terminal growth), discounted back five years."),
  bullet("**Equity value:** present value of stage 1 + present value of terminal value + cash − total debt."),
  bullet("**Intrinsic value per share:** equity value ÷ shares on issue."),
  h2("4.3 Two-stage DDM"),
  bullet("**Base:** average dividend per share over the last three FY reports. Must be greater than zero."),
  bullet("Same two-stage structure as the DCF, applied per share. No cash or debt adjustment, because dividends are already the shareholders' share of value."),
  h2("4.4 Model assumptions"),
  table(["Parameter", "DCF", "DDM", "Override"], [
    ["Stage 1 growth rate", "8%", "5%", "--growth-rate (applies to whichever model runs)"],
    ["Stage 1 length", "5 years", "5 years", "--stage1-years"],
    ["Terminal growth rate", "2.5%", "2.5%", "--terminal-growth-rate"],
    ["Discount rate", "9%", "9%", "--discount-rate"],
    ["Averaging window", "3 years", "3 years", "--fcf-average-years"],
  ], [0.28, 0.14, 0.14, 0.44]),
  note("Dividend growth defaults lower than cash flow growth because dividends are typically steadier. The discount rate must exceed the terminal growth rate."),
  h2("4.5 Margin of safety"),
  p("**margin_of_safety_percent = (intrinsic value − price) ÷ intrinsic value × 100**"),
  bullet("Positive means the share trades below its estimated value; negative means above."),
  bullet("Blank when intrinsic value is missing, zero or negative, or when the result falls outside plus or minus 5,000% (a sign the model broke down, usually from a poor share count estimate)."),
  h2("4.6 Graham Number"),
  p("**graham_number = √(22.5 × EPS × book value per share)**, where 22.5 reflects Graham's ceilings of a price-to-earnings ratio (P/E) of 15 and a price-to-book ratio (P/B) of 1.5. Blank when EPS or book value is zero or negative. A price below it means the share meets both of Graham's limits at once. It is not used in the four value tests or the suggested action; it is one of the six Value checks in the score wheel (section 11.2). Because it ignores growth, it understates companies with few physical assets, such as software businesses."),
);

// 5. Ratio fields
add(
  h1("5. Financial Ratio Fields"),
  p("All ratios use the latest FY report and the latest closing price."),
  table(["Field", "Rule", "Notes"], [
    ["pe_ratio", "Price ÷ EPS", "Blank if EPS is zero or missing."],
    ["pb_ratio", "Price ÷ book value per share", "Book value per share = total equity ÷ shares on issue."],
    ["price_to_fcf", "Price ÷ (FCF ÷ shares on issue)", "Latest year, not the three-year average."],
    ["ev_to_ebit", "Enterprise value (EV) ÷ earnings before interest and tax (EBIT), where EV = market capitalisation + total debt − cash", "Valuation multiple that is independent of capital structure."],
    ["roe", "Net profit after tax ÷ total equity × 100", "Return on equity, %."],
    ["roic", "Net profit after tax ÷ (total debt + total equity − cash) × 100", "Return on invested capital (ROIC), %."],
    ["debt_to_equity", "Total debt ÷ total equity", "Expressed as a ratio, not a %."],
    ["uncapped_dividend_yield", "Dividend per share ÷ price × 100", "Cash yield, before franking credits."],
    ["grossed_up_dividend_yield", "Dividend per share × (1 + franking % × 30 ÷ 70) ÷ price × 100", "Includes franking credits. Fully franked = cash yield × 1.43; unfranked = cash yield."],
    ["payout_ratio", "Dividend per share ÷ EPS × 100", "Only when EPS is positive. Blank beyond 5,000%. Above 150% is a red flag (likely one-off dividend). Uses ordinary dividends only (see section 3)."],
    ["current_ratio", "Not calculated", "The source data does not split current assets and liabilities."],
  ], [0.25, 0.42, 0.33]),
);

// 6. Core value tests
add(
  h1("6. Core Value Tests"),
  p("These four tests are the heart of the screen. Each produces Y (yes) or N (no) for every company."),
  table(["Indicator", "Test", "Default", "Override"], [
    ["mos_ok", "margin_of_safety_percent above threshold", "> 20%", "--min-margin-of-safety"],
    ["roe_ok", "roe above threshold", "> 12%", "--min-roe"],
    ["de_ok", "debt_to_equity below threshold", "< 0.80", "--max-debt-equity"],
    ["yield_ok", "grossed_up_dividend_yield above threshold", "> 4.5%", "--min-yield"],
    ["overall", "Y when all four tests are Y", "All four", "--any-of (any one test)"],
  ], [0.16, 0.42, 0.14, 0.28]),
  gap(),
  bullet("Comparisons are strict: a value exactly on the threshold fails."),
  bullet("A blank value is N."),
  bullet("Nothing is filtered by default. --passing-only shows only overall = Y; --sector restricts to one sector."),
);

// 7. Trend fields
add(
  h1("7. Trend Fields"),
  p("Trend fields answer two questions a single snapshot cannot: is the price moving towards value, and is the business improving or deteriorating?"),
  table(["Field", "Rule", "Values and notes"], [
    ["margin_of_safety_trend", "Today's margin of safety minus the margin of safety from the most recent valuation at least 30 days old.", "Percentage points. Blank until 30 days of daily history exist. Window set by --trend-days."],
    ["momentum_ok", "margin_of_safety_trend above 5 percentage points.", "Y/N. Means \"getting cheaper\". Threshold set by --min-mos-trend."],
    ["fundamentals_trend", "Compares the latest and oldest FY reports in the three-year window. DECLINING if ROE fell by more than 2 percentage points or revenue fell by more than 5%. Otherwise IMPROVING if ROE rose by more than 2 points or revenue rose by more than 5%. Otherwise STABLE.", "DECLINING takes precedence when ROE and revenue disagree. Blank with fewer than two reports. Independent of price."],
    ["trap_risk", "mos_ok = Y and fundamentals_trend = DECLINING.", "Y/N. Looks cheap, but the business is heading the wrong way."],
  ], [0.22, 0.48, 0.30]),
  note("momentum_ok and trap_risk are informational. They do not affect overall, but both feed the suggested action."),
);

// 8. Decision markers
add(
  h1("8. Decision Markers"),
  p("Each marker tests one aspect of quality that the four value tests cannot see."),
  table(["Field", "Rule", "Values and notes"], [
    ["cash_conversion", "Total operating cash flow ÷ total net profit × 100, summed across the three-year window.", "Blank for loss-makers and for Financial Services and Real Estate (where operating cash flow is not comparable)."],
    ["earnings_quality", "From cash_conversion: STRONG at 100% or more; ADEQUATE from 80% to under 100%; WEAK below 80%.", "Is reported profit turning into cash?"],
    ["price_vs_200d", "(Latest close ÷ average of the last 200 closes − 1) × 100.", "% above or below the 200-day average. Needs 200 closes."],
    ["range_position_52w", "(Latest close − 52-week low) ÷ (52-week high − 52-week low) × 100.", "0 = at the low, 100 = at the high. Needs 100 closes."],
    ["price_signal", "NEW LOWS if below the 200-day average and in the bottom 10% of the 52-week range. DOWNTREND if below the 200-day average. UPTREND otherwise.", "Is the price stabilising or still falling? Blank without 200 closes."],
    ["dividend_trend", "Over up to five FY reports: NONE if no dividends paid. CUT if the latest dividend is more than 10% below last year's, or more than 10% below the median of the earlier years. GROWING if the latest is more than 5% above the oldest. Otherwise STEADY.", "Only a cut that still stands counts; a cut since restored does not. Blank with fewer than two years."],
    ["data_confidence", "Share of 11 checks present: closing price, market capitalisation, EPS, net profit, revenue, equity, total debt, operating cash flow, free cash flow, at least 3 FY reports, at least 200 days of prices. HIGH = 10 or 11; MEDIUM = 8 or 9; LOW = 7 or fewer.", "Dividends are excluded: a non-payer is not missing data."],
  ], [0.20, 0.50, 0.30]),
);

// 9. Red flags
add(
  h1("9. Red Flags"),
  p("Red flags are the conditions that downgrade an otherwise attractive company. Any one flag is enough to block a BUY."),
  table(["Flag", "Trigger", "Wording in the reason"], [
    ["Value-trap risk", "trap_risk = Y", "value-trap risk (cheap but ROE/revenue declining)"],
    ["One-off dividend", "payout_ratio above 150%", "payout ratio X% suggests a one-off dividend"],
    ["Weak earnings quality", "earnings_quality = WEAK", "weak earnings quality (cash flow X% of profit)"],
    ["Dividend cut", "dividend_trend = CUT", "dividend cut and not yet restored"],
    ["Still falling", "price_signal = NEW LOWS", "price still making new lows"],
    ["Data gaps", "data_confidence = LOW", "low data confidence, verify the inputs"],
  ], [0.22, 0.28, 0.50]),
);

// 10. Suggested actions
add(
  h1("10. Suggested Actions"),
  h2("10.1 Shares you do not hold"),
  p("Rules are applied in order; the first match decides the action."),
  table(["Order", "Action", "Condition"], [
    ["1", "AVOID", "trap_risk = Y and earnings_quality = WEAK: cheap, declining and profit not backed by cash."],
    ["2", "BUY", "Passes all four value tests with no red flags. The reason notes \"getting cheaper\" when momentum_ok = Y."],
    ["3", "INVESTIGATE", "Passes all four value tests but has one or more red flags."],
    ["4", "INVESTIGATE", "mos_ok = Y and passes three of the four tests. The reason names the failed test."],
    ["5", "WATCH", "mos_ok = Y but passes two or fewer tests."],
    ["6", "WATCH", "momentum_ok = Y: getting cheaper quickly but not yet below estimated value."],
    ["7", "WATCH", "ROE, debt and yield pass but the price is not yet cheap: wait for a better price."],
    ["8", "IGNORE", "None of the above: no value signal. Counted, not listed."],
  ], [0.10, 0.17, 0.73]),
  note("INVESTIGATE and WATCH reasons list any red flags, so a WATCH never reads healthier than the data supports."),
  h2("10.2 Shares you hold"),
  table(["Order", "Action", "Condition"], [
    ["1", "SELL", "fundamentals_trend = DECLINING and at least one of: trading above estimated value (margin of safety below zero), earnings_quality = WEAK, dividend_trend = CUT."],
    ["2", "REVIEW", "Any red flag, or margin of safety below −50% (well above estimated value)."],
    ["3", "ACCUMULATE", "Passes all four value tests with no red flags: the same bar as BUY for a share you do not own, so consider adding. The reason notes \"getting cheaper\" when momentum_ok = Y."],
    ["4", "HOLD", "Otherwise: no red flags, but fails one or more value tests (named in the reason), so not a candidate to add to."],
  ], [0.10, 0.17, 0.73]),
  gap(),
  p("**CGT timing note.** On a SELL or REVIEW, if any open parcel becomes eligible for the 50% CGT discount within the next 90 days, the reason states how many units and from what date, so the timing of a sale can be considered. The note never appears on ACCUMULATE or HOLD, since neither suggests selling."),
  h2("10.3 Report order"),
  p("The action report groups companies as SELL, REVIEW, ACCUMULATE, HOLD, BUY, INVESTIGATE, WATCH and AVOID, sorted by margin of safety within each group. IGNORE is counted only."),
);

// 11. Score wheel
add(
  h1("11. Web Interface (Sift)"),
  p("Sift is the browser interface to the screener. It shows the same results as the command-line tools, plus the displays below."),
  h2("11.1 Valuation status"),
  table(["Status", "Rule"], [
    ["Undervalued", "Margin of safety above 20% (passes the margin of safety value test)."],
    ["Fair value", "Margin of safety from 0% to 20%."],
    ["Overvalued", "Margin of safety below 0%: the price is above estimated value."],
    ["No estimate", "No valuation model could run, so there is no margin of safety."],
  ], [0.2, 0.8]),
  note("Implied upside, shown on each company page, is (estimated value - price) / price. It differs from margin of safety, which divides by estimated value: a 40% margin of safety is a 67% implied upside."),
  h2("11.2 Score wheel"),
  p("The web interface's company page summarises each company on a five-spoke score wheel, similar in style to Simply Wall St. Each spoke counts how many of six yes/no checks the company passes, so its score runs from 0 to 6 and every point traces to a named rule."),
  bullet("A check with missing data shows as no data and never counts as a pass."),
  bullet("Thresholds reuse the screener's own wherever one exists, so the wheel cannot contradict the value tests or markers."),
  bullet("The wheel describes a company; it does not decide anything. The suggested action still comes only from the rules in section 10."),
  table(["Spoke", "The six checks (one point each)"], [
    ["Value", "Margin of safety above 0%; above 20%; above 40%. P/E between 0 and 15. P/B between 0 and 1.5. Price below the Graham Number."],
    ["Performance", "ROE above 12%; above 20%. ROIC above 10%. fundamentals_trend not DECLINING. earnings_quality STRONG or ADEQUATE; STRONG."],
    ["Health", "Debt to equity below 0.8; below 0.4. Cash at least equal to total debt. Positive shareholders' equity. Positive free cash flow. Positive net profit."],
    ["Dividend", "Pays a dividend. Grossed-up yield above 4.5%; above 6%. Payout ratio 100% or less. dividend_trend STEADY or GROWING; GROWING."],
    ["Momentum", "price_signal UPTREND. Not making new 52-week lows. In the upper half of the 52-week range. margin_of_safety_trend above zero; momentum_ok = Y. fundamentals_trend IMPROVING."],
  ], [0.17, 0.83]),
  note("A semicolon separates two thresholds on the same measure, for example ROE above 12% and ROE above 20% are two separate checks."),
  h2("11.3 Dashboard"),
  p("Sift opens on a dashboard that applies the following rules. It reads the same results as the screener; it adds no new tests."),
  table(["Panel", "Rule"], [
    ["Data date", "The date of the latest valuations. Shown as out of date when it is older than the previous weekday's close (so Friday's data stays current over the weekend; a public holiday also shows as out of date). Also flagged when the last nightly run crashed or did not finish. Individual companies that could not be updated are reported but not flagged, as a few occur most nights."],
    ["Portfolio", "Value is units held multiplied by the latest close. Today's change compares the two latest closes. Unrealised gain is value less cost base, before tax."],
    ["Needs attention", "Held shares with a SELL or REVIEW action, parcels that reach the CGT discount within 90 days, held shares missing from the nightly ticker file, and watchlist entries whose trigger is met (section 11.5)."],
    ["What changed", "Companies whose suggested action moved between the latest two nights of recorded signals, ranked BUY and ACCUMULATE, then INVESTIGATE, then WATCH and HOLD, then REVIEW and IGNORE, then AVOID and SELL. A move within the same rank, or one caused by buying or selling the shares, is not listed. Companies on a watchlist are listed first, then better moves first."],
    ["Top opportunities", "Up to six shares you do not hold: BUY first, then INVESTIGATE, each ordered by score wheel total and then margin of safety."],
  ], [0.2, 0.8]),
  note("The menu bar's Markets links open the ASX, the ASX exchange traded fund (ETF) directory, the New York Stock Exchange (NYSE) and Nasdaq websites."),
  h2("11.4 Track record recording"),
  p("To test whether the suggestions work, every night Sift records what it said about each screened company: its signal. The record is the basis for measuring accuracy, and follows these rules."),
  bullet("**Never edited.** A night once recorded is kept exactly as it was, so later rule changes cannot rewrite what was said at the time."),
  bullet("**Dated by the valuation.** Each signal carries the closing price and date its valuation used."),
  bullet("**Out-of-date valuations are skipped.** If a company's valuation failed that night, no signal is recorded for it rather than pairing an old estimate with a new price."),
  bullet("**Rules version.** Each signal records the date the screening rules last changed, so each version of the rules is judged on its own results."),
  bullet("**Forward only.** Results are measured from the first night recorded; past signals are not reconstructed, because today's data would flatter them."),
  p("Signals are then scored as follows."),
  table(["Item", "Rule"], [
    ["Signals scored", "Each company's first signal of each month, so a company that stays BUY all month counts once. Nights when a company's action changed are scored too, but kept out of the monthly results."],
    ["Periods", "1, 3, 6 and 12 months after the signal, once prices reach that date."],
    ["Total return", "(Closing price at the end of the period + every dividend paid in it, one-offs included − price at the signal) ÷ price at the signal."],
    ["Benchmark", "The average total return, over the same period, of every company screened on the night of the signal."],
    ["Excess return", "Total return minus the benchmark, in percentage points. A BUY, ACCUMULATE or INVESTIGATE call is right when this is above zero; an AVOID or SELL call is right when it is below zero."],
    ["Delisted companies", "A company with no price within 10 days of the period's end is scored at its last price, so failures stay in the record."],
    ["Confidence", "Too early with fewer than 30 signals; moderate from 30 to 100; solid above 100."],
    ["Order check", "BUY should beat WATCH, and WATCH should beat AVOID, on average excess return. Judged only once each has 30 signals. If not, the rules need review."],
    ["Missed opportunity", "A BUY or INVESTIGATE call on a share you did not hold and did not buy within 30 days, which beat the average by more than 10 points."],
    ["Money saved", "An AVOID call on a share you did not hold, or a SELL call on one you did, which trailed the average by more than 10 points."],
    ["Still actionable", "Today's signals of an action that has beaten the average at 3 months with at least moderate confidence, while the share is still more than 20% below estimated value. Until an action is proven, BUY signals are shown on the rules' own terms."],
    ["Retention", "Daily signals and their results are kept for 14 whole months. A summary per month, action, period and rules version is kept permanently."],
  ], [0.22, 0.78]),
  h2("11.5 Watchlists"),
  p("Watchlists are named lists of companies and ETFs to follow without owning them. Only companies Sift values, and ETFs it follows, can be added. Each entry can carry a note and triggers."),
  table(["Trigger", "Met while"], [
    ["Margin of safety above X%", "The company's current margin of safety is strictly above X. X may be negative."],
    ["Price at or below $Y", "The latest closing price is at or below Y. Y must be above zero."],
    ["Yield above X% (ETFs only)", "The ETF's 12-month distribution yield is strictly above X. Margin of safety triggers are for shares only."],
  ], [0.3, 0.7]),
  bullet("A trigger is a live condition, not an alert: it shows while it is true and disappears when it stops being true."),
  bullet("A company with no current valuation or price meets neither trigger."),
  bullet("Watchlists are separate from the nightly ticker file, which decides which companies are valued at all."),
  h2("11.6 Admin console and what-if scenarios"),
  p("Every threshold and assumption in this document is held in one place in the code (29 settings in four groups: valuation models, value tests, markers and actions, and the score wheel). The admin console shows each with its live value, allowed range, formula and where it is used, linked to its Help entry."),
  bullet("**Show workings.** Each company page can show every figure step by step, from the cash flow or dividend base through the projection and discounting to estimated value, margin of safety, each test and each marker, with a sensitivity grid of estimated value across discount and growth rates."),
  bullet("**What-if scenarios.** A scenario changes one or more settings and is run against today's data alongside the live settings, showing which companies' actions, valuation status or estimated value would change."),
  bullet("**Guard rails.** A scenario is refused if the discount rate is not above terminal growth, if ADEQUATE earnings quality is set above STRONG, or if a score wheel threshold is not stricter than its value test."),
  bullet("**Nothing live changes.** Scenarios are for exploring only. The nightly job, screener, actions and track record always use the live settings in this document; the margin of safety trend in a scenario stays at its live value."),
  h2("11.7 Exchange traded funds (ETFs)"),
  p("Every exchange traded product listed on the ASX is collected, but ETFs are not valued, tested, scored or tracked as companies: a fund has no cash flow or dividend policy of its own to value. They are judged on cost, size, distributions and performance."),
  table(["Item", "Rule"], [
    ["ETF list and fund facts", "From the ASX Investment Products report, monthly. Each night until last month's report is loaded, Sift looks in data/asx_reports and then on the ASX website. ETFs the newest report no longer lists are marked inactive; their history is kept. LICs and LITs are excluded."],
    ["Report columns", "Matched by their headings (issuer, fee, fund size, flows, spread, yield, performance), not by position. The category is the section heading above each fund (for example Equity - Australia). Fractions written as plain numbers (0.0737 for 7.37%) are converted. Benchmark index rows, LICs, A-REITs and infrastructure funds are left out. Every column is also kept as written."],
    ["ASX returns", "The report's 1-month and 1, 3 and 5-year returns come from Bloomberg with dividends reinvested gross, including franking credits. Each ETF's page shows them beside Sift's own cash-only returns."],
    ["Prices and distributions", "Yahoo Finance, nightly. The full history the first time an ETF is seen, then the last month. Closes are the prices actually traded (split-adjusted only); a split refetches the full history once."],
    ["Total return", "One unit bought at the close on the start date, each distribution reinvested at the close on its ex-date (or the next close), valued at the latest close. 1, 3 and 6 months and 1 year as is; 3, 5 and 10 years and since first price (when over a year) as a yearly rate."],
    ["Missing periods", "No figure unless there is a close within 10 days of the period's start and end, so a fund younger than the period shows nothing."],
    ["Trailing yield", "Cash distributions with ex-dates in the last 12 months, divided by the latest close. All distributions count, including year-end distributions of gains."],
    ["Check against the ASX", "Each month Sift's 1-year return at the report's month end is set beside the report's figure. A gap of more than 2 points is listed in the nightly log and noted on the ETF's page."],
    ["Category average", "For each period, the plain average of the returns of the ETFs in the same ASX category that have a figure for it."],
    ["Reference fund", "The largest other ETF by fund size in the same category, unless another is chosen on the ETF's page. Growth of $10,000 starts both funds on the same date."],
  ], [0.25, 0.75]),
  h2("11.8 Listed investment companies and trusts (LICs)"),
  p("LICs and LITs are listed funds with a fixed number of shares, so the share price can sit above or below the value of what they hold. Sift treats them as a third group, apart from shares and ETFs, judged on the share price against net tangible assets (NTA)."),
  table(["Item", "Rule"], [
    ["Source", "The LIC sheet of the ASX Investment Products report, monthly: type (LIC, LIT), category, fee, performance fee, market cap, pre-tax NTA and its date, the premium or discount at that date, yield and returns. Benchmark index rows are left out."],
    ["Shares reclassified", "A code already valued as a share that appears on the LIC sheet becomes an LIC: it leaves the share screener, suggested actions, scores and the track record."],
    ["Premium or discount", "Latest share price divided by the last reported NTA, less one. Until prices are stored, the report's own figure at the NTA date. Positive is a premium, negative a discount."],
    ["Prices, dividends, returns", "As for ETFs (section 11.7), fetched by the same nightly step; dividends are cash, before franking."],
    ["Watchlist triggers", "Price at or below $Y; 12-month yield above X%; discount to NTA of at least X% (met while the premium is at or below minus X)."],
  ], [0.25, 0.75]),
  bullet("**Presented apart from shares.** ETFs have their own screener and page per ETF, and their own section on the dashboard, in each portfolio (with its own subtotal) and in each watchlist. They never appear in the share screener, suggested actions, scores or the track record."),
);

// 12. Holdings and CGT
add(
  h1("12. Holdings and CGT Rules"),
  p("Holdings are recorded parcel by parcel, in the browser or at the command line, and each parcel belongs to a portfolio. The tax arithmetic follows the mechanical parts of the Australian Taxation Office (ATO) rules, with the capital gains tax (CGT) discount set by who owns the portfolio."),
  table(["Item", "Rule"], [
    ["Parcel", "Each acquisition is recorded separately: units, date, price, brokerage, method (purchase, dividend reinvestment plan (DRP), bonus, transfer, other), broker and notes."],
    ["Cost base", "Units × buy price + buy brokerage."],
    ["Capital proceeds", "Units × sell price − sell brokerage."],
    ["Capital gain or loss", "Capital proceeds − cost base."],
    ["Discount eligibility", "The sale must fall strictly after the first anniversary of purchase. A 29 February purchase anniversaries on 28 February."],
    ["Portfolio", "A named group of parcels with one owner. Every parcel belongs to exactly one portfolio, and a sale only draws on that portfolio's parcels. Parcels recorded before portfolios existed were moved into \"My portfolio\" (individual)."],
    ["Discount rate", "Set by the portfolio's tax type: individual 50%, trust 50%, self-managed super fund (SMSF) 33⅓%, company nil. Company parcels never wait for a discount date."],
    ["Archive and delete", "A portfolio can be archived once every parcel in it is sold; it then accepts no trades but keeps its sales in the CGT report. It can be deleted only while it has no sales, because sale records are kept for five years after each sale."],
    ["Corrections", "Delete removes an open parcel entered by mistake. Undo reverses a sale: a portion split from a parcel that is still open goes back into it, restoring the original cost base."],
    ["Financial year", "1 July to 30 June, labelled for example 2025-26."],
    ["Loss ordering", "Capital losses offset non-discountable gains first, then discountable gains. The portfolio's discount applies to what remains of the discountable gains. Leftover losses are reported as unused. Each portfolio is reported separately."],
    ["Partial sale", "The parcel is split; sell brokerage is apportioned by units."],
    ["Sell order", "First in, first out (FIFO): oldest parcel first; min-tax (lowest taxable gain per unit first, with losses first and discount-eligible gains reduced by the portfolio's discount); or a specific parcel."],
    ["Not covered", "Losses carried forward from earlier years, dividend income and franking credits, cost base adjustments for corporate actions, and moving parcels between portfolios (record an off-market transfer as a sale in one and a buy in the other)."],
  ], [0.22, 0.78]),
  note("A record-keeping aid to reconcile against broker statements, not tax advice."),
);

// 13. Limitations
add(
  h1("13. Key Limitations"),
  bullet("**Source data.** Yahoo Finance data varies in completeness and accuracy. data_confidence and the red flags highlight gaps but cannot correct source errors."),
  bullet("**Fixed thresholds.** The same thresholds apply across all sectors (apart from the choice of valuation model), and the rules cannot see context such as takeover bids, write-downs or management change."),
  bullet("**Franking.** Australian companies are assumed fully franked unless corrected by hand, so partly franked payers and some listed investment companies (LICs) are overstated."),
  bullet("**Share count.** Shares on issue are estimated, which can distort per-share values for small companies. The margin of safety sanity cap removes the worst cases."),
  bullet("**History needed.** margin_of_safety_trend needs 30 days of daily valuations, and the price markers need about 200 trading days of prices (a one-off one-year price backfill fills this immediately)."),
  bullet("**Currency movements.** Statements in other currencies are converted at each year's own exchange rate, so revenue growth is measured in Australian dollars and includes currency movements."),
  bullet("**Two-point trends.** fundamentals_trend compares only the first and last years of the window, not the path between them."),
  bullet("**Track record benchmark.** Signals are judged against the plain average of the screened companies, not a market index, so small companies count as much as large ones. Brokerage, tax and the timing of trades within a day are ignored, and results can only be measured forward from the first night recorded."),
  bullet("**Watchlist triggers.** A trigger is a live condition shown while it is true; nothing is sent, and a trigger met and lost between two visits is not recorded."),
  bullet("**Portfolios.** Parcels cannot be moved between portfolios: an off-market transfer is recorded as a sale in one and a buy in the other. Changing a portfolio's tax type re-rates the sales already recorded in it."),
);


// Appendix A: Glossary
add(
  new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Appendix A: Glossary")] }),
  h2("A.1 Acronyms"),
  table(["Acronym", "Full term", "Meaning in this document"], ACRONYMS, [0.12, 0.30, 0.58]),
  gap(),
  h2("A.2 Key terms"),
  table(["Term", "Definition"], TERMS, [0.26, 0.74]),
);

// ---------- document ----------
const doc = new Document({
  creator: "ASX Value Screener",
  title: "ASX Value Screener: Rules and Methodology",
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: NAVY },
        paragraph: { spacing: { before: 320, after: 140 }, outlineLevel: 0, keepNext: true } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: "Arial", color: "2E5597" },
        paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 1, keepNext: true } },
    ],
  },
  numbering: {
    config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }],
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 } } },
    footers: {
      default: new Footer({ children: [new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: CONTENT }],
        children: [
          new TextRun({ text: "ASX Value Screener: Rules and Methodology", size: 16, color: "888888" }),
          new TextRun({ children: ["\tPage ", PageNumber.CURRENT, " of ", PageNumber.TOTAL_PAGES], size: 16, color: "888888" }),
        ],
      })] }),
    },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT); });
