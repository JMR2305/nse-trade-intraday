#!/usr/bin/env bash
# Phase 1D — Production custom universe upsert
# Run this AFTER publishing the API server to make the /universe/custom/upsert endpoint available.
# This is the one-time production-approved execution path.
# Safe to re-run (idempotent ON CONFLICT DO UPDATE).
#
# Expected result: {"success": true, "upserted": 25}

PROD_URL="https://nse-trade-intraday.replit.app"

curl -s -X POST "${PROD_URL}/api/universe/custom/upsert" \
  -H "Content-Type: application/json" \
  -d '{
  "rows": [
    {
      "symbol": "WIPRO", "company_name": "Wipro Ltd", "sector": "IT",
      "industry": "IT Services", "yahoo_symbol": "WIPRO.NS", "kite_symbol": "WIPRO",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 180.79, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 4635652, "avg_turnover_20d": 837793780,
      "ohlcv_available": true,
      "reason_included": "Only qualifying IT name in Option B band; F&O stock; NIFTY_50 mapping verified",
      "reason_excluded": null
    },
    {
      "symbol": "IRFC", "company_name": "Indian Railway Finance Corporation",
      "sector": "INFRA", "industry": "Infrastructure Finance",
      "yahoo_symbol": "IRFC.NS", "kite_symbol": "IRFC",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 86.40, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 4765907, "avg_turnover_20d": 411774365,
      "ohlcv_available": true,
      "reason_included": "PSU infra; high retail participation; yfinance verified",
      "reason_excluded": null
    },
    {
      "symbol": "NBCC", "company_name": "NBCC India Ltd",
      "sector": "INFRA", "industry": "Construction",
      "yahoo_symbol": "NBCC.NS", "kite_symbol": "NBCC",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 88.88, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 5369124, "avg_turnover_20d": 477101524,
      "ohlcv_available": true,
      "reason_included": "PSU construction infra; budget-cycle sensitivity; good volumes",
      "reason_excluded": null
    },
    {
      "symbol": "NMDC", "company_name": "NMDC Ltd",
      "sector": "INFRA", "industry": "Mining",
      "yahoo_symbol": "NMDC.NS", "kite_symbol": "NMDC",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 84.61, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 18865805, "avg_turnover_20d": 1595614161,
      "ohlcv_available": true,
      "reason_included": "High volume mining PSU; commodity-sensitive; F&O-eligible",
      "reason_excluded": null
    },
    {
      "symbol": "IRCON", "company_name": "IRCON International Ltd",
      "sector": "INFRA", "industry": "Construction",
      "yahoo_symbol": "IRCON.NS", "kite_symbol": "IRCON",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 124.72, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 909714, "avg_turnover_20d": 113439133,
      "ohlcv_available": true,
      "reason_included": "PSU infra construction; decent volumes",
      "reason_excluded": null
    },
    {
      "symbol": "HUDCO", "company_name": "Housing and Urban Development Corporation",
      "sector": "INFRA", "industry": "Infrastructure Finance",
      "yahoo_symbol": "HUDCO.NS", "kite_symbol": "HUDCO",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 186.09, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 875044, "avg_turnover_20d": 162892441,
      "ohlcv_available": true,
      "reason_included": "PSU housing/urban infra finance; good retail participation",
      "reason_excluded": null
    },
    {
      "symbol": "GAIL", "company_name": "GAIL India Ltd",
      "sector": "INFRA", "industry": "Gas Distribution",
      "yahoo_symbol": "GAIL.NS", "kite_symbol": "GAIL",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 172.00, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 6509016, "avg_turnover_20d": 1119550752,
      "ohlcv_available": true,
      "reason_included": "F&O stock; high volume; gas price sensitive",
      "reason_excluded": null
    },
    {
      "symbol": "SAIL", "company_name": "Steel Authority of India Ltd",
      "sector": "INFRA", "industry": "Steel",
      "yahoo_symbol": "SAIL.NS", "kite_symbol": "SAIL",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 173.46, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 14683544, "avg_turnover_20d": 2545956062,
      "ohlcv_available": true,
      "reason_included": "F&O stock; very high volume; commodity infra proxy",
      "reason_excluded": null
    },
    {
      "symbol": "MRPL", "company_name": "Mangalore Refinery and Petrochemicals Ltd",
      "sector": "INFRA", "industry": "Refinery",
      "yahoo_symbol": "MRPL.NS", "kite_symbol": "MRPL",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 176.81, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 6535381, "avg_turnover_20d": 1155220276,
      "ohlcv_available": true,
      "reason_included": "HPCL subsidiary refinery; decent intraday volumes",
      "reason_excluded": null
    },
    {
      "symbol": "RVNL", "company_name": "Rail Vikas Nigam Ltd",
      "sector": "INFRA", "industry": "Railway Infrastructure",
      "yahoo_symbol": "RVNL.NS", "kite_symbol": "RVNL",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 225.30, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 2616366, "avg_turnover_20d": 589267290,
      "ohlcv_available": true,
      "reason_included": "High retail participation; infra budget-driven; Option B band",
      "reason_excluded": null
    },
    {
      "symbol": "RECLTD", "company_name": "REC Ltd",
      "sector": "INFRA", "industry": "Infrastructure Finance",
      "yahoo_symbol": "RECLTD.NS", "kite_symbol": "RECLTD",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 326.65, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 4327156, "avg_turnover_20d": 1413436234,
      "ohlcv_available": true,
      "reason_included": "F&O stock; infrastructure lending PSU; high volume",
      "reason_excluded": null
    },
    {
      "symbol": "NTPC", "company_name": "NTPC Ltd",
      "sector": "INFRA", "industry": "Power Generation",
      "yahoo_symbol": "NTPC.NS", "kite_symbol": "NTPC",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 340.00, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 6532622, "avg_turnover_20d": 2221091480,
      "ohlcv_available": true,
      "reason_included": "F&O stock; very high volume; power sector proxy",
      "reason_excluded": null
    },
    {
      "symbol": "PFC", "company_name": "Power Finance Corporation Ltd",
      "sector": "INFRA", "industry": "Infrastructure Finance",
      "yahoo_symbol": "PFC.NS", "kite_symbol": "PFC",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 363.00, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 9592260, "avg_turnover_20d": 3481990380,
      "ohlcv_available": true,
      "reason_included": "F&O stock; power sector lending PSU; high volume",
      "reason_excluded": null
    },
    {
      "symbol": "COALINDIA", "company_name": "Coal India Ltd",
      "sector": "INFRA", "industry": "Mining",
      "yahoo_symbol": "COALINDIA.NS", "kite_symbol": "COALINDIA",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 405.20, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 10327223, "avg_turnover_20d": 4184590750,
      "ohlcv_available": true,
      "reason_included": "Very high volume; dividend play; commodity proxy",
      "reason_excluded": null
    },
    {
      "symbol": "IDFCFIRSTB", "company_name": "IDFC First Bank Ltd",
      "sector": "BANK", "industry": "Private Bank",
      "yahoo_symbol": "IDFCFIRSTB.NS", "kite_symbol": "IDFCFIRSTB",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 86.75, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 12588998, "avg_turnover_20d": 1092095076,
      "ohlcv_available": true,
      "reason_included": "Very high volume private bank; F&O stock; retail favourite",
      "reason_excluded": null
    },
    {
      "symbol": "PNB", "company_name": "Punjab National Bank",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "PNB.NS", "kite_symbol": "PNB",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 116.55, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 14047780, "avg_turnover_20d": 1636768590,
      "ohlcv_available": true,
      "reason_included": "F&O stock; very high volume PSU bank; widely tracked",
      "reason_excluded": null
    },
    {
      "symbol": "CANBK", "company_name": "Canara Bank",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "CANBK.NS", "kite_symbol": "CANBK",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 129.96, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 8124111, "avg_turnover_20d": 1055987488,
      "ohlcv_available": true,
      "reason_included": "F&O stock; high volume PSU bank",
      "reason_excluded": null
    },
    {
      "symbol": "BANKINDIA", "company_name": "Bank of India",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "BANKINDIA.NS", "kite_symbol": "BANKINDIA",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 142.79, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 5333928, "avg_turnover_20d": 761513821,
      "ohlcv_available": true,
      "reason_included": "F&O stock; solid PSU bank volumes",
      "reason_excluded": null
    },
    {
      "symbol": "MAHABANK", "company_name": "Bank of Maharashtra",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "MAHABANK.NS", "kite_symbol": "MAHABANK",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 80.26, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 7790968, "avg_turnover_20d": 625269033,
      "ohlcv_available": true,
      "reason_included": "Good retail volumes; government-banking sensitive",
      "reason_excluded": null
    },
    {
      "symbol": "UNIONBANK", "company_name": "Union Bank of India",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "UNIONBANK.NS", "kite_symbol": "UNIONBANK",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 183.45, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 6916849, "avg_turnover_20d": 1268599331,
      "ohlcv_available": true,
      "reason_included": "F&O stock; solid PSU bank volumes",
      "reason_excluded": null
    },
    {
      "symbol": "BANKBARODA", "company_name": "Bank of Baroda",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "BANKBARODA.NS", "kite_symbol": "BANKBARODA",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 247.00, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 7914129, "avg_turnover_20d": 1954789863,
      "ohlcv_available": true,
      "reason_included": "F&O stock; very high volume PSU bank; widely covered",
      "reason_excluded": null
    },
    {
      "symbol": "KTKBANK", "company_name": "Karnataka Bank Ltd",
      "sector": "BANK", "industry": "Private Bank",
      "yahoo_symbol": "KTKBANK.NS", "kite_symbol": "KTKBANK",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 328.30, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 3431080, "avg_turnover_20d": 1125423544,
      "ohlcv_available": true,
      "reason_included": "South India private bank; decent volumes; Option B band",
      "reason_excluded": null
    },
    {
      "symbol": "FEDERALBNK", "company_name": "Federal Bank Ltd",
      "sector": "BANK", "industry": "Private Bank",
      "yahoo_symbol": "FEDERALBNK.NS", "kite_symbol": "FEDERALBNK",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": true, "last_ltp": 361.00, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": 4397811, "avg_turnover_20d": 1587609771,
      "ohlcv_available": true,
      "reason_included": "F&O stock; high quality private bank; solid volumes",
      "reason_excluded": null
    },
    {
      "symbol": "IOB", "company_name": "Indian Overseas Bank",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "IOB.NS", "kite_symbol": "IOB",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": false, "last_ltp": 33.0, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": null, "avg_turnover_20d": null,
      "ohlcv_available": true,
      "reason_included": null,
      "reason_excluded": "Excluded Phase 1B: very low absolute price (\u20b933); spread/slippage risk at 757 shares per \u20b925K cap"
    },
    {
      "symbol": "UCOBANK", "company_name": "UCO Bank",
      "sector": "BANK", "industry": "PSU Bank",
      "yahoo_symbol": "UCOBANK.NS", "kite_symbol": "UCOBANK",
      "instrument_token": null, "price_min": 20, "price_max": 500,
      "is_active": false, "last_ltp": 25.7, "last_ltp_source": "yfinance_close",
      "avg_volume_20d": null, "avg_turnover_20d": null,
      "ohlcv_available": true,
      "reason_included": null,
      "reason_excluded": "Excluded Phase 1B: very low absolute price (\u20b925.7); spread/slippage risk at 972 shares per \u20b925K cap"
    }
  ]
}' | python3 -m json.tool
