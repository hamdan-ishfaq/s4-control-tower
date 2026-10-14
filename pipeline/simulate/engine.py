"""Steps 5-10 of the simulation: one pass over the last 365 days, posting SAP documents day by day.

Order of events each day: receipts, invoices, new sales orders, deliveries (oldest due line first),
rejections of short lines, billing, purchasing (legacy weekly policy), end-of-day stock.
Nothing dated after the last day (today - 1) is posted: later receipts and billings stay open.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

from pipeline.simulate.masters import (EKORG, LGORT, TAG_BILLING, TAG_INVOICE, TAG_ORDERS, TAG_PO,
                                       VKORG, rng_for)

PRE_DAYS = 28  # demand history needed before the first simulated day


@dataclass(slots=True)
class SoLine:
    vbeln: str
    posnr: str
    kunnr: str
    s: int  # SKU index
    p: int  # plant index
    edatu: dt.date
    price: float
    open_qty: int
    delivered: int = 0
    block_until: dt.date | None = None  # delivery block active before this date


@dataclass(slots=True)
class PoLine:
    ebeln: str
    ebelp: str
    s: int
    p: int
    v: int
    menge: int
    netpr: float
    eindt: dt.date
    received: int = 0
    closed: bool = False


@dataclass
class Docs:
    """Row buffers for every table the engine writes."""
    rows: dict[str, list] = field(default_factory=lambda: defaultdict(list))
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def next(self, prefix: str) -> str:
        self.counters[prefix] += 1
        return f"{prefix}{self.counters[prefix]:08d}"

    def add(self, table: str, row: tuple) -> None:
        self.rows[table].append(row)


def lognormal_params(lead: int, cv: float, on_time: float) -> tuple[float, float]:
    """mu, sigma of the lead-time multiplier so that P(lead * m <= lead + 1) = on_time."""
    sigma = math.sqrt(math.log(1 + cv * cv))
    mu = math.log((lead + 1) / lead) - sigma * NormalDist().inv_cdf(on_time)
    return mu, sigma


def on_time_at(vendor: pd.Series, eindt: dt.date, end: dt.date, deg: dict) -> float:
    base = vendor["on_time_prob"]
    if vendor["degrade"] == "gradual":
        start = end - dt.timedelta(days=deg["gradual_days"])
        frac = min(max((eindt - start).days / deg["gradual_days"], 0.0), 1.0)
        return base + (deg["gradual_end_on_time"] - base) * frac
    if vendor["degrade"] == "sudden" and eindt > end - dt.timedelta(days=deg["sudden_days"]):
        return deg["sudden_on_time"]
    return base


def run(cfg: dict, m: dict, qty: np.ndarray, price: np.ndarray, start: dt.date, end: dt.date) -> dict[str, pd.DataFrame]:
    """qty and price are [customer, sku, day] arrays; day 0 is `start - PRE_DAYS`."""
    seed, sim = cfg["seed"], cfg["simulation"]
    sku, vendor, cust = m["sku"], m["vendor"], m["customers"]
    plants = list(cfg["plants"])
    plant_of_cust = [plants.index(w) for w in cust["werks"]]
    n_sku, n_days = len(sku), (end - start).days + 1
    matnr = sku["matnr"].tolist()
    pack = sku["case_pack"].to_numpy()
    cost = sku["cost"].to_numpy()
    vidx = {l: i for i, l in enumerate(vendor["lifnr"])}
    sku_vendor = np.array([vidx[l] for l in sku["lifnr"]])
    skus_of_vendor = [np.flatnonzero(sku_vendor == v) for v in range(len(vendor))]
    vcfg, deg, legacy = sim["vendor"], sim["vendor"]["degrading"], sim["legacy_policy"]

    # Plant demand (M5 units summed over the plant's stores), used by the legacy policy and opening stock.
    plant_qty = np.zeros((len(plants), n_sku, qty.shape[2]), dtype=np.int64)
    for c, p in enumerate(plant_of_cust):
        plant_qty[p] += qty[c]
    stock = np.rint(plant_qty[:, :, PRE_DAYS - 28:PRE_DAYS].mean(axis=2) * sim["start_stock_days"]).astype(np.int64)

    docs = Docs()
    queue: dict[tuple[int, int], list[SoLine]] = defaultdict(list)
    po_lines: list[PoLine] = []
    open_po: dict[tuple[int, int], list[PoLine]] = defaultdict(list)
    vbap_row: dict[tuple[str, str], list] = {}
    receipts: dict[dt.date, list[tuple[PoLine, int, bool]]] = defaultdict(list)
    invoices: dict[dt.date, list[tuple[str, list[tuple[PoLine, int, str]]]]] = defaultdict(list)
    billing: dict[dt.date, list[tuple[str, str, list]]] = defaultdict(list)
    shape = (len(plants), n_sku, n_days)
    opening, rec_q, iss_q, rej_q, closing = (np.zeros(shape, dtype=np.int64) for _ in range(5))
    last_order = {k: None for k in cust["kunnr"]}

    for ti in range(n_days):
        t = start + dt.timedelta(days=ti)
        di = ti + PRE_DAYS  # index into the demand arrays
        opening[:, :, ti] = stock

        # 1. Goods receipts (MATDOC 101, EKBE type 1), one material document per PO and day.
        by_po: dict[str, list] = defaultdict(list)
        for line, q, last in receipts.pop(t, []):
            by_po[line.ebeln].append((line, q, last))
        for ebeln in sorted(by_po):
            mblnr, items = docs.next("49"), []
            for z, (line, q, last) in enumerate(by_po[ebeln], start=1):
                zeile = f"{z:04d}"
                stock[line.p, line.s] += q
                rec_q[line.p, line.s, ti] += q
                line.received += q
                docs.add("MATDOC", (mblnr, str(t.year), zeile, "101", matnr[line.s], plants[line.p], LGORT,
                                    q, "S", t, line.ebeln, line.ebelp, None))
                docs.add("EKBE", (line.ebeln, line.ebelp, "1", str(t.year), mblnr, zeile, "101", t, q,
                                  round(q * line.netpr, 2)))
                if last:
                    line.closed = True
                    docs.add("change_log", ("EKPO", f"{line.ebeln}{line.ebelp}", "ELIKZ", "", "X", t))
                items.append((line, q, zeile))
            r = rng_for(seed, TAG_INVOICE, int(mblnr))
            inv_day = t + dt.timedelta(days=int(r.integers(vcfg["invoice_days"][0], vcfg["invoice_days"][1] + 1)))
            invoices[inv_day].append((mblnr, items))

        # 2. Invoices (EKBE type 2) at the PO price times the vendor's drift.
        for mblnr, items in invoices.pop(t, []):
            belnr = docs.next("51")
            r = rng_for(seed, TAG_INVOICE, int(mblnr), 1)
            for line, q, zeile in items:
                drift = vendor.at[line.v, "invoice_drift"] + r.normal(0, 0.005)
                docs.add("EKBE", (line.ebeln, line.ebelp, "2", str(t.year), belnr, zeile, None, t, q,
                                  round(q * line.netpr * (1 + drift), 2)))

        # 3. Sales orders: each customer on its two weekdays, for the units sold since its last order.
        for c, row in cust.iterrows():
            if t.weekday() not in row["order_weekdays"]:
                continue
            prev = last_order[row["kunnr"]] or max(d for d in (t - dt.timedelta(days=k) for k in range(1, 8))
                                                  if d.weekday() in row["order_weekdays"])
            last_order[row["kunnr"]] = t
            lo = di - (t - prev).days + 1
            q = qty[c, :, lo:di + 1].sum(axis=1)
            if not q.any():
                continue
            vbeln = f"{docs.counters['so'] + 10000001:010d}"
            docs.counters["so"] += 1
            r = rng_for(seed, TAG_ORDERS, int(vbeln))
            block_until = None
            if r.random() < sim["delivery_block_rate"]:
                k = int(r.integers(sim["delivery_block_days"][0], sim["delivery_block_days"][1] + 1))
                block_until = t + dt.timedelta(days=k)
                docs.add("change_log", ("VBAK", vbeln, "LIFSK", "", "01", t))
                if block_until <= end:
                    docs.add("change_log", ("VBAK", vbeln, "LIFSK", "01", "", block_until))
            p = plant_of_cust[c]
            edatu = t + dt.timedelta(days=sim["requested_after_days"])
            lifsk = "01" if block_until and block_until > end else ""
            docs.add("VBAK", (vbeln, "OR", row["kunnr"], t, VKORG, lifsk, ""))
            for k, s in enumerate(np.flatnonzero(q), start=1):
                posnr = f"{k * 10:06d}"
                pr = float(price[c, s, di]) if not np.isnan(price[c, s, di]) else float(sku.at[s, "avg_sell_price"])
                line = SoLine(vbeln, posnr, row["kunnr"], int(s), p, edatu, pr, int(q[s]), block_until=block_until)
                queue[(p, int(s))].append(line)
                item = [vbeln, posnr, matnr[s], plants[p], int(q[s]), round(int(q[s]) * pr, 2), ""]
                docs.add("VBAP", item)
                vbap_row[(vbeln, posnr)] = item
                docs.add("VBEP", (vbeln, posnr, "0001", edatu, int(q[s]), int(q[s])))

        # 4. Deliveries: allocate stock to due, unblocked lines, oldest first; then reject stale short lines.
        picked: dict[str, list[tuple[SoLine, int]]] = defaultdict(list)
        rejected: list[SoLine] = []
        for key in sorted(queue):
            lines, keep = queue[key], []
            for line in lines:
                if line.edatu <= t and not (line.block_until and line.block_until > t) and stock[key] > 0:
                    q = min(line.open_qty, int(stock[key]))
                    stock[key] -= q
                    iss_q[key[0], key[1], ti] += q
                    line.open_qty -= q
                    line.delivered += q
                    picked[line.vbeln].append((line, q))
                if line.open_qty > 0 and (t - line.edatu).days >= sim["short_line_open_days"]:
                    rejected.append(line)
                elif line.open_qty > 0:
                    keep.append(line)
            queue[key] = keep
        for line in rejected:
            rej_q[line.p, line.s, ti] += line.open_qty
            docs.add("change_log", ("VBAP", f"{line.vbeln}{line.posnr}", "ABGRU", "", "02", t))
            vbap_row[(line.vbeln, line.posnr)][6] = "02"

        for vbeln in sorted(picked):
            dlv, mblnr = docs.next("80"), docs.next("49")
            kunnr = picked[vbeln][0][0].kunnr
            docs.add("LIKP", (dlv, t, t, kunnr, ""))
            items = []
            for k, (line, q) in enumerate(picked[vbeln], start=1):
                posnr = f"{k * 10:06d}"
                docs.add("LIPS", (dlv, posnr, line.vbeln, line.posnr, matnr[line.s], plants[line.p], q))
                docs.add("MATDOC", (mblnr, str(t.year), f"{k:04d}", "601", matnr[line.s], plants[line.p], LGORT,
                                    q, "H", t, None, None, dlv))
                docs.add("VBFA", (line.vbeln, line.posnr, dlv, posnr, "J", t))
                items.append((posnr, line, q))
            r = rng_for(seed, TAG_BILLING, int(dlv))
            delay = 1
            if r.random() < sim["billing_delay_rate"]:
                delay += int(r.integers(sim["billing_delay_days"][0], sim["billing_delay_days"][1] + 1))
            billing[t + dt.timedelta(days=delay)].append((dlv, kunnr, items))

        # 5. Billing (VBRK/VBRP) one day after goods issue, or later for the delayed ones.
        for dlv, kunnr, items in billing.pop(t, []):
            inv = docs.next("90")
            total = 0.0
            for posnr, line, q in items:
                net = round(q * line.price, 2)
                total += net
                docs.add("VBRP", (inv, posnr, dlv, posnr, matnr[line.s], q, net))
                docs.add("VBFA", (dlv, posnr, inv, posnr, "M", t))
            docs.add("VBRK", (inv, "F2", t, kunnr, round(total, 2)))

        # 6. Purchasing with the legacy policy: weekly review, order-up-to with no variability buffer.
        for v in range(len(vendor)):
            if vendor.at[v, "review_weekday"] != t.weekday():
                continue
            lead = int(vendor.at[v, "lead_days"])
            for p in range(len(plants)):
                lines = []
                for s in skus_of_vendor[v]:
                    avg = plant_qty[p, s, di - legacy["avg_days"]:di].mean()
                    out = avg * (lead + legacy["extra_cover_days"]) * legacy["factor"]
                    on_order = sum(l.menge - l.received for l in open_po[(p, s)])
                    gap = out - stock[p, s] - on_order
                    if gap > 0:
                        lines.append([int(s), math.ceil(gap / pack[s])])
                if not lines:
                    continue
                value = sum(cs * pack[s] * cost[s] for s, cs in lines)
                i = 0
                while value < vendor.at[v, "min_order_value"]:  # top up whole cases to the vendor minimum
                    s = lines[i % len(lines)][0]
                    lines[i % len(lines)][1] += 1
                    value += pack[s] * cost[s]
                    i += 1
                place_po(docs, cfg, t, end, v, p, lines, vendor, sku, plants, po_lines, receipts, open_po)

        # 7. End-of-day stock.
        closing[:, :, ti] = stock
        for key, lines in list(open_po.items()):
            open_po[key] = [l for l in lines if not l.closed]

    stock_daily = (opening, rec_q, iss_q, rej_q, closing)
    return frames(docs, sku, plants, start, stock, stock_daily, po_lines)


def place_po(docs: Docs, cfg: dict, t: dt.date, end: dt.date, v: int, p: int, lines: list, vendor: pd.DataFrame,
             sku: pd.DataFrame, plants: list[str], po_lines: list[PoLine], receipts: dict, open_po: dict) -> None:
    """Write EKKO and plan the receipts. The whole PO travels on one truck; short lines vary per line."""
    vcfg = cfg["simulation"]["vendor"]
    vrow = vendor.loc[v]
    lead = int(vrow["lead_days"])
    eindt = t + dt.timedelta(days=lead)
    ebeln = docs.next("45")
    docs.add("EKKO", (ebeln, "NB", vrow["lifnr"], EKORG, t))

    # Keyed by vendor, plant and day so a replay with another policy sees the same vendor behaviour.
    r = rng_for(cfg["seed"], TAG_PO, v, p, t.toordinal())
    mu, sigma = lognormal_params(lead, float(vrow["lead_cv"]), on_time_at(vrow, eindt, end, vcfg["degrading"]))
    days = max(1, round(lead * 0.75), round(lead * math.exp(mu + sigma * r.standard_normal())))
    arrival = t + dt.timedelta(days=days)

    for k, (s, cases) in enumerate(sorted(lines), start=1):
        pack = int(sku.at[s, "case_pack"])
        line = PoLine(ebeln, f"{k * 10:05d}", s, p, v, cases * pack, float(sku.at[s, "cost"]), eindt)
        po_lines.append(line)
        open_po[(p, s)].append(line)
        if r.random() < vrow["full_prob"] or cases == 1:
            receipts[arrival].append((line, line.menge, True))
            continue
        frac = r.uniform(*vcfg["short_fraction"])
        first = min(max(1, int(cases * frac)), cases - 1) * pack
        later = r.random() < vcfg["rest_later_prob"]
        delay = int(r.integers(vcfg["rest_delay_days"][0], vcfg["rest_delay_days"][1] + 1))
        receipts[arrival].append((line, first, not later))
        if later:
            receipts[arrival + dt.timedelta(days=delay)].append((line, line.menge - first, True))


COLUMNS = {
    "EKKO": ["EBELN", "BSART", "LIFNR", "EKORG", "BEDAT"],
    "EKBE": ["EBELN", "EBELP", "VGABE", "GJAHR", "BELNR", "BUZEI", "BWART", "BUDAT", "MENGE", "DMBTR"],
    "MATDOC": ["MBLNR", "MJAHR", "ZEILE", "BWART", "MATNR", "WERKS", "LGORT", "MENGE", "SHKZG", "BUDAT",
               "EBELN", "EBELP", "VBELN_IM"],
    "VBAK": ["VBELN", "AUART", "KUNNR", "ERDAT", "VKORG", "LIFSK", "FAKSK"],
    "VBAP": ["VBELN", "POSNR", "MATNR", "WERKS", "KWMENG", "NETWR", "ABGRU"],
    "VBEP": ["VBELN", "POSNR", "ETENR", "EDATU", "WMENG", "BMENG"],
    "LIKP": ["VBELN", "LFDAT", "WADAT_IST", "KUNNR", "LIFSK"],
    "LIPS": ["VBELN", "POSNR", "VGBEL", "VGPOS", "MATNR", "WERKS", "LFIMG"],
    "VBRK": ["VBELN", "FKART", "FKDAT", "KUNRG", "NETWR"],
    "VBRP": ["VBELN", "POSNR", "VGBEL", "VGPOS", "MATNR", "FKIMG", "NETWR"],
    "VBFA": ["VBELV", "POSNV", "VBELN", "POSNN", "VBTYP_N", "ERDAT"],
    "change_log": ["TABNAME", "TABKEY", "FNAME", "VALUE_OLD", "VALUE_NEW", "UDATE"],
}


def frames(docs: Docs, sku: pd.DataFrame, plants: list[str], start: dt.date, stock: np.ndarray,
           stock_daily: tuple, po_lines: list[PoLine]) -> dict[str, pd.DataFrame]:
    out = {name: pd.DataFrame(docs.rows.get(name, []), columns=cols) for name, cols in COLUMNS.items()}
    matnr = sku["matnr"].tolist()
    out["EKPO"] = pd.DataFrame(
        [(l.ebeln, l.ebelp, matnr[l.s], plants[l.p], l.menge, "EA", l.netpr, "X" if l.closed else "")
         for l in po_lines], columns=["EBELN", "EBELP", "MATNR", "WERKS", "MENGE", "MEINS", "NETPR", "ELIKZ"])
    out["EKET"] = pd.DataFrame(
        [(l.ebeln, l.ebelp, "0001", l.eindt, l.menge, l.received) for l in po_lines],
        columns=["EBELN", "EBELP", "ETENR", "EINDT", "MENGE", "WEMNG"])
    p_idx, s_idx = np.meshgrid(range(len(plants)), range(len(matnr)), indexing="ij")
    out["MARD"] = pd.DataFrame({"MATNR": np.array(matnr)[s_idx.ravel()], "WERKS": np.array(plants)[p_idx.ravel()],
                                "LGORT": LGORT, "LABST": stock.ravel()})

    opening, rec_q, iss_q, rej_q, closing = stock_daily
    n_days = opening.shape[2]
    grid = np.indices(opening.shape).reshape(3, -1)
    out["stock_daily"] = pd.DataFrame({
        "ds": pd.to_datetime(start) + pd.to_timedelta(grid[2], unit="D"),
        "matnr": np.array(matnr)[grid[1]], "werks": np.array(plants)[grid[0]],
        "opening_qty": opening.ravel(), "receipt_qty": rec_q.ravel(), "issue_qty": iss_q.ravel(),
        "rejected_qty": rej_q.ravel(), "closing_qty": closing.ravel(),
    })
    out["stock_daily"]["ds"] = out["stock_daily"]["ds"].dt.date
    assert len(out["stock_daily"]) == len(plants) * len(matnr) * n_days
    return out
