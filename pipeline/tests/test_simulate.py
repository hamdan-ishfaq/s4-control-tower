import datetime as dt
from statistics import NormalDist

import duckdb
import numpy as np
import pandas as pd
import pytest

from pipeline import simulate
from pipeline.config import load_config
from pipeline.simulate import checks, engine, masters

TODAY = dt.date(2026, 10, 14)


def synthetic_inputs(con: duckdb.DuckDBPyConnection) -> None:
    """12 SKUs in 3 departments, 3 stores over 2 plants, Poisson demand for 200 days."""
    rng = np.random.default_rng(7)
    items = [f"{d}_{i:03d}" for d in ["FOODS_1", "FOODS_2", "HOUSEHOLD_1"] for i in range(1, 5)]
    skus = pd.DataFrame({"rank": range(1, 13), "matnr": items, "dept_id": [m[:-4] for m in items],
                         "cat_id": [m.split("_")[0] for m in items], "units_365": 0, "revenue_365": 0.0,
                         "avg_sell_price": rng.uniform(1, 10, 12).round(2)})
    customers = pd.DataFrame({"kunnr": ["C01", "C02", "C03"], "store_id": ["CA_1", "TX_1", "WI_1"],
                              "name1": ["Store CA-1", "Store TX-1", "Store WI-1"], "werks": ["P001", "P002", "P002"]})
    days = pd.date_range(TODAY - dt.timedelta(days=200), TODAY - dt.timedelta(days=1)).date
    rows = [(d, m, k, int(rng.poisson(lam)), p)
            for m, lam, p in zip(items, rng.uniform(2, 30, 12), skus["avg_sell_price"])
            for k in customers["kunnr"] for d in days]
    demand = pd.DataFrame(rows, columns=["ds", "matnr", "kunnr", "qty", "sell_price"])
    for name, df in [("sku_selection", skus), ("m5_customers", customers), ("demand_daily", demand)]:
        con.register("v", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM v")
        con.unregister("v")


@pytest.fixture
def cfg():
    c = load_config()
    c.update(today=TODAY, vendors=6, plants={"P001": ["CA_1"], "P002": ["TX_1", "WI_1"]})
    c["simulation"] = {**c["simulation"], "history_days": 120}
    return c


@pytest.fixture
def con(cfg):
    con = duckdb.connect()
    synthetic_inputs(con)
    simulate.build(con, cfg)
    return con


def test_integrity_checks_pass(con):
    end = TODAY - dt.timedelta(days=1)
    assert {k: v for k, v in checks.run(con, end).items() if v} == {}


def test_same_seed_same_tables(cfg, con):
    other = duckdb.connect()
    synthetic_inputs(other)
    simulate.build(other, cfg)
    for table in simulate.KEYS:
        q = f'SELECT * FROM "{table}"'
        assert con.execute(q).fetchall() == other.execute(q).fetchall(), table


def test_vendor_counts_reach_25_over_5_departments():
    depts = pd.Series({"FOODS_1": 41, "FOODS_2": 79, "FOODS_3": 251, "HOUSEHOLD_1": 121, "HOUSEHOLD_2": 8})
    counts = masters.vendor_counts(depts, 25)
    assert sum(counts.values()) == 25 and min(counts.values()) >= 2
    assert counts["FOODS_3"] == max(counts.values())


def test_lead_time_multiplier_hits_on_time_probability():
    lead, cv, p = 10, 0.3, 0.92
    mu, sigma = engine.lognormal_params(lead, cv, p)
    assert NormalDist(mu, sigma).cdf(np.log((lead + 1) / lead)) == pytest.approx(p)


def test_po_lines_whole_cases_and_vendor_minimum(con):
    bad_pack = con.execute("""SELECT count(*) FROM EKPO JOIN MARC USING (MATNR, WERKS)
                              WHERE MENGE % BSTRF <> 0""").fetchone()[0]
    below_min = con.execute("""SELECT count(*) FROM (SELECT EBELN, sum(MENGE * NETPR) v FROM EKPO GROUP BY 1) p
                               JOIN EKKO USING (EBELN) JOIN LFM1 USING (LIFNR) WHERE p.v < LFM1.MINBW - 1e-6""").fetchone()[0]
    eindt = con.execute("""SELECT count(*) FROM EKET JOIN EKKO USING (EBELN) JOIN EKPO USING (EBELN, EBELP)
                           JOIN EINA USING (MATNR) JOIN EINE ON EINE.INFNR = EINA.INFNR AND EINE.WERKS = EKPO.WERKS
                           WHERE EKET.EINDT <> EKKO.BEDAT + CAST(EINE.APLFZ AS INTEGER)""").fetchone()[0]
    assert (bad_pack, below_min, eindt) == (0, 0, 0)


def test_order_quantity_is_demand_since_previous_order(con):
    mismatched = con.execute("""
        WITH o AS (SELECT VBELN, KUNNR, ERDAT, lag(ERDAT) OVER (PARTITION BY KUNNR ORDER BY ERDAT) AS prev FROM VBAK),
        so AS (SELECT o.KUNNR, o.ERDAT, o.prev, VBAP.MATNR, VBAP.KWMENG FROM o JOIN VBAP USING (VBELN) WHERE prev IS NOT NULL)
        SELECT count(*) FROM so
        WHERE KWMENG <> (SELECT sum(qty) FROM demand_daily d
                         WHERE d.kunnr = so.KUNNR AND d.matnr = so.MATNR AND d.ds > so.prev AND d.ds <= so.ERDAT)
    """).fetchone()[0]
    assert mismatched == 0


def test_documents_have_sap_number_ranges(con):
    prefixes = con.execute("""SELECT (SELECT bool_and(EBELN LIKE '45%') FROM EKKO), (SELECT bool_and(MBLNR LIKE '49%') FROM MATDOC),
                                     (SELECT bool_and(VBELN LIKE '80%') FROM LIKP), (SELECT bool_and(VBELN LIKE '90%') FROM VBRK)""").fetchone()
    assert all(prefixes)
