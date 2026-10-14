# S4 Control Tower: TRD

## Architecture

Build everything offline in CI and serve a static site; nothing a recruiter clicks depends on a server that can sleep. HaulRank and the Spotter planner both hit Render cold starts; this design removes that failure.

&#91;embedded content: build and serving architecture · 8 build steps, 1 static host\]

The pipeline snakes through eight steps in CI; only the AI step calls out, once per day and from cache. The visitor's browser loads static files and runs SQL itself.

**Design rules**

1. **Numbers come from SQL or Python, never from the LLM.** Same invariant as HaulRank.
2. **Every published figure has an evidence pointer** (table name + key columns) so the UI can show its source rows.
3. **Snapshots never look ahead.** A day-D snapshot uses only rows dated on or before D.
4. **Deterministic builds.** A fixed seed and pinned versions give identical outputs; CI checks the hashes.
5. **The LLM is optional at runtime.** Briefs are generated at build time and cached; with no API key the pipeline uses the template fallback and still ships.

## Stack and cost

Recurring cost is $0, with no optional spend. The LLM runs on Groq's free tier, which allows 1,000 requests a day and 8,000 tokens a minute per model on this key (read from Groq's rate-limit headers on 2026-10-15).

| Layer | Choice | Why | Cost |
| --- | --- | --- | --- |
| Language | Python 3.12 | Your strongest | $0 |
| Storage and SQL | DuckDB file + Parquet exports | Real SQL, no server, fast on a laptop and in CI | $0 |
| SQL models | Plain .sql files run in order by a small runner (dbt-duckdb optional) | Reviewable SQL a hiring manager can read | $0 |
| Demand data | M5 via `datasetsforecast` ([loader docs](https://nixtlaverse.nixtla.io/datasetsforecast/m5)) | One-line download in CI | $0 |
| Forecasting | statsforecast (SeasonalNaive, AutoETS); optional mlforecast + LightGBM | Standard, fast on thousands of series | $0 |
| Optimization | OR-Tools CP-SAT | Reused from HaulRank | $0 |
| Agent | LangGraph + Pydantic | You know both | $0 |
| LLM | Groq free tier, OpenAI-compatible API with JSON mode (`openai/gpt-oss-120b`, provisional) | One call per day; fast; 1,000 req/day free | $0 |
| Excel | openpyxl | Writes real formulas | $0 |
| Web app | React + Vite + TypeScript, DuckDB-WASM, ECharts (imported selectively), Tailwind | Static, SQL in the browser | $0 |
| Hosting | GitHub Pages (Vercel Hobby as backup) | Never sleeps | $0 |
| CI | GitHub Actions on a public repo | Builds and deploys | $0 |
| BI | Power BI Desktop (free, Windows) | Keyword match and screenshots | $0 |
| Video | OBS Studio or Loom free | Demo recording | $0 |
| Uptime check | GitHub Actions weekly link check | No paid monitor | $0 |

**Dev environment:** native Windows 11 with PowerShell, Python 3.12 and Node 24 LTS; no Docker and no WSL. Python 3.12 is pinned (not 3.14) because the forecasting stack (statsforecast, LightGBM, and numba where a library pulls it in) is safest there; a `.python-version` file containing `3.12` makes uv pick it too. CI builds on Ubuntu and also runs a small Windows job, so both stay in step.

## Repository layout

One public repo with three top-level areas: the pipeline (Python), the web app (TypeScript) and the human-facing packs (Power BI, SAP).

```text
s4-control-tower/
├── README.md · PRD.md · TRD.md · ASSUMPTIONS.md · CASE_STUDY.md
├── tasks.py                      # python tasks.py all, or one stage: ingest, simulate, data, models, forecast, ...
├── pyproject.toml · requirements.in · requirements.lock · .python-version
├── pipeline/
│   ├── config.py                 # loads config.yaml (config.small.yaml extends it); SEED override
│   ├── config.yaml               # seed, plants, SKU count, service targets, horizons; config.small.yaml = 50 SKUs for quick runs
│   ├── ingest_m5.py
│   ├── simulate/                 # vendors, purchasing, sales, deliveries, billing, docflow
│   ├── sql/                      # 00_stg_*.sql … 30_mart_*.sql, run in name order
│   ├── run_sql.py
│   ├── forecast/                 # backtest.py, forecast.py
│   ├── policy/                   # safety_stock.py, proposals_cpsat.py
│   ├── suppliers/scorecard.py
│   ├── exceptions/rules.py
│   ├── brief/                    # graph.py, prompts/, verifier.py, template.py, cache/
│   ├── export/                   # parquet.py, excel.py, site_json.py
│   └── tests/
├── web/                          # React + Vite; public/data/ filled at build time
├── powerbi/                      # S4ControlTower.pbix + screenshots/
├── sap-pack/                     # functional_spec.md, process_maps.md, uat_cases.md
├── eval/                         # backtest.json, policy_replay.json, brief_eval.json, replay_alerts.json
└── .github/workflows/            # build.yml, linkcheck.yml
```

## Data model

The pipeline writes standard S/4HANA table and field names into DuckDB, then adds a few derived tables (lower-case names) for planning. Every SAP field used is listed below; anything else is out of scope.

| Table | SAP meaning | Fields used |
| --- | --- | --- |
| T001W | Plants | WERKS, NAME1 |
| MARA | Material master | MATNR, MTART (HAWA), MATKL, MEINS |
| MARC | Material per plant | MATNR, WERKS, DISMM, MINBE, EISBE, PLIFZ, BSTRF |
| MARM | Units of measure | MATNR, MEINH (CS, PAL), UMREZ, UMREN. Both convert to EA as in SAP: CS UMREZ = units per case; PAL UMREZ = units per pallet, so cases per pallet = PAL UMREZ ÷ CS UMREZ |
| MARD | Stock per storage location | MATNR, WERKS, LGORT, LABST |
| MBEW | Valuation | MATNR, BWKEY, VPRSV, VERPR |
| LFA1 | Vendor master | LIFNR, NAME1, LAND1 |
| LFM1 | Vendor purchasing data | LIFNR, EKORG, MINBW (minimum order value) |
| EINA / EINE | Purchasing info record | INFNR, MATNR, LIFNR · EKORG, WERKS, NETPR, PEINH, APLFZ |
| EKKO | PO header | EBELN, BSART (NB), LIFNR, EKORG, BEDAT |
| EKPO | PO item | EBELN, EBELP, MATNR, WERKS, MENGE, MEINS, NETPR, ELIKZ |
| EKET | PO schedule line | EBELN, EBELP, ETENR, EINDT, MENGE, WEMNG |
| EKBE | PO history | EBELN, EBELP, VGABE (1 goods receipt, 2 invoice), GJAHR, BELNR (material document 49… or invoice 51…), BUZEI, BWART, BUDAT, MENGE, DMBTR |
| MATDOC | Material documents | MBLNR, MJAHR, ZEILE, BWART (101, 122, 601), MATNR, WERKS, LGORT, MENGE, SHKZG, BUDAT, EBELN, EBELP, VBELN\_IM |
| KNA1 | Customer master | KUNNR, NAME1, LAND1 |
| VBAK | Sales order header | VBELN, AUART (OR), KUNNR, ERDAT, VKORG, LIFSK, FAKSK |
| VBAP | Sales order item | VBELN, POSNR, MATNR, WERKS, KWMENG, NETWR, ABGRU |
| VBEP | Sales schedule line | VBELN, POSNR, ETENR, EDATU, WMENG, BMENG |
| LIKP / LIPS | Delivery header / item | VBELN, LFDAT, WADAT\_IST, KUNNR, LIFSK · POSNR, VGBEL, VGPOS, MATNR, WERKS, LFIMG |
| VBRK / VBRP | Billing header / item | VBELN, FKART (F2), FKDAT, KUNRG, NETWR · POSNR, VGBEL, VGPOS, MATNR, FKIMG, NETWR |
| VBFA | Document flow | VBELV, POSNV, VBELN, POSNN, VBTYP\_N (J delivery, M invoice), ERDAT |

Derived tables: `stock_daily` (opening, receipt, issue, rejected and closing quantity per SKU-plant-day), `change_log` (dated field changes modelled on CDHDR/CDPOS: delivery blocks set and released, ABGRU rejections, ELIKZ completions, so a snapshot can see each flag as it stood that day), `sim_vendor_params` and `sim_customer_orders` (the simulation's hidden draws, for ASSUMPTIONS.md and the policy replay), the ingest tables (`m5_calendar`, `m5_customers`, `sku_selection`, `demand_daily`, `ingest_meta`), `forecast_daily`, `policy_params`, `po_proposals`, `vendor_scorecard`, `exceptions_daily`, `brief_daily`.

**Simplifications, stated in the dictionary:** one company code, purchasing organization and sales organization; one storage location per plant; prices on items instead of pricing conditions; no MRP run, batches or invoice verification documents (invoices live only in EKBE); no ATP check, so VBEP-BMENG = WMENG; MARC-DISMM is ND (no planning) under the legacy policy until the policy stage writes VB with MINBE and EISBE; header and item fields show their state on the last simulated day, and `change_log` holds their history.

**Simulation algorithm** (seeded, in this order):

1. **SKUs.** Take the top 500 M5 items by unit sales over the last 365 days across FOODS and HOUSEHOLD combined (no fixed split; the resulting category mix goes in ASSUMPTIONS.md). MATNR = item ID, MATKL = department. Cost = 65–80% of the M5 sell price, fixed per SKU. Case pack (MARC-BSTRF, MARM CS) is drawn by seed: FOODS from {12, 24, 48}, HOUSEHOLD from {6, 12, 24}; cases per pallet go in MARM PAL. Every SKU exists in both plants with the same vendor.
2. **Calendar.** Shift all dates by a multiple of 7 days so the last M5 sales day becomes the day before the demo's "today". Weekdays stay aligned, so weekly seasonality survives. M5 ends on a Sunday (2016-06-19) and today − 1 is a Tuesday (2026-10-13), so the last 5 M5 days are dropped; the shift is +3,773 days. Each item-store series starts at its first sale (pre-launch zeros dropped).
3. **Customers and plants.** The 10 M5 stores become customers C01–C10, named after their store ("Store CA-1" and so on). California stores buy from plant P001; Texas and Wisconsin stores buy from P002.
4. **Vendors.** 25 vendors with fictional names built from seeded word lists (for example "Harbor Ridge Supply"; no real brands). Each department gets at least 2 vendors, and each SKU has one. FOODS and HOUSEHOLD have only 5 departments, so 2–4 per department would cap the total at 20; the extra vendors go to the departments with the most SKUs per vendor (with seed 42: FOODS\_1 2, FOODS\_2 4, FOODS\_3 11, HOUSEHOLD\_1 6, HOUSEHOLD\_2 2). Per vendor, draw planned lead time (5–21 days), actual lead-time spread (coefficient of variation 0.1–0.5), on-time probability (0.90–0.99), probability of a full first delivery (0.94–0.995), a minimum order value ($500–3,000, LFM1-MINBW), an invoice price drift (−3% to +3%) and a weekly review weekday (Mon–Fri). Three vendors degrade so both EXC-08 triggers fire: two slip gradually over the final 90 days, and one drops suddenly 30 days before today.
5. **Sales orders** (last 365 days only). Each customer orders on two fixed weekdays. Line quantity = that store's M5 units for the SKU since its previous order. Requested date (VBEP-EDATU) = order date + 2 days.
6. **Deliveries.** Each day, each plant allocates stock to due lines, oldest first, and posts LIKP/LIPS plus MATDOC 601. Short lines stay open 3 days, then get a rejection reason (ABGRU). 8% of orders carry a delivery block for 1–5 days (raised from 2% so EXC-06 reaches 3 firings a week).
7. **Billing.** VBRK/VBRP one day after goods issue, one billing document per delivery; 6% are delayed by 3–6 more days so EXC-07 reaches 3 firings a week (raised from 1%).
8. **Purchasing, using a deliberately weak legacy policy.** Weekly review per vendor; order-up-to = 14-day average demand × (lead time + 7) × 1.2, with no variability buffer; inventory position = on hand + open PO quantity; quantity rounded up to whole cases (MARC-BSTRF), then topped up a case at a time until the PO reaches the vendor minimum (LFM1-MINBW). One PO per vendor and plant per review. Write EKKO/EKPO/EKET with EINDT = BEDAT + APLFZ. The new policy (TRD Inventory policy) is judged against this baseline.
9. **Receipts and invoices.** Each PO arrives on one truck at BEDAT + planned lead time × a lognormal multiplier, floored at 75% of planned. The multiplier's spread comes from the vendor's CV and its median is set so P(arrival ≤ EINDT + 1) equals the vendor's on-time probability. Each line arrives in full with the vendor's full-delivery probability; otherwise 50–95% of its cases arrive, and the rest either follows 3–10 days later or the line closes short (ELIKZ), 50/50. Post MATDOC 101 and EKBE type 1. The invoice (EKBE type 2, one document 51… per goods receipt, 1–5 days later) is at PO price × (1 + vendor drift + noise with a 0.5% standard deviation). Draws are keyed by vendor, plant and PO date, so the policy replay sees the same vendor behaviour (common random numbers).
10. **Stock.** Start at 30 days of average demand. Each day, add receipts and subtract issues; stock never goes negative (the shortfall is unfilled demand). Write `stock_daily`.

**Exception coverage.** Every rule should fire at least 3 times per week. Reach that by tuning simulation rates first. Plant specific cases only for rules that still don't fire, and log each planted case in ASSUMPTIONS.md. Cap critical rows at about 40 per day so the list stays realistic.

Full documents cover the last 365 days only; earlier M5 history feeds forecasting as `demand_daily`. Seed 42 gives about 462,000 sales order lines, 41,000 PO lines and 498,000 material document lines; the simulation takes about 1 minute.

## Pipeline, SQL models and snapshots

Nine stages run in order through tasks.py, a small Python runner that behaves the same in PowerShell and in CI; the whole build should finish in about 20 minutes on a standard GitHub runner.

| # | Stage | Command | Writes | Time budget |
| --- | --- | --- | --- | --- |
| 1 | Ingest M5 (download cached between runs) | `python tasks.py ingest` (or `data`) | `m5_calendar`, `m5_customers`, `sku_selection`, `demand_daily`, `ingest_meta` | 2 min |
| 2 | Simulate SAP layer, then run the integrity checks | `python tasks.py simulate` (or `data`) | All SAP tables, `stock_daily`, `change_log` | 3 min |
| 3 | SQL models | `python tasks.py models` | Intermediate and mart views | 30 s |
| 4 | Forecast and backtest | `python tasks.py forecast` | `forecast_daily`, eval/backtest.json | 5 min |
| 5 | Policy and proposals | `python tasks.py policy` | `policy_params`, `po_proposals` | 2 min |
| 6 | Scorecard and exceptions | `python tasks.py exceptions` | `vendor_scorecard`, `exceptions_daily` | 1 min |
| 7 | AI brief | `python tasks.py brief` | `brief_daily`, eval/brief\_eval.json | 2 min; seconds on cache hit |
| 8 | Export | `python tasks.py export` | Parquet and JSON for the site; CSV for Power BI; the .xlsx plan | 1 min |
| 9 | Site | `python tasks.py site` | web/dist | 1 min |

**SQL models** (one file each, run in name order):

- `10_int_open_po_lines`: schedule lines with open quantity as of the snapshot date.
- `11_int_po_receipts`: per schedule line, first and last receipt date, received quantity, on-time and in-full flags.
- `12_int_vendor_lead_times`: actual lead time per receipt; rolling 90-day mean, p80 and coefficient of variation per vendor.
- `13_int_so_line_status`: VBAP + VBEP + LIPS + VBFA joined into due, delivered, billed and blocked flags.
- `20_mart_kpi_service_daily`, `21_mart_kpi_inventory_daily`, `22_mart_vendor_30_90`, `23_mart_no_movement_28d`, `24_mart_o2c_flow`.

**Snapshots without look-ahead.** Every SQL template takes `{{snapshot_date}}` and filters each dated column (BUDAT, BEDAT, ERDAT, FKDAT, WADAT\_IST) to that date or earlier. The pipeline builds 60 daily snapshots and stores outputs partitioned by `snapshot_date`. Forecasts are re-run weekly (a realistic planning cycle, 9 origins); days in between reuse the latest weekly forecast. A test rebuilds one snapshot from a database truncated at D and checks it matches the snapshot built from the full database.

## Forecasting and backtest

Forecast daily demand per SKU-plant (customer demand summed to its plant) 28 days ahead, and prove the model beats a seasonal-naive baseline on a holdout fold.

**Models**, all from Nixtla's open-source libraries:

- Baseline: `SeasonalNaive(season_length=7)`.
- Main: `AutoETS(season_length=7)`.
- Intermittent SKUs (more than 50% zero days): add `CrostonOptimized`.
- Optional: LightGBM through mlforecast, with lags 7/14/28, rolling means over 7 and 28 days, day of week, and M5 price and SNAP features.

**Backtest protocol.** Rolling origin with `cross_validation(h=28, step_size=28, n_windows=4)`. For each ABC-XYZ class, pick the model with the lowest WAPE on folds 1–3, then report fold 4 as the holdout. Never tune on fold 4.

**Metrics**, computed over all SKU-days in a class:

```latex
\mathrm{WAPE} = \frac{\sum_t |A_t - F_t|}{\sum_t A_t} \qquad \mathrm{Bias} = \frac{\sum_t (F_t - A_t)}{\sum_t A_t}
```

**Classes.** ABC by 365-day revenue share: A is the top 80%, B the next 15%, C the last 5%. XYZ by the coefficient of variation of weekly demand: X below 0.5, Y 0.5–1.0, Z above 1.0.

**Outputs.** `forecast_daily(origin_date, matnr, werks, ds, yhat, model)` and `eval/backtest.json` with WAPE and bias per class, model and fold. The holdout residuals per SKU also feed the safety-stock formula (σ in the next section).

## Inventory policy and PO proposals

Set a periodic-review, order-up-to policy per SKU-plant from forecast error and lead-time spread, then let CP-SAT turn the gaps into orderable quantities per vendor.

**Policy parameters**

```latex
SS = z \sqrt{L\,\sigma_e^{2} + \bar{d}^{2}\,\sigma_L^{2}} \qquad ROP = \bar{d}\,L + SS \qquad S = \bar{d}\,(L + R) + SS
```

- d̄: mean forecast daily demand over the next 28 days. σe: standard deviation of daily forecast errors on the holdout fold.
- L and σL: mean and standard deviation of the vendor's actual lead time (rolling 90 days). R: review period, 7 days.
- z by service target: A 2.054 (98%), B 1.645 (95%), C 1.282 (90%).
- Inventory position IP = on hand + open PO quantity − open customer backlog. Gap = max(0, S − IP).
- Write SS to MARC-EISBE and ROP to MARC-MINBE with MRP type VB, the fields an SAP planner maintains for reorder-point planning.

**CP-SAT proposal model**, solved per vendor and plant on its review day. CP-SAT is integer-only, so money is in cents and pallets in hundredths.

- Variables: cases n\_i ≥ 0 per SKU; trucks k ∈ {0,…,3}; order flag y ∈ {0,1}; shortfall s\_i ≥ 0; overage o\_i ≥ 0.
- s\_i ≥ gap\_i − pack\_i·n\_i and o\_i ≥ pack\_i·n\_i − gap\_i.
- Truck capacity: Σ pallets\_i·n\_i ≤ capacity·k, with capacity 26 pallets for both plants (config). pallets\_i = 1 ÷ cases per pallet (MARM PAL).
- Vendor minimum MOQ\_v is the minimum order value from LFM1-MINBW.
- Vendor minimum: Σ cost\_i·pack\_i·n\_i ≥ MOQ\_v·y; n\_i ≤ M·y; k ≥ y.
- Objective: minimize Σ (w\_i·s\_i + h\_i·o\_i) + F·k, where w\_i = unit cost × ABC weight (A 3, B 2, C 1), h\_i = unit cost × 25% yearly holding rate × 7/365, and F = freight cost per truck (config `freight_cost_per_truck_usd`, $800; an assumption).
- Time limit 2 s per vendor-plant; on timeout, round each gap up to whole cases and log it.

**Policy replay (the case-study headline).** Re-run the last 180 days of the simulation with the new policy buying instead of the legacy one. Use the same demand and the same vendor random draws (common random numbers). Compare fill rate, stockout rate and average inventory value. Publish whatever the result is in `eval/policy_replay.json`.

## Scorecard, exceptions and SAP pack

All three are deterministic Python or SQL over the snapshot; the rules themselves are defined once, in the PRD's Business rules.

**Vendor scorecard** (30- and 90-day windows):

- OTIF as defined in the PRD; vendor fill rate = received ÷ ordered quantity for lines due in the window.
- Lead time: mean, p80 and coefficient of variation of actual days from BEDAT to the first receipt.
- Price variance = Σ (invoice price − info-record price) × quantity ÷ Σ info-record price × quantity, from EKBE type 2 and EINE-NETPR.
- Grade by OTIF: A 95% or more, B 90–95%, C 85–90%, D below 85%. Drop one grade if lead-time variation exceeds 0.4 or price variance exceeds ±2%.

**Exception output.** One row per firing in `exceptions_daily`:

```text
snapshot_date, exc_id, severity, rank, matnr, werks, lifnr, ebeln, ebelp, vbeln,
metric, value, threshold, days_to_impact, value_at_risk, action, evidence
```

- `evidence` is JSON listing the source rows, for example `[{"table":"EKET","keys":{"EBELN":"4500012345","EBELP":"00010","ETENR":"0001"}}]`. The drill-down drawer reads it.
- Rank order: severity, then ABC class, then days to impact (soonest first), then value at risk (largest first). EXC-08 rows have no SKU: rank them as A-class, with value at risk = the vendor's open PO value.
- `action` is a template with numbers filled in, such as "Expedite PO 4500012345/10 (120 EA due 2026-10-18) or order 240 EA now." The LLM never writes this field.
- Use SAP-style number ranges so documents look familiar: POs 45…, material documents 49…, invoices 51…, info records 53…, sales orders 0010…, deliveries 80…, billing 90…. Item numbers are zero-padded as in SAP (EBELP 00010, POSNR 000010, ETENR 0001).

**SAP functional pack** (`sap-pack/`):

1. **Functional spec, ZMM\_PO\_EXCEPTIONS (PO exception monitor).** Purpose; selection screen (plant, vendor, delivery date range, exception type); data selection from EKKO, EKPO, EKET, EKBE, MATDOC, MARD and MARC; logic for EXC-01, 02, 03 and 08; ALV output columns; authorization checks on plant (M\_BEST\_WRK) and purchasing organization (M\_BEST\_EKO); performance notes; open points.
2. **Process maps.** P2P: ME51N requisition, ME21N order, MIGO receipt (101), MIRO invoice, F110 payment. O2C: VA01 order, VL01N delivery, VL02N goods issue (601), VF01 billing, F-28 incoming payment. Mark where each exception rule attaches.
3. **UAT script, 10 cases** (scenario, preconditions, steps, expected result):
   1. PO line past its delivery date with no receipt appears in EXC-02.
   2. Partial receipt of 60% stays flagged with 40% open.
   3. Full receipt clears the line in the next snapshot.
   4. A line closed short (ELIKZ set) is not flagged late.
   5. Sales order with a delivery block due in 2 days appears in EXC-06.
   6. Removing the block clears it.
   7. Goods issue with no billing after 2 days appears in EXC-07.
   8. Creating the billing document clears it.
   9. A vendor whose 30-day OTIF falls below 85% appears in EXC-08.
   10. A user authorized only for P001 sees no P002 rows.

## AI brief

The LLM gets a facts file and returns words; a deterministic verifier rejects any number, date or ID that is not in the facts, and a template takes over after two failures.

**Facts file** (one per snapshot day). Every fact has a stable ID and a pre-formatted string, so the model copies numbers instead of computing them:

```json
{"snapshot_date": "2026-10-14",
 "kpis": [{"id": "K1", "name": "Fill rate", "value_str": "94.2%", "delta_7d_str": "-1.8 pts"}],
 "exceptions": [{"id": "E1", "exc_id": "EXC-01", "severity": "critical", "matnr": "FOODS_3_090", "werks": "P001",
                 "days_to_impact_str": "3 days", "action": "Expedite PO 4500012345/10 ..."}],
 "vendors": [{"lifnr": "V0007", "name": "Vendor 07",
              "late_lines": [{"ebeln": "4500012345", "ebelp": "10", "open_qty_str": "120 EA", "due_str": "2026-10-11", "days_late_str": "3"}]}]}
```

**Graph** (LangGraph `StateGraph`):

1. `load_facts`: read the top 15 exceptions, KPI deltas and late lines per vendor from DuckDB.
2. `draft`: one LLM call returns `{brief, emails[{lifnr, subject, body}], cited_fact_ids}`, validated with Pydantic. Temperature 0; at most 1,200 output tokens.
3. `verify`: the checks below. On failure, return to `draft` once with the list of violations.
4. `template`: after a second failure, a Jinja template writes the brief and emails from the same facts and marks them "template".

**Verifier checks**

- Every number, percentage, money amount and date in the text matches a token in the facts' formatted strings or the snapshot date.
- Every PO number (45 + 8 digits), vendor ID and SKU mentioned exists in the facts.
- Every critical exception is mentioned in the brief.
- The brief is 200 words or fewer; there is one email per vendor with late lines and none for any other vendor.
- Results go to `eval/brief_eval.json`: per day pass or fail, unsupported tokens, attempts and fallback used.

**Email style.** Polite, short and professional, not legalistic. Greet the vendor by LFA1-NAME1 ("Dear Harbor Ridge Supply team") and sign "Purchasing, Plant P001 (demo)", using the plant of the late lines.

**LLM budget.** One call per snapshot day plus at most one retry: 60–120 calls for 60 days. Groq's free tier allows 1,000 requests a day, so the whole first run fits in one day; the binding limit is 8,000 tokens a minute, so the graph waits between calls when the limit headers say so. Responses are cached under `brief/cache/` keyed by a hash of prompt version, model ID and facts, and committed. CI then calls the LLM only when facts or prompts change, and with no API key it ships template briefs. Pin the model ID in config.yaml and record it in the eval file, because free models come and go. Provisional pin: `openai/gpt-oss-120b` (JSON mode verified 2026-10-15); `qwen/qwen3.8-27b` is the fallback. Confirm the pin at M3 against Groq's model list.

**Stretch S-01 (ask box).** A serverless function (Vercel Hobby or Cloudflare Workers free tier) holds the key and lets the model pick from a whitelist of parameterized queries. The browser runs the query in DuckDB-WASM, and the answer passes the same verifier. Never ship the key to the browser.

## Front end, Excel and Power BI

The site paints from small precomputed JSON first and loads DuckDB-WASM only when someone drills down, so the first screen is fast on a phone.

**Pages:** Overview (KPI tiles and 60-day trends) · Exceptions (ranked table, filters, drill-down drawer) · Inventory (SKU explorer: projected stock against SS and ROP, with open PO arrivals) · Suppliers (scorecard and vendor detail) · O2C (blocked and unbilled orders with their document chain) · Brief (daily brief, emails, verifier result) · About (assumptions, method, links).

**Data on the site**

- `data/<snapshot_date>/`: `kpis.json`, `exceptions_top50.json`, `brief.json`, plus `exceptions.parquet`, `scorecard.parquet`, `proposals.parquet` and `o2c.parquet`.
- `data/static/`: master data and evidence rows for the last 60 days (EKET, EKBE, MATDOC, VBAK, VBEP, LIKP, VBRK, VBFA) as Parquet. Keep the whole folder under 50 MB.
- The drawer shows the evidence rows and the exact SQL text from `web/src/queries/*.sql`; there is no free-form SQL box.
- A date picker switches the snapshot folder; the URL carries the date so a link reproduces the view.

**Branding:** no SAP logos or trademarks. Copy says "SAP S/4HANA-style tables", and every page footer reads "Not affiliated with SAP SE. Simulated data."

**Budgets:** first JavaScript under 500 KB gzipped (DuckDB-WASM loads lazily); works at 380 px wide; tables scroll inside their own container; light and dark themes.

**Excel plan** (`Replenishment_Plan_<date>.xlsx`, openpyxl):

| Sheet | Contents |
| --- | --- |
| Plan | One row per SKU-plant: plant, SKU, description, vendor, ABC, on hand, open PO, 28-day forecast, average daily demand, SS, ROP, order-up-to, proposed cases (editable, highlighted), case pack, then formulas for quantity (= cases × pack), days of cover after order and value |
| Vendors | SUMIFS of order value per vendor against its minimum, with a conditional flag when below |
| Assumptions | Service targets, review period, holding rate, data date, "simulated data" notice |

Filters, frozen header and data validation (cases 0 or more) are on. Derived columns are formulas, not pasted values, so the planner's edits recalculate.

**Power BI.** Import the CSV star schema from `exports/` (facts: exceptions, KPI daily, PO lines; dimensions: material, vendor, plant, date). Write DAX measures for fill rate, OTIF and days of cover, and build three pages: Service, Inventory, Suppliers. Commit the .pbix, PNG screenshots and a short clip. Division of work: the pipeline writes the CSV star schema and `powerbi/measures.dax`; Hamdan builds the .pbix in Power BI Desktop. A public live Power BI link needs a Power BI service account, so the static site stays the live demo.

## CI/CD and deploy

One workflow builds, tests, gates and deploys on every push to main, with a small Windows job that keeps your setup working; a second runs a weekly smoke test against the live site. The committed workflow grows with the pipeline: today it runs `tasks.py data` (ingest, simulate and the integrity checks; full config on Ubuntu, small on Windows) and `pytest`; the Pages build and deploy jobs are added with the Overview page.

```yaml
# .github/workflows/build.yml (sketch; pin the current major version of each action)
on: { push: { branches: [main] }, workflow_dispatch: {} }
permissions: { contents: read, pages: write, id-token: write }
jobs:
  windows-check:               # same code on Windows, small config, no deploy
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - uses: actions/cache@v4
        with: { path: data/m5, key: m5-win-v1 }
      - run: pip install -r requirements.lock
      - run: python tasks.py data models --config pipeline/config.small.yaml
      - run: pytest -q
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - uses: actions/cache@v4
        with: { path: data/m5, key: m5-v1 }
      - run: pip install -r requirements.lock
      - run: python tasks.py all
        env: { GROQ_API_KEY: "${{ secrets.GROQ_API_KEY }}", LLM_MODE: cache-first }
      - run: pytest -q && python -m pipeline.gates
      - uses: actions/setup-node@v4
        with: { node-version: 24 }
      - run: python tasks.py site
      - uses: actions/upload-pages-artifact@v3
        with: { path: web/dist }
  deploy:
    needs: [build, windows-check]
    runs-on: ubuntu-latest
    environment: github-pages
    steps: [ { uses: actions/deploy-pages@v4 } ]
```

**Gates** (`pipeline.gates`) fail the build when: the determinism hash changes without a version bump, any published brief has an unsupported number, a snapshot fails the no-look-ahead test, or the site data folder exceeds 50 MB.

**GitHub Pages gotchas**

- Set Vite `base` to `/<repo-name>/`, and use a hash router (or a 404.html fallback) so deep links work.
- Pages cannot set COOP/COEP headers, so use DuckDB-WASM's default non-threaded bundle.
- `linkcheck.yml` runs weekly and after each deploy: Playwright opens every page on the live URL, picks a snapshot and opens one drill-down.

## Testing and definition of done

Tests target the claims a hiring manager might check: the formulas, the SAP document chains, no look-ahead, and no invented numbers.

| Layer | What it proves | Examples |
| --- | --- | --- |
| Unit | Formulas and solvers are right | SS/ROP against hand-computed cases; CP-SAT respects MOQ, case pack and truck capacity; each rule on a small fixture |
| Data integrity | The SAP layer is internally consistent | Unique keys (EKPO: EBELN+EBELP; VBAP: VBELN+POSNR); every EKPO has an EKKO, every LIPS has its VGBEL order line; no receipt before its PO date; stock never negative; VBFA chains complete except the planted gaps |
| Snapshot | No look-ahead | Snapshot built from data truncated at D equals the full-data snapshot for D |
| Determinism | Same seed, same output | Two runs give identical hashes |
| Verifier | The guard catches inventions | Adversarial strings: a wrong number, an unknown PO, a rounded percentage, a missing critical exception |
| End to end | The live site works | Playwright: every page loads, KPI tiles match kpis.json, a drill-down shows evidence rows |

**Definition of done**

- [ ] All Must requirements FR-01 to FR-14 shipped
- [ ] CI green, gates passing, site live on GitHub Pages
- [ ] eval/backtest.json, eval/policy\_replay.json and eval/brief\_eval.json committed, with numbers quoted unchanged in the case study
- [ ] Zero unsupported numbers in the 60 published briefs
- [ ] Excel plan opens in Excel and Google Sheets with working formulas
- [ ] Power BI .pbix, screenshots and clip committed
- [ ] SAP pack: functional spec, process maps and 10 UAT cases
- [ ] README, ASSUMPTIONS.md, CASE\_STUDY.md and a 90-second video
- [ ] Landing page loads under 3 s on a phone; Playwright smoke passes on the live URL

## Runbook, configuration and security

Everything runs locally with Python and Node; nothing needs a cloud account except the GitHub repo.

```powershell
# one-time setup, from the repo folder (for example C:\dev\s4-control-tower)
setx PYTHONUTF8 1                       # then reopen PowerShell
py -3.12 -m venv .venv                  # .python-version pins 3.12 for uv as well
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # once, only if activation is blocked
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock
npm --prefix web ci

# build and check
python tasks.py all                     # data, models, forecast, policy, exceptions, brief, export
python tasks.py site                    # builds web\dist
npm --prefix web run preview            # add -- --port 5173 if the default port is refused
pytest -q; python -m pipeline.gates
```

**Lock file:** `requirements.in` lists direct dependencies. `uv pip compile requirements.in --universal -o requirements.lock` writes one lock for both Windows and Linux (pip-tools if uv is unavailable).

`tasks.py` is about 60 lines of argparse: one function per stage, `all` runs stages 1–8 in order, several stages can be named at once, and `--config` picks a config file.

**Windows notes**

- Keep the repo at a short path such as `C:\dev\s4-control-tower`; deep `node_modules` paths can hit Windows' 260-character limit.
- `PYTHONUTF8=1` stops Windows reading and writing text as cp1252, which breaks on characters like "ü" and "·".
- Build every path with `pathlib`; never type `/` or `\` into a path string.
- Write CSVs with `lineterminator="\n"` and commit a `.gitattributes` containing `* text=auto eol=lf`. Otherwise Windows and CI produce different bytes and the determinism gate fails.
- Hash only Parquet and JSON outputs for that gate; .xlsx files embed timestamps.
- Close Excel and Power BI before re-running export. Windows locks open files and the run stops with `PermissionError`.
- Only one process can write the .duckdb file; close any notebook or database viewer that has it open.
- In `tasks.py`, call npm through `shutil.which("npm")`, which finds `npm.cmd` on Windows; a bare `"npm"` in `subprocess` fails there.
- Point Power BI Desktop at the `exports\` folder once, then press Refresh after each run.

**config.yaml** (defaults):

```yaml
version: 1                   # bump when outputs change on purpose; the determinism gate checks it
seed: 42
today: 2026-10-14            # demo "today", fixed forever; M5 dates shift to end the day before
skus: 500
categories: [FOODS, HOUSEHOLD]
plants: {P001: [CA_1, CA_2, CA_3, CA_4], P002: [TX_1, TX_2, TX_3, WI_1, WI_2, WI_3]}
vendors: 25
snapshots: 60
service_targets: {A: 0.98, B: 0.95, C: 0.90}
review_period_days: 7
holding_rate_year: 0.25
truck_pallets: 26
freight_cost_per_truck_usd: 800
case_packs: {FOODS: [12, 24, 48], HOUSEHOLD: [6, 12, 24]}
max_critical_per_day: 40
forecast: {horizon: 28, windows: 4, season_length: 7}
llm: {provider: groq, base_url: "https://api.groq.com/openai/v1", model: openai/gpt-oss-120b, mode: cache-first, max_output_tokens: 1200}
paths: {data_dir: data, db: data/s4ct.duckdb}
```

| Variable | Needed | Notes |
| --- | --- | --- |
| `GROQ_API_KEY` | Only to refresh briefs | Local `.env` (gitignored) and a GitHub Actions secret; never in `web/` or the bundle |
| `LLM_MODE` | No | `cache-first` (default), `live`, or `template` |
| `SEED` | No | Overrides config; changing it changes every hash |

**Security and hygiene**

- The site is static and holds no secrets; the only key lives in CI secrets (and in the S-01 function, if built).
- No personal data: customers and vendors are synthetic names.
- Never commit `.env`; add a pre-commit secret scan.
- `.gitignore` anchors build data to the repo root (`/data/`, `/web/public/data/`, `/exports/`) so folders named `data` deeper in the tree are not ignored by accident. `pipeline/brief/cache/` is committed.
- Keep your existing convention: commits authored as Muhammad Hamdan Ishfaq (`163332483+hamdan-ishfaq@users.noreply.github.com`, set in the repo's local git config), with no AI co-author trailers.
- Commit locally after each working, tested piece; push only on request. Repo: https://github.com/hamdan-ishfaq/s4-control-tower (Vite `base` = `/s4-control-tower/`).
