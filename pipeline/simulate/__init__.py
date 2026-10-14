"""Stage 2: simulate the SAP layer from demand_daily (TRD, Simulation algorithm).

Reads sku_selection, m5_customers and demand_daily from DuckDB; writes the SAP tables, stock_daily
and change_log (dated header/item field changes, modelled on CDHDR/CDPOS, so snapshots can see
what a block, rejection or completion flag looked like on any day).
"""

from __future__ import annotations

import datetime as dt

import duckdb
import numpy as np
import pandas as pd

from pipeline.simulate import checks, engine, masters

# Sort keys so table bytes do not depend on insertion order.
KEYS = {
    "T001W": "WERKS", "MARA": "MATNR", "MARC": "MATNR, WERKS", "MARM": "MATNR, MEINH", "MARD": "MATNR, WERKS, LGORT",
    "MBEW": "MATNR, BWKEY", "LFA1": "LIFNR", "LFM1": "LIFNR, EKORG", "EINA": "INFNR", "EINE": "INFNR, EKORG, WERKS",
    "KNA1": "KUNNR", "EKKO": "EBELN", "EKPO": "EBELN, EBELP", "EKET": "EBELN, EBELP, ETENR",
    "EKBE": "EBELN, EBELP, VGABE, GJAHR, BELNR, BUZEI", "MATDOC": "MBLNR, MJAHR, ZEILE", "VBAK": "VBELN",
    "VBAP": "VBELN, POSNR", "VBEP": "VBELN, POSNR, ETENR", "LIKP": "VBELN", "LIPS": "VBELN, POSNR",
    "VBRK": "VBELN", "VBRP": "VBELN, POSNR", "VBFA": "VBELV, POSNV, VBELN, POSNN",
    "change_log": "UDATE, TABNAME, TABKEY, FNAME, VALUE_NEW", "stock_daily": "ds, matnr, werks",
}


def window(cfg: dict) -> tuple[dt.date, dt.date]:
    end = cfg["today"] - dt.timedelta(days=1)
    return end - dt.timedelta(days=cfg["simulation"]["history_days"] - 1), end


def load_inputs(con: duckdb.DuckDBPyConnection, cfg: dict):
    start, end = window(cfg)
    skus = con.execute("SELECT matnr, dept_id, cat_id, avg_sell_price FROM sku_selection ORDER BY matnr").df()
    customers = con.execute("SELECT kunnr, store_id, name1, werks FROM m5_customers ORDER BY kunnr").df()
    first = start - dt.timedelta(days=engine.PRE_DAYS)
    dem = con.execute(
        "SELECT kunnr, matnr, ds, qty, sell_price FROM demand_daily WHERE ds BETWEEN ? AND ?", [first, end]
    ).df()
    n_days = (end - first).days + 1
    c = dem["kunnr"].map({k: i for i, k in enumerate(customers["kunnr"])}).to_numpy()
    s = dem["matnr"].map({m: i for i, m in enumerate(skus["matnr"])}).to_numpy()
    d = (pd.to_datetime(dem["ds"]) - pd.Timestamp(first)).dt.days.to_numpy()
    qty = np.zeros((len(customers), len(skus), n_days), dtype=np.int64)
    price = np.full(qty.shape, np.nan)
    qty[c, s, d] = dem["qty"].to_numpy()
    price[c, s, d] = dem["sell_price"].to_numpy()
    return skus, customers, qty, price, start, end


def build(con: duckdb.DuckDBPyConnection, cfg: dict) -> dict[str, pd.DataFrame]:
    skus, customers, qty, price, start, end = load_inputs(con, cfg)
    m = masters.build(cfg, skus, customers)
    tables = {**m["tables"], **engine.run(cfg, m, qty, price, start, end)}
    for name, df in tables.items():
        con.register("df_view", df)
        con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM df_view ORDER BY {KEYS[name]}')
        con.unregister("df_view")
    # Planning helpers the later stages need but SAP does not hold in one place.
    for name, df in [("sim_vendor_params", m["vendor"]), ("sim_customer_orders", customers_frame(m["customers"]))]:
        con.register("df_view", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df_view")
        con.unregister("df_view")
    return tables


def customers_frame(cust: pd.DataFrame) -> pd.DataFrame:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return pd.DataFrame({"kunnr": cust["kunnr"], "werks": cust["werks"],
                         "order_weekdays": ["/".join(days[d] for d in w) for w in cust["order_weekdays"]]})


def run(cfg: dict) -> None:
    with duckdb.connect(str(cfg["paths"]["db"])) as con:
        build(con, cfg)
        checks.assert_ok(con, window(cfg)[1])
        for table in ["EKKO", "EKPO", "MATDOC", "VBAK", "VBAP", "LIKP", "VBRK", "stock_daily"]:
            print(f"{table:<12} {con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:>10,}")
