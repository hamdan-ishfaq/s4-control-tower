import datetime as dt

import duckdb
import pytest

from pipeline import ingest_m5

START = dt.date(2016, 5, 30)  # Monday; 21 days to Sunday 2016-06-19, like real M5's last day
DAYS = 21
TODAY = dt.date(2026, 10, 14)  # Wednesday
STORES = ["CA_1", "TX_1"]


def daily_units(item: str, store: str, day: int) -> int:
    if item == "HOBBIES_1_001":
        return 100  # largest seller, but not in the configured categories
    if item == "HOUSEHOLD_1_001":
        return 0 if store == "CA_1" and day < 3 else 10  # launches late at CA_1
    if item == "FOODS_1_001":
        return 5
    return 1  # FOODS_1_002


@pytest.fixture
def m5(tmp_path):
    raw = tmp_path / "data" / "m5" / "datasets"
    raw.mkdir(parents=True)
    days = [START + dt.timedelta(days=i) for i in range(DAYS)]
    week = {d: 11600 + (i + 2) // 7 for i, d in enumerate(days)}

    cal = ['"date","wm_yr_wk","weekday","wday","month","year","event_name_1","event_type_1",'
           '"event_name_2","event_type_2","snap_CA","snap_TX","snap_WI"']
    for i, d in enumerate(days):
        cal.append(f"{d},{week[d]},x,1,{d.month},{d.year},NA,NA,NA,NA,{int(i % 2 == 0)},0,0")
    (raw / "calendar.csv").write_text("\n".join(cal) + "\n", encoding="utf-8")

    items = ["FOODS_1_001", "FOODS_1_002", "HOUSEHOLD_1_001", "HOBBIES_1_001"]
    prices = ['"store_id","item_id","wm_yr_wk","sell_price"']
    prices += [f"{s},{it},{w},2.5" for s in STORES for it in items for w in sorted(set(week.values()))]
    (raw / "sell_prices.csv").write_text("\n".join(prices) + "\n", encoding="utf-8")

    def sales(name, lo, hi):
        head = "item_id,dept_id,cat_id,store_id,state_id," + ",".join(f"d_{i + 1}" for i in range(lo, hi))
        rows = [head]
        for it in items:
            for s in STORES:
                vals = ",".join(str(daily_units(it, s, i)) for i in range(lo, hi))
                rows.append(f"{it},{it.rsplit('_', 1)[0]},{it.split('_')[0]},{s},{s[:2]},{vals}")
        (raw / name).write_text("\n".join(rows) + "\n", encoding="utf-8")

    sales("sales_train_evaluation.csv", 0, 14)
    sales("sales_test_evaluation.csv", 14, DAYS)

    cfg = {
        "today": TODAY,
        "skus": 2,
        "categories": ["FOODS", "HOUSEHOLD"],
        "plants": {"P001": ["CA_1"], "P002": ["TX_1"]},
        "paths": {"data_dir": tmp_path / "data", "db": tmp_path / "data" / "test.duckdb"},
    }
    return raw, cfg


def build(raw, cfg):
    con = duckdb.connect()
    ingest_m5.build(con, raw, cfg)
    return con


def test_calendar_shift_keeps_weekdays_and_ends_day_before_today():
    end, shift = ingest_m5.calendar_shift(dt.date(2016, 6, 19), TODAY)
    assert end == dt.date(2016, 6, 14)
    assert shift % 7 == 0
    assert end + dt.timedelta(days=shift) == TODAY - dt.timedelta(days=1)


def test_calendar_shift_no_trim_when_weekdays_match():
    end, shift = ingest_m5.calendar_shift(dt.date(2016, 6, 14), TODAY)
    assert end == dt.date(2016, 6, 14) and shift == 3773


def test_customers_follow_plant_order():
    cfg = {"plants": {"P001": ["CA_1", "CA_2"], "P002": ["TX_1"]}}
    assert ingest_m5.customers(cfg) == [
        ("C01", "CA_1", "Store CA-1", "P001"),
        ("C02", "CA_2", "Store CA-2", "P001"),
        ("C03", "TX_1", "Store TX-1", "P002"),
    ]


def test_selection_is_top_units_in_configured_categories(m5):
    con = build(*m5)
    assert con.execute("SELECT matnr FROM sku_selection ORDER BY rank").fetchall() == [
        ("HOUSEHOLD_1_001",),
        ("FOODS_1_001",),
    ]


def test_demand_daily_shape(m5):
    con = build(*m5)
    last, misaligned, no_price = con.execute(
        "SELECT max(ds), count(*) FILTER (WHERE dayofweek(ds) <> dayofweek(m5_date)), "
        "count(*) FILTER (WHERE sell_price IS NULL) FROM demand_daily"
    ).fetchone()
    assert last == TODAY - dt.timedelta(days=1)
    assert misaligned == 0 and no_price == 0
    # 16 days kept (to Tuesday 2016-06-14); HOUSEHOLD at CA_1 loses its 3 pre-launch days.
    counts = dict(con.execute("SELECT matnr || '@' || kunnr, count(*) FROM demand_daily GROUP BY 1").fetchall())
    assert counts == {"FOODS_1_001@C01": 16, "FOODS_1_001@C02": 16, "HOUSEHOLD_1_001@C01": 13, "HOUSEHOLD_1_001@C02": 16}
    assert con.execute("SELECT DISTINCT kunnr, werks FROM demand_daily ORDER BY 1").fetchall() == [
        ("C01", "P001"),
        ("C02", "P002"),
    ]


def test_build_is_deterministic(m5):
    q = "SELECT * FROM demand_daily ORDER BY matnr, kunnr, ds"
    assert build(*m5).execute(q).fetchall() == build(*m5).execute(q).fetchall()
