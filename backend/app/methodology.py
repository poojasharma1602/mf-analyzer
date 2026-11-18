"""User-facing methodology text. Single source of truth for the UI, the README and the Excel export."""

SECTIONS = [
    {
        "title": "Data and as-of dates",
        "body": [
            "NAV history comes only from the provider (mfapi.in) and is cached locally in SQLite. Nothing is estimated or filled in.",
            "Every row shows the date of the latest NAV used. Monthly ratios end at the last COMPLETE calendar month (a month whose last NAV is more than 4 days before month-end is treated as still open and dropped), so the ratio period can end earlier than the NAV as-of date.",
            "If the provider is unreachable, cached data is used and flagged as stale; with no cache the fund shows an error instead of numbers.",
        ],
    },
    {
        "title": "Returns convention",
        "body": [
            "Monthly return r(t) = NAV(t) / NAV(t-1) - 1 using the last available NAV in each calendar month. Only consecutive calendar months produce a return; a missing month is never bridged or filled.",
            "Returns are NAV-based. For Growth options this approximates total return. For IDCW / Dividend / Payout options the NAV drops on each distribution and this tool does NOT add distributions back, so returns are understated. Prefer Growth options. The option type is inferred from the scheme name (heuristic) and can be wrong.",
            "Returns are net of the scheme's expense ratio and exclude exit loads, taxes and any investor-level transaction costs.",
        ],
    },
    {
        "title": "3-year CAGR",
        "body": [
            "CAGR = (NAV_end / NAV_start)^(365.25 / days) - 1 where NAV_end is the latest NAV, and NAV_start is the last NAV on or before (latest date minus 3 calendar years). Days is the actual number of days between the two NAV dates.",
            "N/A if no NAV exists within 7 days before the start date (history too short or a data gap).",
        ],
    },
    {
        "title": "Analysis window and minimum sample",
        "body": [
            "Ratios use the most recent N monthly returns (default 36, configurable) ending at the last complete month. A minimum number of valid monthly observations (default 24, configurable) is required; otherwise the metric shows N/A with the reason.",
            "Benchmark-relative metrics use only months present in BOTH the fund and the benchmark, over the window ending at the earlier of the two series' last complete month. The matched observation count is shown.",
        ],
    },
    {
        "title": "Risk-free rate and minimum acceptable return",
        "body": [
            "Both are annual rates you configure (the risk-free default is a placeholder, not a fetched market rate). They are converted to monthly equivalents geometrically: (1 + R)^(1/12) - 1.",
        ],
    },
    {
        "title": "Sharpe ratio",
        "body": [
            "Sharpe = mean(r - rf_m) / stdev(r - rf_m) x sqrt(12), sample standard deviation (n-1), monthly returns. N/A if volatility of excess returns is zero.",
        ],
    },
    {
        "title": "Sortino ratio",
        "body": [
            "Sortino = (mean(r) - MAR_m) / DD x sqrt(12), with downside deviation DD = sqrt(mean(min(r - MAR_m, 0)^2)) taken over all N monthly observations. N/A if no month fell below the MAR (zero downside deviation).",
        ],
    },
    {
        "title": "Beta",
        "body": [
            "Beta = covariance(r_fund, r_benchmark) / variance(r_benchmark) on matched monthly returns (equivalent to the OLS slope). Requires an imported benchmark TRI series.",
        ],
    },
    {
        "title": "Jensen's alpha",
        "body": [
            "Monthly alpha = (mean(r_fund) - rf_m) - beta x (mean(r_benchmark) - rf_m). Reported annualised by multiplying by 12 (arithmetic annualisation). Same matched window as beta.",
        ],
    },
    {
        "title": "Information ratio",
        "body": [
            "Active return a(t) = r_fund(t) - r_benchmark(t). IR = (mean(a) x 12) / (stdev(a) x sqrt(12)) = mean(a)/stdev(a) x sqrt(12). Annualised active return and tracking error are also exported. N/A if tracking error is zero.",
        ],
    },
    {
        "title": "Volatility and maximum drawdown",
        "body": [
            "Volatility = stdev of monthly returns x sqrt(12). Maximum drawdown is the largest peak-to-trough fall of the month-end NAV series within the window, so it understates intra-month drawdowns.",
        ],
    },
    {
        "title": "Benchmarks",
        "body": [
            "Benchmark total return index (TRI) data is imported from CSV (columns: Date, Index Value). The tool maps schemes to benchmark names by category-level default rules that you can override per scheme; the defaults are suggestions, not each scheme's official benchmark - verify with the scheme documents.",
            "The same month-end alignment rule is applied to the benchmark as to the fund. Use TRI (not price) indices; a price index omits dividends and biases alpha upward.",
        ],
    },
    {
        "title": "Limitations",
        "body": [
            "A single ratio does not show that a fund is good or bad. Ratios are backward-looking, depend on the window, benchmark and risk-free rate chosen, and are noisy over 24-36 monthly observations.",
            "Beta, alpha and the information ratio are only as meaningful as the benchmark match and the CSV quality. Past performance does not predict future results. This is an analysis aid, not investment advice.",
        ],
    },
]
