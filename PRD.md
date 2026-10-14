# S4 Control Tower: PRD

Oct 15, 2026 · @Steve

## Summary

S4 Control Tower is a free public demo that answers a supply planner's morning questions. Which SKUs will stock out? Which PO lines are late? Which vendors are slipping? Which deliveries are stuck? It also drafts the follow-up emails. It runs on SAP S/4HANA-shaped tables built from public M5 demand data plus a documented simulation. Every number comes from SQL; the AI only writes the words around them.

It exists to win interviews for supply chain analyst, logistics data and junior SAP MM/SD roles. Each module maps to a demand found in the 33-job scan: Supply Chain & SAP Job Scan + Portfolio Project.

**Goals**

1. A recruiter understands what it does within 60 seconds, from the live link or the video.
2. A hiring manager can check any figure by clicking it and seeing its source rows.
3. It costs $0 to run and never sleeps: no server on the path a recruiter clicks.
4. One person ships it part-time by Nov 11, 2026.

**Non-goals**

- Real company data or a live SAP connection.
- LLM fine-tuning, real-time streaming, user accounts, or write-back to any ERP.
- Accuracy claims beyond the stated backtest on simulated data.

## Users

The four operational personas are simulated; the recruiter is the real user, and every design choice serves a 60-second visit.

| Persona | What they need | Where it shows |
| --- | --- | --- |
| Supply planner (primary) | A ranked morning list of what to act on; order proposals they can edit | Exceptions page, Excel plan |
| Buyer | Late PO lines by vendor, draft chase emails, vendor scorecard | Suppliers page, Brief page |
| Order-to-cash analyst | Blocked deliveries and delivered-but-unbilled orders, with document flow | O2C page |
| Supply chain manager | Service, inventory and vendor KPI trends | Overview page, Power BI |
| Recruiter or hiring manager (real) | Proof of skills in 60 seconds; numbers they can trust | Landing page, video, case study |

The business framing is a distributor. Two distribution centers (SAP plants) buy about 500 SKUs from 25 vendors and sell to 10 customer accounts. This mirrors FFC's dealer model and exercises both MM and SD, unlike a pure retail store setup.

## Scope

The MVP is the 10 stories below; nothing in Stretch starts until the MVP definition of done (TRD) is ticked.

| ID | Story | Acceptance criteria |
| --- | --- | --- |
| US-01 | As a planner, I see today's exceptions ranked by severity, so I act on the worst first. | Ranked list renders within 2 s of page load. Each row shows type, entity (SKU, PO line, vendor or order), key number and recommended action. Filters by type and severity. |
| US-02 | As a planner, I click any number and see the rows that produced it. | A drawer shows the source rows (for example EKET and MATDOC lines) and the SQL that computed the figure. |
| US-03 | As a planner, I download a replenishment plan and adjust quantities. | An .xlsx with one row per SKU and plant. Order quantity is editable and days of cover recompute by formula. Opens in Excel and Google Sheets. |
| US-04 | As a buyer, I read a vendor scorecard for the last 30 and 90 days. | OTIF, lead-time mean and p80, lead-time variability and price variance per vendor. Grades A–D with thresholds printed. |
| US-05 | As a buyer, I get one draft chase email per vendor with late lines. | Every figure, PO number and date in the email exists in that day's facts. |
| US-06 | As a manager, I read a daily brief of 200 words or fewer. | Passes the grounding check (TRD). If it fails twice, the deterministic template is shown instead and labelled. |
| US-07 | As an O2C analyst, I see blocked deliveries due within 3 days and deliveries unbilled after 2 days. | Each row shows its document chain: sales order, delivery, billing (or the missing step). |
| US-08 | As a reviewer, I replay any of the last 60 days. | A date picker switches every page to that day's snapshot, built only from data known on that day. |
| US-09 | As a reviewer, I see forecast accuracy against a baseline. | WAPE and bias by ABC-XYZ class over 4 backtest folds; the last fold is a holdout. |
| US-10 | As a recruiter, I understand the project from the landing page. | A one-sentence pitch, 3 headline numbers from the backtest, a 90-second video, and links to the repo and case study. |

**Stretch**, in priority order:

1. S-01 Ask-a-question box: a serverless function that answers with SQL tools and the same grounding check.
2. S-02 Inbound freight cost: score carriers for inbound POs with HaulRank's deterministic engine.
3. S-03 Shopify-format order export, for e-commerce operations roles.
4. S-04 Tableau Public version of the dashboard.

## Functional requirements

Fourteen requirements are Must for launch; one is Could. The last column names the job-scan demand each one answers.

