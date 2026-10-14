# Assumptions

Every simulation choice that a reviewer might question, with the reason. Numbers here are produced by the pipeline; re-run `python tasks.py ingest` to regenerate them.

## Demand data (M5)

- **Source.** M5 (Walmart, 10 stores in CA, TX and WI), downloaded at build time through `datasetsforecast`. The raw files are never committed or re-hosted.
- **Calendar shift.** Dates move forward by a multiple of 7 days so weekdays stay aligned. M5 ends on Sunday 2016-06-19, but the demo's "today" is Wednesday 2026-10-14, so the last 5 M5 days are dropped and the data ends on Tuesday 2016-06-14. Shift: +3,773 days (539 weeks). Demand history runs 2021-05-29 to 2026-10-13.
- **Pre-launch zeros.** Each item-store series starts at its first sale; the zeros before an item's launch are dropped.

## SKU selection

Top 500 M5 items by unit sales over the last 365 kept days (2015-06-16 to 2016-06-14, all 10 stores), across FOODS and HOUSEHOLD combined, with no fixed split. Ties break by item ID.

| Category | Department | SKUs | SKU share | Unit share | Revenue share |
| --- | --- | ---: | ---: | ---: | ---: |
| FOODS | all | 371 | 74.2% | 78.7% | 75.9% |
| | FOODS_1 | 41 | 8.2% | 7.9% | 7.7% |
| | FOODS_2 | 79 | 15.8% | 11.7% | 15.3% |
| | FOODS_3 | 251 | 50.2% | 59.1% | 52.9% |
| HOUSEHOLD | all | 129 | 25.8% | 21.3% | 24.1% |
| | HOUSEHOLD_1 | 121 | 24.2% | 20.5% | 23.1% |
| | HOUSEHOLD_2 | 8 | 1.6% | 0.8% | 1.0% |

## Customers and plants

The 10 M5 stores are customers C01–C10 ("Store CA-1" and so on). CA stores (C01–C04) buy from plant P001; TX and WI stores (C05–C10) buy from P002.

## Vendors

25 fictional vendors (names from seeded word lists). FOODS and HOUSEHOLD have only 5 M5 departments, so the TRD's "2–4 vendors per department" would allow at most 20; every department keeps at least 2 and the rest go where SKUs per vendor are highest: FOODS_1 2, FOODS_2 4, FOODS_3 11, HOUSEHOLD_1 6, HOUSEHOLD_2 2. Every SKU has one vendor, the same for both plants. Three vendors degrade on purpose (two gradually over the last 90 days, one suddenly 30 days before today), so the "vendor slipping" rule has something real to find. Per-vendor draws are in the `sim_vendor_params` table.

## Simulation rates

| Setting | Value | Why |
| --- | --- | --- |
| Orders per customer | 2 fixed weekdays a week; quantity = the store's M5 units since its previous order | Store replenishment from the DC |
| Requested date | Order date + 2 days | |
| Short lines | Rejected (ABGRU 02) 3 days after the requested date | |
| Delivery blocks | 8% of orders, 1–5 days | The TRD's 2% gave about 0.3 blocked orders a week, too few for EXC-06 |
| Late billing | 6% of deliveries, 3–6 extra days | The TRD's 1% gave about 0.5 a week, too few for EXC-07 |
| Legacy purchasing | Weekly; order-up-to = 14-day average × (lead time + 7) × 1.2; no safety buffer | The deliberately weak baseline the new policy is judged against |
| Opening stock | 30 days of average demand, 365 days before today | The first weeks are a ramp-up, outside the 60-day replay window |

Seed 42 gives a line fill rate of 98.4% and 2.4% of SKU-plant-days ending at zero stock under the legacy policy.

## Planted cases

None yet. Every exception case planted to make a rule fire is logged here (TRD, Exception coverage).
