# S4 Control Tower

A free, static supply-planning demo on SAP S/4HANA-style tables: which SKUs will stock out, which PO lines are late, which vendors are slipping, which deliveries are stuck, plus drafted follow-up emails. Every number comes from SQL; the AI only writes the words around them.

Built from public M5 demand data plus a documented, seeded simulation. **Not affiliated with SAP SE. Simulated data.**

- Product spec: [PRD.md](PRD.md) · Technical design: [TRD.md](TRD.md) · Simulation choices: [ASSUMPTIONS.md](ASSUMPTIONS.md)
- Status: M1 (data foundation) in progress.

## Run it locally (Windows PowerShell)

```powershell
setx PYTHONUTF8 1                 # once, then reopen PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock

python tasks.py data              # download M5 (cached in data\), pick SKUs, simulate the SAP tables
python tasks.py data --config pipeline\config.small.yaml     # 50-SKU quick run
pytest -q
```

## Layout

```text
tasks.py            build runner: python tasks.py all | ingest | data | models | ...
pipeline/           Python + SQL pipeline (config.yaml, ingest, simulate, sql, forecast, policy, ...)
web/                static React site (M1+)
powerbi/            Power BI report and screenshots (M4)
sap-pack/           functional spec, process maps, UAT cases (M4)
eval/               backtest, policy replay and brief-verifier results
```