| ID | Module | Requirement | Priority | JD demand |
| --- | --- | --- | --- | --- |
| FR-01 | Data | Generate SAP-shaped tables from M5 plus a seeded simulation; the same seed gives byte-identical outputs | Must | SAP in 82% of SAP JDs |
| FR-02 | Data | Data dictionary for every table and field: SAP name, plain-English meaning, example | Must | Documentation in 45% of SAP JDs |
| FR-03 | KPIs | SQL views for fill rate, OTIF, days of cover, inventory turns, stockout rate, no movement in 28 days | Must | Reporting in 86% of analyst JDs |
| FR-04 | Forecast | Daily SKU-plant forecast 28 days ahead; seasonal-naive baseline plus one model; rolling backtest | Must | Forecasting in 64% |
| FR-05 | Inventory policy | Safety stock, reorder point and order-up-to level per SKU-plant; service target by ABC class | Must | Inventory in 64% |
| FR-06 | PO proposals | Order quantities that respect case pack, vendor minimum order value and truck capacity (OR-Tools CP-SAT) | Must | PO execution in 36% |
| FR-07 | Suppliers | Scorecard: OTIF, lead-time mean/p80/variability, price variance, grade | Must | Supplier scorecards in 41% |
| FR-08 | Exceptions | Eight deterministic rules (Business rules) with severity, evidence rows and a templated action | Must | Grüns "exception lists" |
| FR-09 | AI brief | Daily brief and per-vendor emails from facts only; grounding verifier; template fallback | Must | AI tools in 27%, automation in 36% |
| FR-10 | Web app | Static site: Overview, Exceptions, Inventory, Suppliers, O2C, Brief, About; drill-down; 60-day replay | Must | Dashboards in 86% |
| FR-11 | Excel | Replenishment plan workbook with live formulas | Must | Excel in 64% |
| FR-12 | Power BI | Three-page report on the exported data; .pbix and screenshots in the repo | Must | Power BI/Tableau in 18% |
| FR-13 | SAP pack | Functional spec for a PO exception report, P2P and O2C maps with T-codes, 10 UAT test cases | Must | Configuration and UAT in 100% of SAP JDs |
| FR-14 | Story | Landing page, README, ASSUMPTIONS.md and a one-page case study | Must | All roles |
| FR-15 | Ask | Natural-language questions answered through SQL tools | Could | AI tools |

## Business rules

These definitions are the contract between the SQL, the dashboard, the Excel file and the AI brief; all four must show the same number.

**KPIs**

| KPI | Definition | Source |
| --- | --- | --- |
| Fill rate (line) | Delivered quantity ÷ ordered quantity, for sales order lines due in the period | VBAP, VBEP, LIPS |
| OTIF (vendor) | Share of PO schedule lines received in full (at least 98% of quantity) by the delivery date plus 1 day grace | EKET, MATDOC movement 101 |
| Days of cover | Unrestricted stock ÷ mean forecast daily demand over the next 28 days | MARD, forecast |
| Inventory turns | Cost of goods issued in the last 90 days × 365/90 ÷ average stock value | MATDOC movement 601, MBEW |
| Stockout rate | Share of SKU-plant-days with open demand and zero unrestricted stock | stock\_daily, VBAP |
| No movement | Unrestricted stock above zero and no goods movement in 28 days | MARD, MATDOC |

**Exception rules**

| ID | Fires when | Severity | Recommended action |
| --- | --- | --- | --- |
| EXC-01 Stockout before replenishment | Projected available stock (on hand + open PO quantity due by day t − cumulative forecast to t) drops below zero at some t within the vendor's p80 actual lead time | Critical if A-class and 3 days or less; high if 7 days or less; else medium | Expedite the open PO, or raise a PO now at the proposed quantity |
| EXC-02 Late PO line | Delivery date (EKET-EINDT) is before today and received quantity is below scheduled quantity | Critical if A-class and 7 or more days late; high if 3 or more days late; else medium | Chase the vendor; email drafted |
| EXC-03 PO line likely late | PO date + the vendor's p80 actual lead time is after the delivery date; not yet late | Medium | Ask the vendor to confirm the date |
| EXC-04 Excess stock | Days of cover above 90 (A and B) or 120 (C) | Low; medium if stock value is in the top 10% | Pause open POs or reallocate between plants |
| EXC-05 No movement 28 days | Stock above zero and no goods movement in 28 days | Low | Review for markdown or return to vendor (movement 122) |
| EXC-06 Delivery block due soon | Sales order delivery block (VBAK-LIFSK) is set and the requested date (VBEP-EDATU) is within 3 days | High | Release the block in VA02 or tell the customer |
| EXC-07 Delivered, not billed | Goods issue posted (LIKP-WADAT\_IST) and no billing document in the document flow after 2 days | High | Create billing in VF01 or check the billing block |
| EXC-08 Vendor slipping | 30-day OTIF below 85%, or 10 points or more below the vendor's 90-day OTIF | High | Escalate and review the scorecard |

