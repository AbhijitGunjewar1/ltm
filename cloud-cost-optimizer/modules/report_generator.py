"""
Generate a detailed cost optimization report — both console and CSV outputs.
"""

import os
import csv
import json
from datetime import datetime, timezone
from tabulate import tabulate
from colorama import Fore, Style, init as colorama_init
from config import REPORTS_DIR, MONTHS_BACK, ANALYSIS_START, ANALYSIS_END

colorama_init(autoreset=True)

STATUS_COLORS = {
    "IDLE":             Fore.RED,
    "OVER_PROVISIONED": Fore.YELLOW,
    "UNDER_PROVISIONED":Fore.MAGENTA,
    "OPTIMAL":          Fore.GREEN,
    "NO_DATA":          Fore.WHITE,
}


def _col(text: str, classification: str) -> str:
    color = STATUS_COLORS.get(classification, "")
    return f"{color}{text}{Style.RESET_ALL}"


def print_header(project_id: str, total_vms: int) -> None:
    print("\n" + "=" * 80)
    print(f"  GCP CLOUD COST OPTIMIZATION REPORT")
    print(f"  Project   : {project_id}")
    print(f"  Period    : {ANALYSIS_START.strftime('%Y-%m-%d')} → {ANALYSIS_END.strftime('%Y-%m-%d')}  ({MONTHS_BACK} months)")
    print(f"  Total VMs : {total_vms}")
    print(f"  Generated : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80 + "\n")


def print_vm_analysis_table(vms_analysis: list[dict]) -> None:
    print(f"\n{'─'*80}")
    print("  VM ANALYSIS — CPU & MEMORY UTILIZATION")
    print(f"{'─'*80}\n")

    rows = []
    for v in vms_analysis:
        cls   = v.get("classification", "NO_DATA")
        cpu   = v.get("cpu_avg")
        mem   = v.get("mem_avg")
        cost  = v.get("monthly_cost")
        stype = v.get("suggested_type")
        scost = v.get("suggested_type_cost")

        rows.append([
            _col(v["name"][:30], cls),
            v["zone"][-12:],
            v["machine_type"],
            v.get("vcpus", "?"),
            f'{v.get("ram_gb","?")} GB',
            f"{cpu:.1f}%" if cpu is not None else "N/A",
            f"{mem:.1f}%" if mem is not None else "N/A",
            f"${cost:.2f}" if cost else "N/A",
            _col(cls, cls),
            stype or "—",
            f"${scost:.2f}" if scost else "—",
        ])

    print(
        tabulate(
            rows,
            headers=[
                "VM Name", "Zone", "Machine Type", "vCPU", "RAM",
                "CPU avg", "Mem avg", "Est $/mo",
                "Classification", "Suggested Type", "Saved $/mo",
            ],
            tablefmt="github",
        )
    )


def print_monthly_breakdown(monthly_data: dict[str, list], vms_analysis: list[dict]) -> None:
    print(f"\n{'─'*80}")
    print("  MONTHLY CPU UTILIZATION BREAKDOWN (last 10 months)")
    print(f"{'─'*80}\n")

    # Collect all months
    all_months: set[str] = set()
    for series in monthly_data.values():
        for entry in series:
            all_months.add(entry["month"])
    months_sorted = sorted(all_months)[-10:]   # last 10

    vm_cls = {v["name"]: v.get("classification", "NO_DATA") for v in vms_analysis}

    rows = []
    for vm_name, series in monthly_data.items():
        by_month = {e["month"]: e["avg_cpu"] for e in series}
        cls = vm_cls.get(vm_name, "NO_DATA")
        row = [_col(vm_name[:28], cls)]
        for m in months_sorted:
            val = by_month.get(m)
            row.append(f"{val:.1f}%" if val is not None else "—")
        rows.append(row)

    print(
        tabulate(
            rows,
            headers=["VM Name"] + months_sorted,
            tablefmt="github",
        )
    )


def print_savings_summary(savings: dict) -> None:
    print(f"\n{'─'*80}")
    print("  COST SAVINGS SUMMARY")
    print(f"{'─'*80}\n")

    rows = [
        ["Current monthly cost (all VMs)",          f"${savings['total_current_monthly_usd']:>10,.2f}"],
        ["Optimized monthly cost",                   f"${savings['total_optimized_monthly_usd']:>10,.2f}"],
        ["Monthly savings potential",                f"${savings['total_savings_monthly_usd']:>10,.2f}"],
        [f"10-month cumulative savings",             f"${savings['total_savings_10month_usd']:>10,.2f}"],
        ["  ↳ from shutting down IDLE VMs",         f"${savings['idle_savings_monthly_usd']:>10,.2f}/mo"],
        ["  ↳ from rightsizing OVER_PROVISIONED",   f"${savings['rightsize_savings_monthly_usd']:>10,.2f}/mo"],
        ["Savings percentage",                       f"{savings['savings_pct']:>10.1f}%"],
    ]
    print(tabulate(rows, tablefmt="plain", colalign=("left", "right")))
    print()


def print_recommendations(vms_analysis: list[dict]) -> None:
    print(f"\n{'─'*80}")
    print("  PRIORITISED RECOMMENDATIONS")
    print(f"{'─'*80}\n")

    idle   = [v for v in vms_analysis if v.get("classification") == "IDLE"]
    overp  = [v for v in vms_analysis if v.get("classification") == "OVER_PROVISIONED"]
    underp = [v for v in vms_analysis if v.get("classification") == "UNDER_PROVISIONED"]
    nodata = [v for v in vms_analysis if v.get("classification") == "NO_DATA"]

    if idle:
        print(Fore.RED + "  [P1] IDLE VMs — Shut down or delete immediately" + Style.RESET_ALL)
        for v in idle:
            cost = v.get("monthly_cost", 0) or 0
            print(f"       • {v['name']} ({v['zone']})  CPU avg: {v.get('cpu_avg', 0):.1f}%  "
                  f"Est saving: ${cost:.2f}/mo")
        print()

    if overp:
        print(Fore.YELLOW + "  [P2] OVER-PROVISIONED VMs — Rightsize to smaller machine type" + Style.RESET_ALL)
        for v in overp:
            saving = (v.get("monthly_cost") or 0) - (v.get("suggested_type_cost") or v.get("monthly_cost") or 0)
            stype  = v.get("suggested_type") or "smaller type"
            print(f"       • {v['name']} ({v['machine_type']} → {stype})  "
                  f"CPU avg: {v.get('cpu_avg', 0):.1f}%  "
                  f"Potential saving: ${saving:.2f}/mo")
        print()

    if underp:
        print(Fore.MAGENTA + "  [P3] UNDER-PROVISIONED VMs — Consider upsizing or load distribution" + Style.RESET_ALL)
        for v in underp:
            print(f"       • {v['name']} ({v['machine_type']})  CPU avg: {v.get('cpu_avg', 0):.1f}%")
        print()

    if nodata:
        print(Fore.WHITE + "  [INFO] VMs with no metrics (RUNNING but no data — check monitoring)" + Style.RESET_ALL)
        for v in nodata:
            print(f"       • {v['name']} ({v['zone']}, {v['machine_type']})")
        print()

    print("  Additional general recommendations:")
    print("  • Enable Committed Use Discounts (CUDs) for stable workloads → 37–57% savings")
    print("  • Use Spot/Preemptible VMs for fault-tolerant batch jobs → up to 91% savings")
    print("  • Schedule non-prod VMs to shut down outside working hours (8 hrs/day = 67% saving)")
    print("  • Review and delete unattached persistent disks")
    print("  • Use Cloud Monitoring Budget Alerts to catch unexpected spend early\n")


def export_csv(vms_analysis: list[dict], monthly_data: dict[str, list], project_id: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = os.path.join(REPORTS_DIR, f"cost_optimization_{project_id}_{ts}.csv")

    all_months = sorted(
        {e["month"] for series in monthly_data.values() for e in series}
    )[-10:]

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        header = [
            "VM Name", "Zone", "Machine Type", "vCPUs", "RAM (GB)",
            "Status", "CPU Avg%", "CPU Max%", "CPU P95%",
            "Mem Avg%", "Est Monthly Cost USD",
            "Classification", "Reason",
            "Suggested Machine Type", "Suggested Cost USD",
        ] + [f"CPU {m}" for m in all_months]
        w.writerow(header)

        for v in vms_analysis:
            by_month = {e["month"]: e["avg_cpu"] for e in monthly_data.get(v["name"], [])}
            row = [
                v["name"], v["zone"], v["machine_type"],
                v.get("vcpus"), v.get("ram_gb"),
                v.get("status"),
                v.get("cpu_avg"), v.get("cpu_max"), v.get("cpu_p95"),
                v.get("mem_avg"),
                v.get("monthly_cost"),
                v.get("classification"), v.get("reason"),
                v.get("suggested_type"), v.get("suggested_type_cost"),
            ] + [by_month.get(m, "") for m in all_months]
            w.writerow(row)

    return path


def export_json(vms_analysis: list[dict], savings: dict, project_id: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = os.path.join(REPORTS_DIR, f"cost_optimization_{project_id}_{ts}.json")

    payload = {
        "project_id": project_id,
        "analysis_period": {
            "start": ANALYSIS_START.isoformat(),
            "end":   ANALYSIS_END.isoformat(),
            "months": MONTHS_BACK,
        },
        "savings_summary": savings,
        "vms": vms_analysis,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    return path
