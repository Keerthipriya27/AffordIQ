"""
Main pipeline execution script for Buy or Wait financial reasoning engine.
"""
import sys
import time
import argparse
from pathlib import Path
from decimal import Decimal
import csv
from collections import Counter
from datetime import date, timedelta

from code.config import (
    DATASET_DIR, MEDIA_IMAGES_DIR, OUTPUT_PATH, setup_logging
)
from code.schema_validator import SchemaValidator
from code.data_loader import DataLoader
from code.currency import CurrencyConverter
from code.evidence_extractor import EvidenceExtractor
from code.conflict_resolver import ConflictResolver
from code.financial_state import FinancialStateReconstructor
from code.simulator import BalanceSimulator
from code.plan_ranker import PlanRanker
from code.explainer import PlanExplainer
from code.output_validator import OutputValidator, REQUIRED_OUTPUT_HEADERS
from code.optimizer import PaymentPlanOutputMapper, OPTIMIZER_OUTPUT_HEADERS, OptimizerOutputRow
from code.adversarial_validator import StrictAdversarialValidator, FatalValidationError
import json

logger = setup_logging("main_pipeline")

def run_pipeline(
    dataset_dir: Path = DATASET_DIR,
    output_path: Path = OUTPUT_PATH,
    requests_file: str = "prediction_requests.csv"
) -> dict:
    start_time = time.time()
    logger.info("=====================================================")
    logger.info("Starting Buy or Wait Financial Reasoning Engine")
    logger.info(f"Dataset dir: {dataset_dir}")
    logger.info(f"Output path: {output_path}")
    logger.info("=====================================================")

    # 1. Validate Schema
    if not SchemaValidator.validate_dataset_directory(dataset_dir):
        logger.error("Dataset schema validation failed. Aborting pipeline.")
        return {"status": "SCHEMA_ERROR"}

    # 2. Ingest Data
    loader = DataLoader(dataset_dir)
    requested_path = dataset_dir / requests_file
    if not requested_path.exists() and requests_file == "requests.csv":
        fallback_path = dataset_dir / "prediction_requests.csv"
        if fallback_path.exists():
            logger.warning(
                "dataset/requests.csv was not found; using dataset/prediction_requests.csv "
                "as the available production request source."
            )
            requests_file = "prediction_requests.csv"
    profiles = loader.load_profiles()
    raw_events = loader.load_events()
    messages = loader.load_messages()
    images = loader.load_images()
    options_by_req = loader.load_payment_options()
    exchange_rates = loader.load_exchange_rates()
    requests = loader.load_requests(requests_file)

    if not requests:
        logger.error(f"No requests found to process in {requests_file}!")
        return {"status": "NO_REQUESTS"}

    # Group events, messages, images by user_id
    events_by_user = {}
    for ev in raw_events:
        events_by_user.setdefault(ev.user_id, []).append(ev)

    messages_by_user = {}
    for msg in messages:
        messages_by_user.setdefault(msg.user_id, []).append(msg)

    images_by_user = {}
    for img in images:
        images_by_user.setdefault(img.user_id, []).append(img)

    # 3. Initialize Core Engines
    converter = CurrencyConverter(exchange_rates)
    extractor = EvidenceExtractor()
    resolver = ConflictResolver(extractor)
    reconstructor = FinancialStateReconstructor(converter)
    simulator = BalanceSimulator(converter)
    ranker = PlanRanker(simulator)
    strict_validator = StrictAdversarialValidator(simulator, converter, options_by_req)

    optimizer_rows = []
    dashboard_users = {}
    request_user_ids = {}
    request_details = {}
    processed_count = 0
    image_request_ids = set()
    message_request_ids = set()

    media_dir = dataset_dir / "media" / "images"

    # 4. Process Each Request
    for req in requests:
        logger.info(f">>> Processing Request {req.request_id} for User {req.user_id} (Amount: {req.amount} {req.currency})")

        profile = profiles.get(req.user_id)
        if not profile:
            logger.error(f"Profile not found for user {req.user_id}! Skipping request {req.request_id}")
            continue
        request_user_ids[req.request_id] = req.user_id
        request_details[req.request_id] = {
            "item_name": req.item_name,
            "amount": str(req.amount),
            "currency": req.currency,
            "request_date": req.request_date.isoformat(),
            "desired_completion_date": req.desired_completion_date.isoformat() if req.desired_completion_date else None,
        }

        user_events = events_by_user.get(req.user_id, [])
        user_messages = messages_by_user.get(req.user_id, [])
        user_images = images_by_user.get(req.user_id, [])

        event_ids = {event.event_id for event in user_events}
        if any(
            image.related_event_id in event_ids
            or any(event.image_id == image.image_id for event in user_events)
            for image in user_images
        ):
            image_request_ids.add(req.request_id)
        if user_messages:
            message_request_ids.add(req.request_id)

        # Stage A: Resolve Conflicts & Blank Amounts (Image > Message > Event)
        resolved_events = resolver.resolve_events(user_events, user_messages, user_images, media_dir)

        # Stage B: Reconstruct Financial State
        fin_state = reconstructor.reconstruct(profile, resolved_events)
        if req.user_id not in dashboard_users:
            baseline = simulator.simulate(fin_state, req.request_date)
            dashboard_users[req.user_id] = {
                "user_id": profile.user_id,
                "base_currency": profile.base_currency,
                "current_balance": str(profile.current_balance),
                "minimum_balance_to_keep": str(profile.minimum_balance_to_keep),
                "monthly_essential_expenses": str(profile.monthly_essential_expenses),
                "monthly_flexible_expenses": str(profile.monthly_flexible_expenses),
                "risk_tolerance": profile.risk_tolerance,
                "forecast": [
                    {
                        "date": (req.request_date + timedelta(days=index)).isoformat(),
                        "balance": str(balance)
                    }
                    for index, balance in enumerate(baseline.daily_balances)
                ],
                "events": [
                    {
                        "event_id": event.event_id,
                        "category": event.category,
                        "event_type": event.event_type,
                        "amount": str(event.amount) if event.amount is not None else None,
                        "currency": event.currency,
                        "frequency": event.frequency,
                        "start_date": event.start_date.isoformat(),
                        "status": event.status,
                        "is_essential": event.is_essential,
                    }
                    for event in resolved_events
                ],
                "ignored_events_summary": fin_state.ignored_events_summary,
            }

        # Stage C: Retrieve payment options
        options = options_by_req.get(req.request_id, [])

        # Stage D: Simulate & Rank Candidate Plans using Candidate Payment-Plan Optimizer
        optimized_plan = ranker.evaluate_request_optimized(req, fin_state, options)
        earliest_full_date = ranker.optimizer.find_earliest_date_for_full_payment(req, fin_state)
        amount_safe = ranker.optimizer.calculate_amount_safe_to_pay(req, fin_state, optimized_plan)
        all_diags = ranker.optimizer.get_diagnostics_for_request(req.request_id)

        # Stage E & F: Map via PaymentPlanOutputMapper
        raw_optimizer_output = PaymentPlanOutputMapper.map_to_output(
            request=req,
            winning_plan=optimized_plan,
            state=fin_state,
            earliest_full_date=earliest_full_date,
            amount_safe_to_pay=amount_safe,
            all_diagnostics=all_diags
        )

        # Stage G: Strict Adversarial Validation & Deterministic Repair Layer
        validated_optimizer_output = strict_validator.validate_and_repair(
            row=raw_optimizer_output,
            request=req,
            state=fin_state
        )

        # Stage H: Optional Gemini explanation over the already validated result.
        # The model can only rewrite grounded facts; it never participates in
        # affordability, simulation, ranking, or output-field decisions.
        validated_optimizer_output.decision_explanation = extractor.generate_grounded_explanation(
            source_id=f"explanation_{req.request_id}",
            grounded_facts={
                "request_id": req.request_id,
                "item_name": req.item_name,
                "requested_amount": str(req.amount),
                "currency": req.currency,
                "affordability_status": validated_optimizer_output.affordability_status,
                "recommended_payment_method": validated_optimizer_output.recommended_payment_method,
                "amount_safe_to_pay": validated_optimizer_output.amount_safe_to_pay,
                "payment_plan": validated_optimizer_output.payment_plan,
                "earliest_date_for_full_payment": validated_optimizer_output.earliest_date_for_full_payment,
                "spending_changes_needed": validated_optimizer_output.spending_changes_needed,
                "minimum_balance": str(profile.minimum_balance_to_keep),
                "forecast_horizon_days": 90,
                "minimum_projected_cushion": (
                    str(validated_optimizer_output.winning_plan.simulation.min_cushion_observed)
                    if validated_optimizer_output.winning_plan
                    else None
                ),
            },
            fallback=validated_optimizer_output.decision_explanation,
        )
        
        optimizer_rows.append(validated_optimizer_output)
        processed_count += 1

    # 5. Write the exact strict eight-column output schema.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OPTIMIZER_OUTPUT_HEADERS)
        writer.writeheader()
        for row in optimizer_rows:
            writer.writerow(row.to_dict())

    # 6. Keep the optimizer-named copy for existing consumers.
    optimizer_output_path = output_path.parent / "output_optimizer.csv"
    with open(optimizer_output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OPTIMIZER_OUTPUT_HEADERS)
        writer.writeheader()
        for r in optimizer_rows:
            writer.writerow(r.to_dict())
            
    # 7. Save candidate plan diagnostics JSON for inspection of rejected plans
    diagnostics_path = output_path.parent / "candidate_plan_diagnostics.json"
    diagnostics_payload = {
        r.request_id: [d.to_dict() for d in r.all_diagnostics]
        for r in optimizer_rows
    }
    with open(diagnostics_path, "w", encoding="utf-8") as f:
        json.dump(diagnostics_payload, f, indent=2)

    dashboard_path = output_path.parent / "dashboard_data.json"
    with open(dashboard_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": date.today().isoformat(),
            "users": dashboard_users,
            "request_user_ids": request_user_ids,
            "request_details": request_details,
            "evidence": {
                "image_request_ids": sorted(image_request_ids),
                "message_request_ids": sorted(message_request_ids),
            },
        }, f, indent=2)

    # 8. Run an independent audit against the file that was actually written.
    audit = _audit_output_file(output_path, optimizer_rows, requests, strict_validator)
    validation_failures = audit["total_failures"]
    if validation_failures:
        raise FatalValidationError(
            f"Final output audit failed: {audit}"
        )

    # 9. Save Validation Statistics JSON
    validation_stats_path = output_path.parent / "validation_statistics.json"
    val_stats_dict = strict_validator.stats.to_dict()
    val_stats_dict["final_audit"] = audit
    with open(validation_stats_path, "w", encoding="utf-8") as f:
        json.dump(val_stats_dict, f, indent=2)

    runtime = time.time() - start_time

    # Report Metrics
    metrics = {
        "number_of_requests": len(requests),
        "number_successfully_processed": processed_count,
        "number_of_validation_failures": validation_failures,
        "final_audit": audit,
        "validation_statistics": val_stats_dict,
        "requests_requiring_image_extraction": len(image_request_ids),
        "requests_requiring_message_interpretation": len(message_request_ids),
        "runtime_seconds": round(runtime, 3),
        "gemini_calls": extractor.gemini_calls,
        "token_usage": {
            "input_tokens": extractor.input_tokens,
            "output_tokens": extractor.output_tokens,
            "total_tokens": extractor.input_tokens + extractor.output_tokens
        },
        "estimated_cost_usd": round(extractor.estimated_cost, 5)
    }
    metrics["average_cost_per_request_usd"] = round(
        extractor.estimated_cost / max(1, len(requests)), 5
    )

    logger.info("=====================================================")
    logger.info("Execution Summary:")
    for k, v in metrics.items():
        if k == "validation_statistics":
            logger.info("  Validation Statistics:")
            for vk, vv in v.items():
                if vk not in ["repairs_sample", "fallbacks_sample"]:
                    logger.info(f"    - {vk}: {vv}")
        else:
            logger.info(f"  {k}: {v}")
    logger.info(f"Output saved to: {output_path}")
    logger.info(f"Optimizer output saved to: {optimizer_output_path}")
    logger.info(f"Validation statistics saved to: {validation_stats_path}")
    logger.info("=====================================================")

    return metrics


