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

## Planted cases

None yet. Every exception case planted to make a rule fire is logged here (TRD, Exception coverage).
