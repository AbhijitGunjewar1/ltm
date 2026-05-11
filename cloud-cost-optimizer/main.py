#!/usr/bin/env python3
"""
GCP Cloud Cost Optimizer — main entry point.
Project: gcpopenshift

Usage:
    python main.py                        # full analysis
    python main.py --project my-project   # override project
    python main.py --no-export            # skip CSV/JSON export
"""

import sys
import argparse
import traceback

from config import PROJECT_ID, CREDENTIALS_PATH, MONTHS_BACK
from modules.auth import get_access_token
from modules.vm_inventory import list_all_vms, print_vm_table
from modules.metrics_analyzer import (
    fetch_cpu_metrics,
    fetch_memory_metrics,
    build_monthly_breakdown,
    classify_vm,
)
from modules.cost_calculator import (
    estimate_monthly_cost,
    suggest_rightsized_type,
    compute_savings,
)
from modules.report_generator import (
    print_header,
    print_vm_analysis_table,
    print_monthly_breakdown,
    print_savings_summary,
    print_recommendations,
    export_csv,
    export_json,
)


def parse_args():
    p = argparse.ArgumentParser(description="GCP Cloud Cost Optimizer")
    p.add_argument("--project",    default=PROJECT_ID, help="GCP project ID")
    p.add_argument("--creds",      default=CREDENTIALS_PATH, help="Service account JSON path")
    p.add_argument("--no-export",  action="store_true", help="Skip CSV/JSON export")
    p.add_argument("--no-memory",  action="store_true", help="Skip memory metrics (faster)")
    p.add_argument("--running-only", action="store_true", help="Analyse only RUNNING VMs")
    return p.parse_args()


def main():
    args = parse_args()
    project_id = args.project

    print(f"\nGCP Cloud Cost Optimizer")
    print(f"Project : {project_id}")
    print(f"Period  : last {MONTHS_BACK} months\n")

    # ── 1. Auth ───────────────────────────────────────────────────────────────
    print("[1/5] Authenticating...")
    try:
        token = get_access_token(args.creds)
    except Exception as e:
        print(f"\nERROR: Authentication failed.\n{e}")
        print("\nSetup options:")
        print("  A) Place service-account.json in ./credentials/ and re-run.")
        print("  B) Run:  gcloud auth application-default login")
        print("  C) Set:  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json\n")
        sys.exit(1)

    # ── 2. VM Inventory ───────────────────────────────────────────────────────
    print(f"[2/5] Fetching VM inventory for project '{project_id}'...")
    try:
        all_vms = list_all_vms(token, project_id)
    except Exception as e:
        print(f"\nERROR: Could not list VMs. Check project ID and IAM permissions.\n{e}")
        sys.exit(1)

    if not all_vms:
        print("No VMs found in this project.")
        sys.exit(0)

    if args.running_only:
        vms = [v for v in all_vms if v["status"] == "RUNNING"]
        print(f"  Found {len(all_vms)} total VMs, {len(vms)} RUNNING.")
    else:
        vms = all_vms
        running = sum(1 for v in vms if v["status"] == "RUNNING")
        stopped = len(vms) - running
        print(f"  Found {len(vms)} VMs ({running} RUNNING, {stopped} STOPPED/TERMINATED).")

    print("\n  Full VM inventory:")
    print_vm_table(vms)

    # ── 3. Metrics ────────────────────────────────────────────────────────────
    print(f"\n[3/5] Pulling Cloud Monitoring metrics (last {MONTHS_BACK} months)...")
    cpu_metrics = fetch_cpu_metrics(token, project_id)

    mem_metrics: dict = {}
    if not args.no_memory:
        mem_metrics = fetch_memory_metrics(token, project_id)

    monthly_data = build_monthly_breakdown(token, project_id)

    # ── 4. Analysis ───────────────────────────────────────────────────────────
    print("\n[4/5] Analysing and computing optimisation opportunities...")
    vms_analysis: list[dict] = []

    for vm in vms:
        name = vm["name"]
        cpu  = cpu_metrics.get(name, {})
        mem  = mem_metrics.get(name)

        classification, reason = classify_vm(cpu, mem)

        monthly_cost = estimate_monthly_cost(vm["vcpus"], vm["ram_gb"], vm["machine_type"])

        stype, scost = suggest_rightsized_type(
            vm["machine_type"],
            cpu.get("avg"),
            mem.get("avg") if mem else None,
            vm["vcpus"],
            vm["ram_gb"],
        )

        vms_analysis.append({
            **vm,
            "cpu_avg":  cpu.get("avg"),
            "cpu_max":  cpu.get("max"),
            "cpu_min":  cpu.get("min"),
            "cpu_p95":  cpu.get("p95"),
            "mem_avg":  mem.get("avg") if mem else None,
            "mem_max":  mem.get("max") if mem else None,
            "monthly_cost":          monthly_cost,
            "classification":        classification,
            "reason":                reason,
            "suggested_type":        stype,
            "suggested_type_cost":   scost,
        })

    savings = compute_savings(vms_analysis)

    # ── 5. Report ─────────────────────────────────────────────────────────────
    print("\n[5/5] Generating report...\n")
    print_header(project_id, len(vms))
    print_vm_analysis_table(vms_analysis)
    print_monthly_breakdown(monthly_data, vms_analysis)
    print_savings_summary(savings)
    print_recommendations(vms_analysis)

    if not args.no_export:
        csv_path  = export_csv(vms_analysis, monthly_data, project_id)
        json_path = export_json(vms_analysis, savings, project_id)
        print(f"  Reports saved:")
        print(f"    CSV  : {csv_path}")
        print(f"    JSON : {json_path}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