def _audit_output_file(
    output_path: Path,
    rows: list,
    requests: list,
    strict_validator: StrictAdversarialValidator
) -> dict:
    """Audit the serialized strict output and its validated internal plans."""
    with open(output_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        serialized_rows = list(reader)
        header = reader.fieldnames

    request_ids = [request.request_id for request in requests]
    written_ids = [row.get("request_id", "") for row in serialized_rows]
    duplicate_ids = sorted(request_id for request_id, count in Counter(written_ids).items() if count > 1)
    missing_ids = sorted(set(request_ids) - set(written_ids))
    invalid_statuses = sum(row.get("affordability_status") not in {
        "affordable", "affordable_with_delay", "affordable_with_spending_changes",
        "affordable_with_delay_and_spending_changes", "partially_affordable", "not_affordable"
    } for row in serialized_rows)
    invalid_methods = sum(row.get("recommended_payment_method") not in {
        "full_payment", "partial_payment", "installments", "wait", "not_recommended"
    } for row in serialized_rows)

    malformed_plans = 0
    arithmetic_failures = 0
    safety_failures = 0
    for row, serialized in zip(rows, serialized_rows):
        if not strict_validator._verify_payment_plan_syntax(row):
            malformed_plans += 1
        plan = row.winning_plan
        if plan and plan.schedule:
            schedule = plan.schedule
            if sum(schedule.due_amounts) != schedule.total_nominal_cost:
                arithmetic_failures += 1
            if row.recommended_payment_method != "not_recommended" and not plan.simulation.is_safe:
                safety_failures += 1

    header_failure = int(header != OPTIMIZER_OUTPUT_HEADERS)
    row_count_failure = int(len(serialized_rows) != len(requests))
    total_failures = (
        header_failure + row_count_failure + len(duplicate_ids) + len(missing_ids)
        + invalid_statuses + invalid_methods + malformed_plans
        + arithmetic_failures + safety_failures
    )
    return {
        "total_requests": len(requests),
        "rows_written": len(serialized_rows),
        "duplicate_request_ids": duplicate_ids,
        "missing_request_ids": missing_ids,
        "invalid_statuses": invalid_statuses,
        "invalid_payment_methods": invalid_methods,
        "malformed_plans": malformed_plans,
        "arithmetic_failures": arithmetic_failures,
        "safety_failures": safety_failures,
        "header_failure": header_failure,
        "row_count_failure": row_count_failure,
        "total_failures": total_failures,
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Buy or Wait Financial Engine")
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--requests-file", type=str, default="requests.csv")
    args = parser.parse_args()

    run_pipeline(args.dataset_dir, args.output, args.requests_file)
