"""Load the DKeX daily reports into DuckDB (data/dkex/dkex.duckdb): trades (time & sales), settlements, daily market rows,
and a per-contract table joining settlement, name and league/market-type parsed from the symbol.
Timestamps are Eastern (the reports say EDT/EST; DuckDB does not know those names, so they are stripped and kept naive)."""
import os, time, duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "dkex")
DB = os.path.join(DATA, "dkex.duckdb")
ET = lambda col: f"strptime(replace(replace({col}, ' EDT', ''), ' EST', ''), '%m/%d/%y %I:%M %p')"


def main():
    t0 = time.time()
    con = duckdb.connect(DB)
    con.execute("PRAGMA threads=8")
    raw = os.path.join(DATA, "raw")
    con.execute(f"""CREATE OR REPLACE TABLE trades AS
SELECT CAST("Business Date" AS INTEGER) AS bdate, Symbol AS symbol, {ET('"Transaction Date and Time"')} AS ts,
       CAST(replace("Last Price (USD)", '$', '') AS DOUBLE) AS price, CAST("Last Quantity" AS BIGINT) AS qty, filename AS src
FROM read_csv('{raw}/time-and-sales_*.csv', header=true, filename=true, all_varchar=true, union_by_name=true)""")
    print("trades", con.execute("select count(*), sum(qty), min(bdate), max(bdate) from trades").fetchall(), round(time.time() - t0))
    con.execute(f"""CREATE OR REPLACE TABLE settlements AS
SELECT "Market Name" AS name, Ticker AS symbol, Status AS status, "Date and Time of Settlement (ET)" AS settle_ts_raw,
       CAST(replace("Price (USD)", '$', '') AS DOUBLE) AS settle, filename AS src
FROM read_csv('{raw}/daily-settlement_*.csv', header=true, filename=true, all_varchar=true, union_by_name=true)""")
    print("settlements", con.execute("select count(*), count(distinct symbol) from settlements").fetchall(), round(time.time() - t0))
    con.execute(f"""CREATE OR REPLACE TABLE daily AS
SELECT CAST("Business Date" AS INTEGER) AS bdate, Symbol AS symbol, Status AS status, CAST("Open Interest" AS BIGINT) AS oi,
       CAST("Trade Volume" AS BIGINT) AS vol, CAST(replace("High Price (USD)", '$', '') AS DOUBLE) AS high,
       CAST(replace("Low Price (USD)", '$', '') AS DOUBLE) AS low, CAST(replace("Settlement/Last Trade Price (USD)", '$', '') AS DOUBLE) AS last,
       "Maturity Date and Time (ET)" AS maturity_raw
FROM read_csv('{raw}/daily-market_*.csv', header=true, filename=true, all_varchar=true, union_by_name=true)""")
    print("daily", con.execute("select count(*), count(distinct symbol) from daily").fetchall(), round(time.time() - t0))
    con.execute("""CREATE OR REPLACE TABLE contracts AS
WITH s AS (SELECT symbol, arg_max(settle, src) AS settle, arg_max(name, src) AS name, arg_max(settle_ts_raw, src) AS settle_ts_raw FROM settlements GROUP BY symbol),
     m AS (SELECT symbol, min(maturity_raw) AS maturity_raw, max(oi) AS max_oi, sum(vol) AS total_vol, min(bdate) AS first_listed FROM daily GROUP BY symbol)
SELECT coalesce(s.symbol, m.symbol) AS symbol, s.settle, s.name, s.settle_ts_raw,
       try_strptime(replace(replace(s.settle_ts_raw, ' EDT', ''), ' EST', ''), '%m/%d/%y %I:%M:%S.%f %p') AS settle_ts,
       m.maturity_raw, m.max_oi, m.total_vol, m.first_listed,
       split_part(coalesce(s.symbol, m.symbol), '-', 1) AS league, split_part(coalesce(s.symbol, m.symbol), '-', 2) AS mtype,
       split_part(coalesce(s.symbol, m.symbol), '-', 3) AS period,
       CASE WHEN s.name IS NULL THEN NULL ELSE (length(s.name) - length(replace(s.name, ' / ', ''))) / 3 + 1 END AS legs
FROM s FULL OUTER JOIN m ON s.symbol = m.symbol""")
    print("contracts", con.execute("select count(*), count(settle), count(settle_ts) from contracts").fetchall(), round(time.time() - t0))
    con.close()


if __name__ == "__main__":
    main()
