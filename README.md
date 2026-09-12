# AffordIQ

**Buy with confidence, not guesswork.**

AffordIQ is a financial decision-intelligence engine for the HackerRank
Orchestrate "Buy or Wait?" challenge. The Python backend reconstructs financial
state, resolves evidence, simulates 90-day cashflow, ranks eligible plans, and
writes the strict output file. The React frontend is a read-only presentation
layer over those generated artifacts; it does not implement financial
decision logic.

## Run the backend pipeline

From the repository root:

```powershell
python -m code.main --dataset-dir dataset --output output.csv --requests-file prediction_requests.csv
```

This produces `output.csv`, `output_optimizer.csv`,
`candidate_plan_diagnostics.json`, `validation_statistics.json`, and the
frontend-safe `dashboard_data.json`.

The decision path is deliberately staged:

1. Load and validate structured requests, profiles, events, payment options,
   messages, images, and exchange rates.
2. Extract evidence from messages/images (deterministically first, with Gemini
   only for ambiguous evidence).
3. Resolve evidence into a deterministic financial state.
4. Simulate the 90-day balance trajectory.
5. Generate, simulate, and rank eligible payment plans deterministically.
6. Validate and repair the structured result with the adversarial validator.
7. Optionally ask Gemini to rewrite only the grounded explanation; it cannot
   alter amounts, dates, status, payment method, or plan.
8. Serialize the CSV and audit the file that was actually written.

Thus Gemini is never used as the decision-maker: the financial state,
simulation, optimization, and safety checks remain deterministic.

## Run evaluation

```powershell
python evaluation/evaluate.py
```

The evaluator writes `evaluation/metrics.json`,
`evaluation/evaluation_report.md`, and `evaluation/usage_report.md`.

## Run the frontend

Install dependencies and start Vite:

```powershell
npm install
npm run dev
```

Open `http://localhost:3000`.

The frontend consumes backend-generated `output.csv`,
`validation_statistics.json`, and `dashboard_data.json`. Do not put API keys in
frontend code. Gemini credentials, when used by the evidence layer, must be
provided only through the runtime environment.

## Tests

```powershell
python -m unittest discover -s code -p "test_*.py"
npm run lint
npm run build
```

## Submission packaging

Do not archive the repository root. A submission archive must be created from
an allowlist and must exclude `dataset/`, `node_modules/`, `dist/`, `.cache/`,
logs, local environment files, and credentials. Keep `evaluation/` and the
generated `output.csv` in the submission only when the challenge rules
require them.
