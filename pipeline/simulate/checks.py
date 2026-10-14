"""Data-integrity checks on the simulated SAP layer (TRD, Testing: data integrity).

Each check is a query that returns the number of violating rows; zero means pass.
"""

from __future__ import annotations

import datetime as dt

import duckdb

UNIQUE = {
    "EKKO": "EBELN", "EKPO": "EBELN, EBELP", "EKET": "EBELN, EBELP, ETENR", "VBAK": "VBELN",
    "VBAP": "VBELN, POSNR", "VBEP": "VBELN, POSNR, ETENR", "LIKP": "VBELN", "LIPS": "VBELN, POSNR",
    "VBRK": "VBELN", "VBRP": "VBELN, POSNR", "MATDOC": "MBLNR, MJAHR, ZEILE",
    "EKBE": "EBELN, EBELP, VGABE, GJAHR, BELNR, BUZEI", "VBFA": "VBELV, POSNV, VBELN, POSNN",
    "MARC": "MATNR, WERKS", "EINE": "INFNR, EKORG, WERKS",
}

CHECKS = {
    "every EKPO has an EKKO": "SELECT count(*) FROM EKPO LEFT JOIN EKKO USING (EBELN) WHERE EKKO.BEDAT IS NULL",
    "every EKPO has one EKET": "SELECT count(*) FROM EKPO LEFT JOIN EKET USING (EBELN, EBELP) WHERE EKET.EINDT IS NULL",
    "every VBAP has a VBAK": "SELECT count(*) FROM VBAP LEFT JOIN VBAK USING (VBELN) WHERE VBAK.ERDAT IS NULL",
    "every LIPS has its order line": """SELECT count(*) FROM LIPS LEFT JOIN VBAP ON VBAP.VBELN = LIPS.VGBEL
                                        AND VBAP.POSNR = LIPS.VGPOS WHERE VBAP.MATNR IS NULL""",
    "every VBRP has its delivery line": """SELECT count(*) FROM VBRP LEFT JOIN LIPS ON LIPS.VBELN = VBRP.VGBEL
                                           AND LIPS.POSNR = VBRP.VGPOS WHERE LIPS.MATNR IS NULL""",
    "every LIPS has a J flow": """SELECT count(*) FROM LIPS LEFT JOIN VBFA ON VBFA.VBELN = LIPS.VBELN
                                  AND VBFA.POSNN = LIPS.POSNR AND VBFA.VBTYP_N = 'J' WHERE VBFA.VBELV IS NULL""",
    "every VBRP has an M flow": """SELECT count(*) FROM VBRP LEFT JOIN VBFA ON VBFA.VBELN = VBRP.VBELN
                                   AND VBFA.POSNN = VBRP.POSNR AND VBFA.VBTYP_N = 'M' WHERE VBFA.VBELV IS NULL""",
    "no receipt before its PO date": """SELECT count(*) FROM MATDOC m JOIN EKKO k USING (EBELN)
                                        WHERE m.BWART = '101' AND m.BUDAT < k.BEDAT""",
    "received <= ordered": "SELECT count(*) FROM EKET WHERE WEMNG > MENGE",
    "delivered <= ordered": """SELECT count(*) FROM (SELECT VGBEL, VGPOS, sum(LFIMG) q FROM LIPS GROUP BY ALL) d
                               JOIN VBAP ON VBAP.VBELN = d.VGBEL AND VBAP.POSNR = d.VGPOS WHERE d.q > VBAP.KWMENG""",
    "EKET WEMNG matches MATDOC 101": """SELECT count(*) FROM EKET e LEFT JOIN (SELECT EBELN, EBELP, sum(MENGE) q
                                        FROM MATDOC WHERE BWART = '101' GROUP BY ALL) m USING (EBELN, EBELP)
                                        WHERE e.WEMNG <> coalesce(m.q, 0)""",
    "stock never negative": "SELECT count(*) FROM stock_daily WHERE closing_qty < 0",
    "stock_daily balances": """SELECT count(*) FROM stock_daily
                               WHERE closing_qty <> opening_qty + receipt_qty - issue_qty""",
    "stock_daily issues match MATDOC 601": """SELECT count(*) FROM (SELECT ds, matnr, werks, sum(issue_qty) q
                                              FROM stock_daily GROUP BY ALL) s
                                              FULL JOIN (SELECT BUDAT ds, MATNR matnr, WERKS werks, sum(MENGE) q
                                              FROM MATDOC WHERE BWART = '601' GROUP BY ALL) m USING (ds, matnr, werks)
                                              WHERE coalesce(s.q, 0) <> coalesce(m.q, 0)""",
    "MARD equals last closing stock": """SELECT count(*) FROM MARD JOIN stock_daily s ON s.matnr = MARD.MATNR
                                         AND s.werks = MARD.WERKS AND s.ds = (SELECT max(ds) FROM stock_daily)
                                         WHERE s.closing_qty <> MARD.LABST""",
}


def dated_after(end: dt.date) -> dict[str, str]:
    cols = {"EKKO": "BEDAT", "MATDOC": "BUDAT", "EKBE": "BUDAT", "VBAK": "ERDAT", "LIKP": "WADAT_IST",
            "VBRK": "FKDAT", "VBFA": "ERDAT", "change_log": "UDATE"}
    return {f"no {t} dated after {end}": f"SELECT count(*) FROM {t} WHERE {c} > DATE '{end}'" for t, c in cols.items()}


def run(con: duckdb.DuckDBPyConnection, end: dt.date) -> dict[str, int]:
    queries = {f"{t} keys unique": f"SELECT count(*) - count(DISTINCT ({k})) FROM {t}" for t, k in UNIQUE.items()}
    queries |= CHECKS | dated_after(end)
    return {name: con.execute(q).fetchone()[0] for name, q in queries.items()}


def assert_ok(con: duckdb.DuckDBPyConnection, end: dt.date) -> None:
    failed = {k: v for k, v in run(con, end).items() if v}
    if failed:
        raise AssertionError(f"integrity checks failed: {failed}")
