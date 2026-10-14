"""Step 1 and 3-4 of the simulation: material, plant, customer and vendor master data.

All draws come from `rng_for(seed, tag, ...)`, so each entity's values depend only on the seed
and its own keys. The policy replay can reuse the same vendor draws (common random numbers).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Seed tags, one per kind of draw.
TAG_SKU, TAG_VENDOR, TAG_ASSIGN, TAG_CUSTOMER, TAG_NAMES = 1, 2, 3, 4, 5
TAG_ORDERS, TAG_PO, TAG_BILLING, TAG_INVOICE = 6, 7, 8, 9

PLANT_NAMES = {"P001": "Distribution Center West", "P002": "Distribution Center Central"}
EKORG = VKORG = "1000"
LGORT = "0001"

NAME_FIRST = ["Harbor", "Summit", "Prairie", "Cedar", "Granite", "Bluewater", "Northfield", "Silverbrook",
              "Redwood", "Lakeshore", "Ironwood", "Maplecrest", "Pinehurst", "Riverbend", "Sunvale",
              "Westbrook", "Oakmont", "Highmoor", "Coastline", "Meadowlark"]
NAME_SECOND = ["Ridge", "Valley", "Point", "Hollow", "Bay", "Crossing", "Fields", "Peak", "Grove", "Landing"]
NAME_SUFFIX = {"FOODS": ["Foods", "Provisions", "Pantry Supply", "Fresh Trading"],
               "HOUSEHOLD": ["Home Supply", "Household Goods", "Housewares", "Home Products"]}


def rng_for(seed: int, *keys: int) -> np.random.Generator:
    return np.random.default_rng([seed, *keys])


def _uniform(rng: np.random.Generator, bounds, size=None):
    return rng.uniform(bounds[0], bounds[1], size)


def vendor_counts(depts: pd.Series, n_vendors: int) -> dict[str, int]:
    """Vendors per department: at least 2 each, extra vendors to the departments with most SKUs per vendor.

    FOODS + HOUSEHOLD have only 5 departments, so the 25 vendors need more than 4 in the big ones.
    """
    alloc = {d: min(2, n) for d, n in depts.items()}
    target = max(sum(alloc.values()), min(n_vendors, int(depts.sum())))
    while sum(alloc.values()) < target:
        d = max((d for d in alloc if alloc[d] < depts[d]), key=lambda d: (depts[d] / alloc[d], d))
        alloc[d] += 1
    return alloc


def build(cfg: dict, skus: pd.DataFrame, customers: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Master data tables plus planning helpers (`sku`, `vendor`) used by the engine."""
    seed, sim = cfg["seed"], cfg["simulation"]
    skus = skus.sort_values("matnr").reset_index(drop=True)
    n = len(skus)

    # Materials: cost, case pack, cases per pallet.
    rng = rng_for(seed, TAG_SKU)
    ratio = _uniform(rng, sim["cost_ratio"], n)
    sku = skus[["matnr", "dept_id", "cat_id", "avg_sell_price"]].copy()
    sku["cost"] = np.round(sku["avg_sell_price"] * ratio, 2)
    sku["case_pack"] = [int(rng.choice(cfg["case_packs"][c])) for c in sku["cat_id"]]
    sku["cases_per_pallet"] = rng.choice(sim["cases_per_pallet"], n).astype(int)

    # Vendors: 2-4 per department, SKUs dealt round-robin after a seeded shuffle.
    depts = sku.groupby("dept_id").size().sort_index()
    counts = vendor_counts(depts, int(cfg["vendors"]))
    names = _vendor_names(rng_for(seed, TAG_NAMES), [d.split("_")[0] for d, k in counts.items() for _ in range(k)])
    rows, lifnr_of = [], {}
    for d_idx, (dept, k) in enumerate(counts.items()):
        ids = [f"V{len(rows) + i + 1:04d}" for i in range(k)]
        rows += [(lifnr, dept) for lifnr in ids]
        members = sku.loc[sku["dept_id"] == dept, "matnr"].to_numpy()
        rng_for(seed, TAG_ASSIGN, d_idx).shuffle(members)
        lifnr_of.update({m: ids[i % k] for i, m in enumerate(members)})
    sku["lifnr"] = sku["matnr"].map(lifnr_of)

    vendor = pd.DataFrame(rows, columns=["lifnr", "dept_id"])
    vendor["name1"] = names
    v = sim["vendor"]
    draws = [rng_for(seed, TAG_VENDOR, i) for i in range(len(vendor))]
    vendor["lead_days"] = [int(r.integers(v["planned_lead_days"][0], v["planned_lead_days"][1] + 1)) for r in draws]
    vendor["lead_cv"] = [_uniform(r, v["lead_time_cv"]) for r in draws]
    vendor["on_time_prob"] = [_uniform(r, v["on_time_prob"]) for r in draws]
    vendor["full_prob"] = [_uniform(r, v["full_prob"]) for r in draws]
    vendor["min_order_value"] = [float(round(_uniform(r, v["min_order_value_usd"]), -1)) for r in draws]
    vendor["invoice_drift"] = [_uniform(r, v["invoice_drift"]) for r in draws]
    vendor["review_weekday"] = [int(r.integers(0, 5)) for r in draws]

    # Degrading vendors: start them near the top of the range so the slide is visible.
    deg = v["degrading"]
    picks = rng_for(seed, TAG_VENDOR, 999).permutation(len(vendor))[: deg["gradual"] + deg["sudden"]]
    vendor["degrade"] = ""
    vendor.loc[picks[: deg["gradual"]], "degrade"] = "gradual"
    vendor.loc[picks[deg["gradual"]:], "degrade"] = "sudden"
    vendor.loc[picks, "on_time_prob"] = vendor.loc[picks, "on_time_prob"].clip(lower=0.97)
    vendor.loc[picks, "full_prob"] = vendor.loc[picks, "full_prob"].clip(lower=0.98)

    sku = sku.merge(vendor[["lifnr", "lead_days"]], on="lifnr")
    plants = list(cfg["plants"])

    # Customers: one pair of order weekdays each.
    pairs = sim["order_weekday_pairs"]
    cust = customers.sort_values("kunnr").reset_index(drop=True)
    crng = rng_for(seed, TAG_CUSTOMER)
    cust["order_weekdays"] = [tuple(pairs[int(crng.integers(0, len(pairs)))]) for _ in range(len(cust))]

    per_plant = sku.merge(pd.DataFrame({"werks": plants}), how="cross")
    tables = {
        "T001W": pd.DataFrame({"WERKS": plants, "NAME1": [PLANT_NAMES.get(p, p) for p in plants]}),
        "MARA": pd.DataFrame({"MATNR": sku["matnr"], "MTART": "HAWA", "MATKL": sku["dept_id"], "MEINS": "EA"}),
        "MARC": pd.DataFrame({"MATNR": per_plant["matnr"], "WERKS": per_plant["werks"], "DISMM": "ND",
                              "MINBE": 0.0, "EISBE": 0.0, "PLIFZ": per_plant["lead_days"],
                              "BSTRF": per_plant["case_pack"]}),
        "MARM": pd.concat([
            pd.DataFrame({"MATNR": sku["matnr"], "MEINH": "CS", "UMREZ": sku["case_pack"], "UMREN": 1}),
            pd.DataFrame({"MATNR": sku["matnr"], "MEINH": "PAL",
                          "UMREZ": sku["case_pack"] * sku["cases_per_pallet"], "UMREN": 1}),
        ]),
        "MBEW": pd.DataFrame({"MATNR": per_plant["matnr"], "BWKEY": per_plant["werks"], "VPRSV": "V",
                              "VERPR": per_plant["cost"]}),
        "LFA1": pd.DataFrame({"LIFNR": vendor["lifnr"], "NAME1": vendor["name1"], "LAND1": "US"}),
        "LFM1": pd.DataFrame({"LIFNR": vendor["lifnr"], "EKORG": EKORG, "MINBW": vendor["min_order_value"]}),
        "EINA": pd.DataFrame({"INFNR": [f"53{i + 1:08d}" for i in range(n)], "MATNR": sku["matnr"],
                              "LIFNR": sku["lifnr"]}),
        "KNA1": pd.DataFrame({"KUNNR": cust["kunnr"], "NAME1": cust["name1"], "LAND1": "US"}),
    }
    infnr = dict(zip(tables["EINA"]["MATNR"], tables["EINA"]["INFNR"]))
    tables["EINE"] = pd.DataFrame({"INFNR": per_plant["matnr"].map(infnr), "EKORG": EKORG,
                                   "WERKS": per_plant["werks"], "NETPR": per_plant["cost"], "PEINH": 1,
                                   "APLFZ": per_plant["lead_days"]})
    return {"tables": tables, "sku": sku, "vendor": vendor, "customers": cust}


def _vendor_names(rng: np.random.Generator, cats: list[str]) -> list[str]:
    used, out = set(), []
    for cat in cats:
        while True:
            name = (f"{rng.choice(NAME_FIRST)} {rng.choice(NAME_SECOND)} "
                    f"{rng.choice(NAME_SUFFIX.get(cat, ['Supply']))}")
            if name not in used:
                used.add(name)
                out.append(name)
                break
    return out
