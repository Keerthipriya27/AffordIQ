# Evaluation Report

- Requests: 250
- Rows evaluated: 250
- Status accuracy: None
- Payment method accuracy: None
- Payment-plan validity: 100.00%
- Safe amount MAE: None
- Earliest-date accuracy: None
- Spending-change validity: 100.00%
- Explanation consistency: 100.00%
- Difficult requests: 0

## Failure Categories

- schema: 0
- duplicate_request_id: 0
- missing_request_id: 0
- unexpected_request_id: 0
- blank_request_id: 0
- invalid_status: 0
- invalid_payment_method: 0
- malformed_plan: 0
- arithmetic: 0
- safe_amount: 0
- safety: 0
- earliest_date: 0
- spending_change: 0
- explanation_consistency: 0

## Model Usage

{
  "provider": "Google Gemini",
  "model_name": "gemini-2.5-flash",
  "calls": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "total_tokens": 0,
  "average_tokens_per_request": 0.0,
  "estimated_total_cost_usd": 0.0,
  "estimated_cost_per_request_usd": 0.0
}
