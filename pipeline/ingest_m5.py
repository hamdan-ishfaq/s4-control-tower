"""Stage 1: download M5 (cached), shift its calendar, pick the SKUs and write demand_daily.

M5 is downloaded at build time and never committed or re-hosted. Raw CSVs are read
straight into DuckDB; only the selected SKUs leave this stage.

Tables written:
  m5_calendar    one row per M5 day kept: ds (shifted), m5_date, wm_yr_wk, events, SNAP flags
  m5_customers   the 10 M5 stores as customers C01-C10 with their supplying plant
  sku_selection  top N items by 365-day unit sales across the configured categories
  demand_daily   selected item x store x day from each series' first sale: qty, sell_price, snap
  ingest_meta    shift and window facts used by later stages and ASSUMPTIONS.md
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb

M5_FILES = ["calendar.csv", "sell_prices.csv", "sales_train_evaluation.csv", "sales_test_evaluation.csv"]


def m5_dir(cfg: dict) -> Path:
    return cfg["paths"]["data_dir"] / "m5" / "datasets"


def download(cfg: dict) -> Path:
    """Fetch the M5 files through datasetsforecast unless they are already cached."""
    raw = m5_dir(cfg)
    if not all((raw / f).exists() for f in M5_FILES):
        from datasetsforecast.m5 import M5

        M5.download(str(cfg["paths"]["data_dir"]))
    return raw


def calendar_shift(last_m5_day: dt.date, today: dt.date) -> tuple[dt.date, int]:
    """Return (last M5 day kept, shift in days).

    The shift is a multiple of 7 so weekdays stay aligned. M5 ends on a Sunday and the
    demo's "today - 1" may not, so the last few M5 days are dropped until the weekday matches.
    """
    target = today - dt.timedelta(days=1)
    end = last_m5_day - dt.timedelta(days=(last_m5_day.weekday() - target.weekday()) % 7)
    shift = (target - end).days
    assert shift % 7 == 0 and shift > 0
    return end, shift


def customers(cfg: dict) -> list[tuple[str, str, str, str]]:
    """(kunnr, store_id, name1, werks), numbered in the order plants list their stores."""
    rows = []
    for werks, stores in cfg["plants"].items():
        for store in stores:
            rows.append((f"C{len(rows) + 1:02d}", store, f"Store {store.replace('_', '-')}", werks))
    return rows


def build(con: duckdb.DuckDBPyConnection, raw: Path, cfg: dict) -> None:
    f = {name: (raw / name).as_posix() for name in M5_FILES}
    cats = list(cfg["categories"])

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cal AS
        SELECT row_number() OVER (ORDER BY date) AS d_num, date::DATE AS m5_date, wm_yr_wk,
               event_name_1, event_type_1, event_name_2, event_type_2,
               snap_CA::BOOLEAN AS snap_ca, snap_TX::BOOLEAN AS snap_tx, snap_WI::BOOLEAN AS snap_wi
        FROM read_csv(?, header = true, nullstr = 'NA')
        """,
        [f["calendar.csv"]],
    )

    # Wide sales -> long, only the configured categories. The test file adds the last 28 days.
    parts = []
    for name in ["sales_train_evaluation.csv", "sales_test_evaluation.csv"]:
        parts.append(
            f"""
            SELECT * FROM (
                UNPIVOT (
                    SELECT item_id, dept_id, cat_id, store_id, COLUMNS('^d_[0-9]+$')
                    FROM read_csv('{f[name]}', header = true)
                    WHERE cat_id IN (SELECT unnest($cats))
                ) ON COLUMNS('^d_[0-9]+$') INTO NAME d VALUE qty
            )"""
        )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE sales AS
        SELECT s.item_id, s.dept_id, s.cat_id, s.store_id, c.m5_date, c.wm_yr_wk, s.qty::INTEGER AS qty
        FROM ({' UNION ALL '.join(parts)}) s
        JOIN cal c ON c.d_num = CAST(substr(s.d, 3) AS INTEGER)
        """,
        {"cats": cats},
    )

    last_m5_day = con.execute("SELECT max(m5_date) FROM sales").fetchone()[0]
    end, shift = calendar_shift(last_m5_day, cfg["today"])
    window_start = end - dt.timedelta(days=364)

    con.execute(
        "CREATE OR REPLACE TEMP TABLE prices AS SELECT store_id, item_id, wm_yr_wk, sell_price::DOUBLE AS sell_price "
        "FROM read_csv(?, header = true) WHERE split_part(item_id, '_', 1) IN (SELECT unnest(?))",
        [f["sell_prices.csv"], cats],
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE m5_calendar AS
        SELECT m5_date + CAST($shift AS INTEGER) AS ds, m5_date, wm_yr_wk,
               event_name_1, event_type_1, event_name_2, event_type_2, snap_ca, snap_tx, snap_wi
        FROM cal WHERE m5_date <= $end ORDER BY m5_date
        """,
        {"shift": shift, "end": end},
    )

    con.execute("CREATE OR REPLACE TABLE m5_customers (kunnr VARCHAR, store_id VARCHAR, name1 VARCHAR, werks VARCHAR)")
    con.executemany("INSERT INTO m5_customers VALUES (?, ?, ?, ?)", customers(cfg))

    # Top N items by units over the last 365 kept days, ties broken by item ID.
    con.execute(
        """
        CREATE OR REPLACE TABLE sku_selection AS
        WITH w AS (
            SELECT s.item_id, s.dept_id, s.cat_id, s.qty, p.sell_price
            FROM sales s
            LEFT JOIN prices p USING (store_id, item_id, wm_yr_wk)
            WHERE s.m5_date BETWEEN $start AND $end
        ), agg AS (
            SELECT item_id, dept_id, cat_id,
                   sum(qty) AS units_365,
                   round(sum(qty * sell_price), 2) AS revenue_365,
                   round(sum(qty * sell_price) / nullif(sum(qty), 0), 4) AS avg_sell_price
            FROM w GROUP BY ALL
        )
        SELECT row_number() OVER (ORDER BY units_365 DESC, item_id) AS rank,
               item_id AS matnr, dept_id, cat_id, units_365, revenue_365, avg_sell_price
        FROM agg
        QUALIFY rank <= $n
        ORDER BY rank
        """,
        {"start": window_start, "end": end, "n": int(cfg["skus"])},
    )

    # Daily demand per item and store, from each series' first sale (pre-launch zeros dropped).
    con.execute(
        """
        CREATE OR REPLACE TABLE demand_daily AS
        WITH s AS (
            SELECT s.*, max(s.qty > 0) OVER (PARTITION BY s.item_id, s.store_id ORDER BY s.m5_date) AS launched
            FROM sales s
            WHERE s.item_id IN (SELECT matnr FROM sku_selection) AND s.m5_date <= $end
        )
        SELECT c.ds, s.m5_date, s.item_id AS matnr, s.store_id, k.kunnr, k.werks, s.qty, p.sell_price,
               CASE split_part(s.store_id, '_', 1) WHEN 'CA' THEN c.snap_ca WHEN 'TX' THEN c.snap_tx ELSE c.snap_wi END AS snap
        FROM s
        JOIN m5_calendar c USING (m5_date)
        JOIN m5_customers k USING (store_id)
        LEFT JOIN prices p ON p.store_id = s.store_id AND p.item_id = s.item_id AND p.wm_yr_wk = s.wm_yr_wk
        WHERE s.launched
        ORDER BY s.item_id, k.kunnr, c.ds
        """,
        {"end": end},
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE ingest_meta AS
        SELECT $last::DATE AS m5_last_day, $end::DATE AS m5_last_day_kept, $shift::INTEGER AS shift_days,
               $start::DATE AS selection_window_start, $today::DATE AS today,
               (SELECT min(ds) FROM demand_daily) AS first_ds, (SELECT max(ds) FROM demand_daily) AS last_ds
        """,
        {"last": last_m5_day, "end": end, "shift": shift, "start": window_start, "today": cfg["today"]},
    )
    con.execute("DROP TABLE sales; DROP TABLE prices; DROP TABLE cal")


def mix_report(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Category and department mix of the selected SKUs: (cat, dept, skus, sku share, units share, revenue share)."""
    return con.execute(
        """
        WITH t AS (SELECT count(*) AS n, sum(units_365) AS u, sum(revenue_365) AS r FROM sku_selection)
        SELECT cat_id, coalesce(dept_id, '(all)') AS dept_id, count(*) AS skus,
               round(100.0 * count(*) / any_value(t.n), 1) AS sku_pct,
               round(100.0 * sum(units_365) / any_value(t.u), 1) AS units_pct,
               round(100.0 * sum(revenue_365) / any_value(t.r), 1) AS revenue_pct
        FROM sku_selection, t
        GROUP BY ROLLUP (cat_id, dept_id)
        HAVING cat_id IS NOT NULL
        ORDER BY cat_id, dept_id NULLS FIRST
        """
    ).fetchall()


def print_mix(con: duckdb.DuckDBPyConnection) -> None:
    meta = con.execute("SELECT m5_last_day, m5_last_day_kept, shift_days, first_ds, last_ds FROM ingest_meta").fetchone()
    print(f"M5 last day {meta[0]}, kept to {meta[1]}, shifted +{meta[2]} days -> demand {meta[3]} .. {meta[4]}")
    print(f"{'category':<10} {'dept':<12} {'SKUs':>5} {'SKU %':>6} {'units %':>8} {'revenue %':>10}")
    for cat, dept, n, sku_pct, units_pct, rev_pct in mix_report(con):
        label = cat if dept == "(all)" else ""
        dept = "" if dept == "(all)" else dept
        print(f"{label:<10} {dept:<12} {n:>5} {sku_pct:>6} {units_pct:>8} {rev_pct:>10}")


def run(cfg: dict) -> None:
    raw = download(cfg)
    db = cfg["paths"]["db"]
    db.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db)) as con:
        build(con, raw, cfg)
        print_mix(con)
