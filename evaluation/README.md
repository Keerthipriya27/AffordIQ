# Evaluation Framework

The evaluation tools use only the Python standard library and run from the
repository root after a clean clone.

```powershell
python evaluation/evaluate.py
```

Optional paths:

```powershell
python evaluation/evaluate.py `
  --output output.csv `
  --requests dataset/prediction_requests.csv `
  --expected dataset/sample_requests.csv `
  --stats validation_statistics.json
```

The evaluator writes `metrics.json`, `evaluation_report.md`, and
`usage_report.md` beside these scripts. It validates the strict eight-column
schema, request coverage, statuses, methods, payment-plan syntax, arithmetic,
dates, safe amounts, spending changes, and explanation consistency. It also
reports difficult requests and categorized failures.

Sample comparison is performed only for matching request IDs and fields that
are present in the expected file. Missing or non-overlapping sample IDs are
reported as non-comparable rather than treated as incorrect predictions.

Model usage is read from either the current pipeline telemetry
(`token_usage`, `gemini_calls`) or the normalized `model_usage` format.
Missing telemetry is reported as zero; no credential or API key is read or
emitted. All scripts use only the Python standard library.