Service-level targets by ABC class: A 98%, B 95%, C 90%. ABC uses 365-day revenue share (A top 80%, B next 15%, C last 5%); XYZ uses the variability of weekly demand (TRD).

## Success metrics

Product targets are measured in the backtest and the 60-day replay; publish the numbers you get, including misses.

| Metric | Target | How measured |
| --- | --- | --- |
| Stockouts flagged early | 70% or more of simulated stockouts flagged 7+ days ahead | Replay EXC-01 against actual stockout days |
| False stockout alerts | 30% or fewer of EXC-01 alerts without a stockout or an expedite | Same replay |
| Forecast gain | Model WAPE at least 10% below seasonal-naive on A-class SKUs | Holdout fold |
| Grounding | Zero unsupported numbers across 60 published briefs; fallback rate reported | Verifier eval file |
| Speed | Landing page under 3 s on a mid-range phone on 4G; exceptions table under 2 s | Lighthouse and a manual check |
| Cost | $0 per month to run | Billing pages |

**Career metrics** (what the project is for):

- 5 LinkedIn posts by 2026-11-11, each with a picture.
- At least one recruiter or hiring-manager conversation a week from week 3.
- Used in 15 or more applications; 2 or more interviews by 2026-11-30.

## Milestones

Four one-week milestones; each ends with a deployed site and a LinkedIn post, so a slip never leaves you with nothing to show.

1. **M1 · Oct 15–21 · Data foundation.** SAP tables generated, data dictionary written, KPI views built, Overview page live on GitHub Pages.
   - Exit: CI green; two runs with the same seed produce identical file hashes.
2. **M2 · Oct 22–28 · Forecast and inventory.** Backtest report, safety stock and reorder points, Inventory page, Excel plan.
   - Exit: backtest table committed; the workbook opens with working formulas.
3. **M3 · Oct 29–Nov 4 · Suppliers, exceptions, AI.** Scorecard, the eight rules, CP-SAT proposals, 60 daily briefs.
   - Exit: the grounding eval shows zero unsupported numbers; Exceptions, Suppliers, O2C and Brief pages live.
4. **M4 · Nov 5–11 · Polish and launch.** Power BI report, SAP functional pack, case study, video, landing page.
   - Exit: every box in the TRD definition of done is ticked.

If time runs short, cut in this order: Stretch items, then the third Power BI page, then the O2C page. Never cut drill-down or the grounding check; they are the differentiators.

## Risks and open questions

The biggest risk is time: four weeks, part-time, beside a final year and a job. The cut order under Milestones is the answer to it.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Scope creep | Launch slips past Nov 11 | Stretch only after MVP done; weekly cut review |
| Simulation looks fake | SAP or SC people dismiss it | Publish ASSUMPTIONS.md; plausible lead times and fill rates; label "simulated" on every page |
| Free LLM limits (Groq free tier: 1,000 requests/day, 8,000 tokens/min per model) | Briefs not generated | One call per day covers brief + emails; cache results in the repo; pace calls under the token cap; template fallback ships without a key |
| M5 data terms | Takedown request | Download M5 in CI; do not re-host the raw files; publish only simulated and aggregated outputs |
| Broken or sleeping link | Recruiter sees nothing | Static hosting; CI link check; no server on the click path |
| SAP fidelity questioned | Credibility | Standard table and field names; dictionary lists simplifications (one company code, no pricing conditions, no MRP run) |
| Trademark confusion | Looks like an official SAP product | No SAP logos or trademarks; say "SAP S/4HANA-style tables"; footer on every page: "Not affiliated with SAP SE. Simulated data." |

**Open questions**

- [x] Final project name: S4 Control Tower
- [x] Power BI only (no Tableau). The .pbix and video ship in the repo; the static site is the live link
- [x] Store mapping: all 10 M5 stores are customers; CA stores are served by plant P001 and TX/WI stores by P002

## Demo script and launch

The 90-second video follows the recruiter's questions in order: what is it, does it work, can I trust it, is it SAP.

1. **0–10 s.** "A distributor's planner opens this every morning. Here is what will go wrong this week." Show the Exceptions page.
2. **10–30 s.** Click a critical EXC-01 row: the stock projection crosses zero before the open PO lands. Open the drill-down and show the EKET and MATDOC rows behind it.
3. **30–45 s.** Download the Excel plan, change one quantity and watch days of cover update.
4. **45–60 s.** Suppliers page: a vendor graded D, its OTIF falling, and the drafted chase email.
5. **60–75 s.** The daily brief, then the verifier report: zero unsupported numbers in 60 days.
6. **75–90 s.** The SAP functional spec and UAT cases, then the backtest numbers and the repo link.

**Launch package:** a landing page with three headline numbers from your own backtest, the video, CASE\_STUDY.md (problem, approach, results, limits, one page), and a LinkedIn post that links the site, not the repo.
