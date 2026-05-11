#!/usr/bin/env python3
"""
GCP Cloud Cost Optimizer — File-based analyzer.

Drop your exported VM/metrics file into this directory, then run:

    python analyze_file.py <your-file>

Supported formats:
    - CSV  (GCP Console export or Monitoring export)
    - JSON
    - Excel (.xlsx / .xls)

Examples:
    python analyze_file.py vm_metrics.csv
    python analyze_file.py monitoring_export.json
    python analyze_file.py gcp_vms.xlsx
"""

import sys
import os
import json
import csv
import argparse
from datetime import datetime, timezone

# ── Try importing optional libs gracefully ────────────────────────────────────
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False


# ── Thresholds (same as config.py) ───────────────────────────────────────────
CPU_IDLE_THRESHOLD   = 5.0
CPU_LOW_THRESHOLD    = 20.0
CPU_HIGH_THRESHOLD   = 80.0
MEM_LOW_THRESHOLD    = 40.0

# Approximate on-demand prices (us-central1, USD/hr)
MACHINE_CATALOG = {
    "n1-standard-1":  (1,  3.75,  0.0475, 0.0066),
    "n1-standard-2":  (2,  7.5,   0.0475, 0.0066),
    "n1-standard-4":  (4,  15,    0.0475, 0.0066),
    "n1-standard-8":  (8,  30,    0.0475, 0.0066),
    "n1-standard-16": (16, 60,    0.0475, 0.0066),
    "n1-standard-32": (32, 120,   0.0475, 0.0066),
    "n1-standard-64": (64, 240,   0.0475, 0.0066),
    "n1-highmem-2":   (2,  13,    0.0475, 0.0066),
    "n1-highmem-4":   (4,  26,    0.0475, 0.0066),
    "n1-highmem-8":   (8,  52,    0.0475, 0.0066),
    "n1-highmem-16":  (16, 104,   0.0475, 0.0066),
    "n1-highcpu-4":   (4,  3.6,   0.0475, 0.0066),
    "n1-highcpu-8":   (8,  7.2,   0.0475, 0.0066),
    "n1-highcpu-16":  (16, 14.4,  0.0475, 0.0066),
    "n2-standard-2":  (2,  8,     0.0334, 0.0045),
    "n2-standard-4":  (4,  16,    0.0334, 0.0045),
    "n2-standard-8":  (8,  32,    0.0334, 0.0045),
    "n2-standard-16": (16, 64,    0.0334, 0.0045),
    "n2-standard-32": (32, 128,   0.0334, 0.0045),
    "n2-standard-48": (48, 192,   0.0334, 0.0045),
    "n2-highmem-2":   (2,  16,    0.0334, 0.0045),
    "n2-highmem-4":   (4,  32,    0.0334, 0.0045),
    "n2-highmem-8":   (8,  64,    0.0334, 0.0045),
    "n2-highmem-16":  (16, 128,   0.0334, 0.0045),
    "n2-highcpu-4":   (4,  4,     0.0334, 0.0045),
    "n2-highcpu-8":   (8,  8,     0.0334, 0.0045),
    "n2-highcpu-16":  (16, 16,    0.0334, 0.0045),
    "n2-highcpu-32":  (32, 32,    0.0334, 0.0045),
    "e2-micro":       (2,  1,     0.0210, 0.0028),
    "e2-small":       (2,  2,     0.0210, 0.0028),
    "e2-medium":      (2,  4,     0.0210, 0.0028),
    "e2-standard-2":  (2,  8,     0.0210, 0.0028),
    "e2-standard-4":  (4,  16,    0.0210, 0.0028),
    "e2-standard-8":  (8,  32,    0.0210, 0.0028),
    "e2-standard-16": (16, 64,    0.0210, 0.0028),
    "e2-highmem-2":   (2,  16,    0.0210, 0.0028),
    "e2-highmem-4":   (4,  32,    0.0210, 0.0028),
    "e2-highmem-8":   (8,  64,    0.0210, 0.0028),
    "e2-highmem-16":  (16, 128,   0.0210, 0.0028),
    "e2-highcpu-4":   (4,  4,     0.0210, 0.0028),
    "e2-highcpu-8":   (8,  8,     0.0210, 0.0028),
    "e2-highcpu-16":  (16, 16,    0.0210, 0.0028),
    "e2-highcpu-32":  (32, 32,    0.0210, 0.0028),
    "n2d-standard-2": (2,  8,     0.0284, 0.0038),
    "n2d-standard-4": (4,  16,    0.0284, 0.0038),
    "n2d-standard-8": (8,  32,    0.0284, 0.0038),
    "n2d-standard-16":(16, 64,    0.0284, 0.0038),
    "c2-standard-4":  (4,  16,    0.0522, 0.0070),
    "c2-standard-8":  (8,  32,    0.0522, 0.0070),
    "c2-standard-16": (16, 64,    0.0522, 0.0070),
    "c2-standard-30": (30, 120,   0.0522, 0.0070),
    "c2-standard-60": (60, 240,   0.0522, 0.0070),
}

HOURS_PER_MONTH = 730

# ── Column name aliases (handles variations in GCP export headers) ─────────────
COL_ALIASES = {
    "name":         ["name", "instance name", "vm name", "instance_name", "vm_name", "hostname"],
    "zone":         ["zone", "location", "region"],
    "machine_type": ["machine type", "machine_type", "type", "instance type", "size"],
    "status":       ["status", "state", "power state"],
    "cpu_avg":      ["cpu avg", "cpu_avg", "average cpu", "cpu utilization", "cpu util",
                     "cpu usage", "avg cpu utilization", "mean cpu", "cpu (avg)",
                     "cpu utilization (avg)", "average cpu utilization"],
    "cpu_max":      ["cpu max", "cpu_max", "max cpu", "peak cpu", "cpu (max)"],
    "cpu_p95":      ["cpu p95", "cpu_p95", "95th cpu", "p95 cpu"],
    "mem_avg":      ["memory avg", "mem avg", "mem_avg", "average memory",
                     "memory utilization", "mem util", "memory usage",
                     "avg memory utilization", "memory (avg)", "ram usage"],
    "mem_max":      ["memory max", "mem max", "mem_max", "peak memory", "memory (max)"],
    "vcpus":        ["vcpus", "vcpu", "cpus", "cpu count", "num cpus", "cores"],
    "ram_gb":       ["ram gb", "ram_gb", "memory gb", "memory (gb)", "ram (gb)",
                     "total memory", "memory size"],
}


# ─────────────────────────────────────────────────────────────────────────────
#  File loading
# ─────────────────────────────────────────────────────────────────────────────

def load_file(path: str) -> list[dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return load_json(path)
    elif ext in (".xlsx", ".xls"):
        return load_excel(path)
    else:
        return load_csv(path)


def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items() if k})
    print(f"  Loaded {len(rows)} rows from CSV.")
    return rows


def load_excel(path: str) -> list[dict]:
    if not HAS_PANDAS:
        print("ERROR: pandas is required for Excel files.  Run:  pip install pandas openpyxl")
        sys.exit(1)
    df = pd.read_excel(path, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    rows = df.fillna("").to_dict(orient="records")
    print(f"  Loaded {len(rows)} rows from Excel.")
    return rows


def load_json(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # GCP Monitoring timeSeries export or custom dict
        rows = data.get("vms", data.get("instances", data.get("items", [data])))
    print(f"  Loaded {len(rows)} records from JSON.")
    return rows


# ─────────────────────────────────────────────────────────────────────────────
#  Column mapping
# ─────────────────────────────────────────────────────────────────────────────

def map_columns(rows: list[dict]) -> list[dict]:
    """Normalise column names using COL_ALIASES."""
    if not rows:
        return rows

    raw_headers = list(rows[0].keys())
    header_lower = {h.lower(): h for h in raw_headers}
    mapping: dict[str, str] = {}   # canonical_name → raw_header

    for canonical, aliases in COL_ALIASES.items():
        for alias in aliases:
            if alias in header_lower:
                mapping[canonical] = header_lower[alias]
                break

    if "name" not in mapping:
        print("\nWARNING: Could not detect a 'VM Name' column.")
        print(f"  Detected columns: {raw_headers}")
        print("  Please rename one column to 'name' and re-run.\n")

    normalized = []
    for row in rows:
        nr: dict = {}
        for canonical, raw in mapping.items():
            nr[canonical] = row.get(raw, "")
        # preserve any extra columns not in our aliases
        for k, v in row.items():
            if k not in mapping.values():
                nr[k] = v
        normalized.append(nr)

    return normalized


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pct(val) -> float | None:
    """Parse a value that may be '12.3', '12.3%', or empty → float or None."""
    if val is None or str(val).strip() in ("", "-", "N/A", "n/a"):
        return None
    s = str(val).strip().rstrip("%")
    try:
        v = float(s)
        # If stored as 0-1 fraction, convert to %
        if 0 < v <= 1.0:
            v *= 100
        return round(v, 2)
    except ValueError:
        return None


def _float(val) -> float | None:
    if val is None or str(val).strip() in ("", "-", "N/A"):
        return None
    try:
        return float(str(val).strip().replace(",", ""))
    except ValueError:
        return None


def _int(val) -> int | None:
    f = _float(val)
    return int(f) if f is not None else None


def estimate_cost(vcpus, ram_gb, machine_type) -> float | None:
    if vcpus is None or ram_gb is None:
        return None
    mt = (machine_type or "").lower()
    for key, (cv, cr, cpu_p, ram_p) in MACHINE_CATALOG.items():
        if mt == key:
            return round(cv * cpu_p * HOURS_PER_MONTH + cr * ram_p * HOURS_PER_MONTH, 2)
    # fallback: use vcpus/ram_gb with n2 pricing
    return round(vcpus * 0.0334 * HOURS_PER_MONTH + ram_gb * 0.0045 * HOURS_PER_MONTH, 2)


def lookup_machine_specs(machine_type: str):
    mt = (machine_type or "").lower()
    if mt in MACHINE_CATALOG:
        v, r, _, _ = MACHINE_CATALOG[mt]
        return v, r
    return None, None


def suggest_smaller(machine_type, avg_cpu, avg_mem, vcpus, ram_gb):
    if avg_cpu is None or vcpus is None:
        return None, None
    target_cpu = max(1, vcpus * (avg_cpu / 100) * 1.3)
    target_ram = max(0.5, (ram_gb or 4) * ((avg_mem or 50) / 100) * 1.3)

    best, best_cost = None, None
    for mt, (cv, cr, cpu_p, ram_p) in MACHINE_CATALOG.items():
        if cv < target_cpu or cr < target_ram:
            continue
        if not any(mt.startswith(f) for f in ["e2-", "n2-standard", "n2-highmem"]):
            continue
        cost = cv * cpu_p * HOURS_PER_MONTH + cr * ram_p * HOURS_PER_MONTH
        if best_cost is None or cost < best_cost:
            best, best_cost = mt, round(cost, 2)

    current_cost = estimate_cost(vcpus, ram_gb, machine_type)
    if best and current_cost and best_cost and best_cost < current_cost * 0.85:
        return best, best_cost
    return None, None


def classify(avg_cpu, avg_mem):
    if avg_cpu is None:
        return "NO_DATA", "No CPU metrics in file"
    if avg_cpu < CPU_IDLE_THRESHOLD:
        return "IDLE", f"Avg CPU {avg_cpu:.1f}% — candidate for shutdown"
    if avg_cpu < CPU_LOW_THRESHOLD:
        if avg_mem is not None and avg_mem < MEM_LOW_THRESHOLD:
            return "OVER_PROVISIONED", f"Avg CPU {avg_cpu:.1f}%, Avg Mem {avg_mem:.1f}% — both low"
        return "OVER_PROVISIONED", f"Avg CPU {avg_cpu:.1f}% — low utilization"
    if avg_cpu > CPU_HIGH_THRESHOLD:
        return "UNDER_PROVISIONED", f"Avg CPU {avg_cpu:.1f}% — consistently high"
    return "OPTIMAL", f"Avg CPU {avg_cpu:.1f}% — within normal range"


def _c(text, cls):
    if not HAS_COLOR:
        return str(text)
    colors = {
        "IDLE":             Fore.RED,
        "OVER_PROVISIONED": Fore.YELLOW,
        "UNDER_PROVISIONED":Fore.MAGENTA,
        "OPTIMAL":          Fore.GREEN,
        "NO_DATA":          Fore.WHITE,
    }
    return f"{colors.get(cls,'')}{text}{Style.RESET_ALL}"


def _tab(rows, headers):
    if HAS_TABULATE:
        return tabulate(rows, headers=headers, tablefmt="github")
    # plain fallback
    widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
              for i, h in enumerate(headers)]
    sep = "  ".join("-" * w for w in widths)
    hdr = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    lines = [hdr, sep]
    for row in rows:
        lines.append("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  Monthly breakdown detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_monthly_columns(rows: list[dict]) -> list[str]:
    """Find columns that look like 'YYYY-MM' month keys."""
    if not rows:
        return []
    months = []
    for col in rows[0].keys():
        c = str(col).strip()
        # match YYYY-MM or Month-YYYY or abbreviated month names
        if len(c) == 7 and c[4] == "-":
            try:
                datetime.strptime(c, "%Y-%m")
                months.append(c)
            except ValueError:
                pass
        elif len(c) >= 6 and "-" in c:
            # try MMM-YYYY
            for fmt in ("%b-%Y", "%B-%Y", "%b %Y"):
                try:
                    dt = datetime.strptime(c, fmt)
                    months.append(dt.strftime("%Y-%m"))
                    break
                except ValueError:
                    pass
    return sorted(months)


# ─────────────────────────────────────────────────────────────────────────────
#  Main analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze(rows: list[dict]) -> None:
    print(f"\n{'='*80}")
    print("  GCP CLOUD COST OPTIMIZATION REPORT")
    print(f"  Generated : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  VMs in file : {len(rows)}")
    print(f"{'='*80}\n")

    vms_analysis = []
    monthly_cols = detect_monthly_columns(rows)

    for row in rows:
        name         = row.get("name", "").strip() or row.get("Name", "unknown")
        zone         = row.get("zone", "").strip()
        machine_type = row.get("machine_type", "").strip()
        status       = row.get("status", "UNKNOWN").strip().upper()

        avg_cpu = _pct(row.get("cpu_avg"))
        max_cpu = _pct(row.get("cpu_max"))
        p95_cpu = _pct(row.get("cpu_p95"))
        avg_mem = _pct(row.get("mem_avg"))

        vcpus   = _int(row.get("vcpus"))
        ram_gb  = _float(row.get("ram_gb"))

        # If vcpus/ram not in file, look up from machine type
        if vcpus is None and machine_type:
            vcpus, ram_gb = lookup_machine_specs(machine_type)

        monthly = {}
        for mc in monthly_cols:
            v = _pct(row.get(mc))
            if v is not None:
                monthly[mc] = v

        monthly_cost    = estimate_cost(vcpus, ram_gb, machine_type)
        cls, reason     = classify(avg_cpu, avg_mem)
        stype, scost    = suggest_smaller(machine_type, avg_cpu, avg_mem, vcpus, ram_gb)

        vms_analysis.append({
            "name": name, "zone": zone, "machine_type": machine_type,
            "status": status, "vcpus": vcpus, "ram_gb": ram_gb,
            "cpu_avg": avg_cpu, "cpu_max": max_cpu, "cpu_p95": p95_cpu,
            "mem_avg": avg_mem,
            "monthly_cost": monthly_cost,
            "classification": cls, "reason": reason,
            "suggested_type": stype, "suggested_type_cost": scost,
            "monthly": monthly,
        })

    # ── VM Analysis Table ─────────────────────────────────────────────────────
    print(f"\n{'─'*80}")
    print("  VM ANALYSIS — CPU & MEMORY UTILIZATION")
    print(f"{'─'*80}\n")

    table_rows = []
    for v in vms_analysis:
        cls = v["classification"]
        table_rows.append([
            _c(v["name"][:32], cls),
            (v["zone"] or "")[-14:],
            v["machine_type"] or "—",
            v["vcpus"] or "?",
            f'{v["ram_gb"]} GB' if v["ram_gb"] else "?",
            f'{v["cpu_avg"]:.1f}%' if v["cpu_avg"] is not None else "N/A",
            f'{v["mem_avg"]:.1f}%' if v["mem_avg"] is not None else "N/A",
            f'${v["monthly_cost"]:.2f}' if v["monthly_cost"] else "N/A",
            _c(cls, cls),
            v["suggested_type"] or "—",
            f'${v["suggested_type_cost"]:.2f}/mo' if v["suggested_type_cost"] else "—",
        ])

    print(_tab(table_rows, [
        "VM Name", "Zone", "Machine Type", "vCPU", "RAM",
        "CPU avg", "Mem avg", "$/mo", "Classification", "Suggested Type", "Saving"
    ]))

    # ── Monthly Breakdown ─────────────────────────────────────────────────────
    if monthly_cols:
        print(f"\n{'─'*80}")
        print(f"  MONTHLY CPU UTILIZATION BREAKDOWN ({len(monthly_cols)} months)")
        print(f"{'─'*80}\n")
        last10 = sorted(monthly_cols)[-10:]
        mrows = []
        for v in vms_analysis:
            row = [_c(v["name"][:28], v["classification"])]
            for m in last10:
                val = v["monthly"].get(m)
                row.append(f"{val:.1f}%" if val is not None else "—")
            mrows.append(row)
        print(_tab(mrows, ["VM Name"] + last10))
    else:
        print("\n  NOTE: No monthly breakdown columns detected in file.")
        print("        To get monthly data, export each month's avg CPU as a separate column")
        print("        named 'YYYY-MM' (e.g. '2024-08', '2024-09', ...).\n")

    # ── Savings Summary ───────────────────────────────────────────────────────
    total_current   = sum(v["monthly_cost"] or 0 for v in vms_analysis)
    idle_saving     = sum(v["monthly_cost"] or 0 for v in vms_analysis if v["classification"] == "IDLE")
    rightsize_saving= sum(
        (v["monthly_cost"] or 0) - (v["suggested_type_cost"] or v["monthly_cost"] or 0)
        for v in vms_analysis if v["classification"] == "OVER_PROVISIONED"
    )
    total_saving    = idle_saving + rightsize_saving
    optimized       = total_current - total_saving

    print(f"\n{'─'*80}")
    print("  COST SAVINGS SUMMARY")
    print(f"{'─'*80}\n")
    summary = [
        ["Current monthly cost (all VMs)",        f"${total_current:>10,.2f}"],
        ["Optimized monthly cost",                 f"${optimized:>10,.2f}"],
        ["Monthly savings potential",              f"${total_saving:>10,.2f}"],
        ["10-month cumulative savings",            f"${total_saving*10:>10,.2f}"],
        ["  from shutting down IDLE VMs",          f"${idle_saving:>10,.2f}/mo"],
        ["  from rightsizing OVER_PROVISIONED",    f"${rightsize_saving:>10,.2f}/mo"],
        ["Savings %",                              f"{(total_saving/total_current*100 if total_current else 0):>9.1f}%"],
    ]
    print(_tab(summary, ["", ""]))

    # ── Recommendations ───────────────────────────────────────────────────────
    idle   = [v for v in vms_analysis if v["classification"] == "IDLE"]
    overp  = [v for v in vms_analysis if v["classification"] == "OVER_PROVISIONED"]
    underp = [v for v in vms_analysis if v["classification"] == "UNDER_PROVISIONED"]
    nodata = [v for v in vms_analysis if v["classification"] == "NO_DATA"]

    print(f"\n{'─'*80}")
    print("  PRIORITISED RECOMMENDATIONS")
    print(f"{'─'*80}\n")

    if idle:
        print(_c(f"  [P1] IDLE VMs ({len(idle)}) — Shut down or delete", "IDLE"))
        for v in idle:
            print(f"       • {v['name']}  ({v['zone']})  CPU avg: {v['cpu_avg']:.1f}%  "
                  f"Saving: ${v['monthly_cost'] or 0:.2f}/mo")
        print()

    if overp:
        print(_c(f"  [P2] OVER-PROVISIONED VMs ({len(overp)}) — Rightsize", "OVER_PROVISIONED"))
        for v in overp:
            saving = (v["monthly_cost"] or 0) - (v["suggested_type_cost"] or v["monthly_cost"] or 0)
            print(f"       • {v['name']}  ({v['machine_type']} → {v['suggested_type'] or 'smaller'})  "
                  f"CPU avg: {v['cpu_avg']:.1f}%  Saving: ${saving:.2f}/mo")
        print()

    if underp:
        print(_c(f"  [P3] UNDER-PROVISIONED VMs ({len(underp)}) — Consider upsizing", "UNDER_PROVISIONED"))
        for v in underp:
            print(f"       • {v['name']}  ({v['machine_type']})  CPU avg: {v['cpu_avg']:.1f}%")
        print()

    if nodata:
        print(_c(f"  [INFO] No metrics data for {len(nodata)} VMs", "NO_DATA"))
        for v in nodata:
            print(f"       • {v['name']}  ({v['zone']}, {v['machine_type']})")
        print()

    print("  General recommendations:")
    print("  • Committed Use Discounts (CUDs) for stable VMs    → 37–57% savings")
    print("  • Spot/Preemptible VMs for batch/fault-tolerant     → up to 91% savings")
    print("  • Schedule non-prod shutdown outside office hours   → ~67% savings on those VMs")
    print("  • Delete unattached persistent disks")
    print("  • Set up Budget Alerts in Cloud Billing\n")

    # ── Export CSV ────────────────────────────────────────────────────────────
    os.makedirs("reports", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out_path = f"reports/analysis_{ts}.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "VM Name", "Zone", "Machine Type", "vCPUs", "RAM GB", "Status",
            "CPU Avg%", "CPU Max%", "CPU P95%", "Mem Avg%",
            "Est Monthly Cost USD", "Classification", "Reason",
            "Suggested Machine Type", "Suggested Cost USD",
        ] + sorted(monthly_cols)[-10:])
        for v in vms_analysis:
            w.writerow([
                v["name"], v["zone"], v["machine_type"],
                v["vcpus"], v["ram_gb"], v["status"],
                v["cpu_avg"], v["cpu_max"], v["cpu_p95"], v["mem_avg"],
                v["monthly_cost"], v["classification"], v["reason"],
                v["suggested_type"], v["suggested_type_cost"],
            ] + [v["monthly"].get(m, "") for m in sorted(monthly_cols)[-10:]])

    print(f"  Report saved: {out_path}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GCP VM Cost Analyzer — file-based")
    parser.add_argument("file", nargs="?", help="Path to VM metrics file (CSV/JSON/Excel)")
    args = parser.parse_args()

    # Auto-detect file if not specified
    filepath = args.file
    if not filepath:
        candidates = [
            f for f in os.listdir(".")
            if f.lower().endswith((".csv", ".json", ".xlsx", ".xls"))
            and not f.startswith(".")
            and "analysis_" not in f   # skip our own output
        ]
        if len(candidates) == 1:
            filepath = candidates[0]
            print(f"  Auto-detected file: {filepath}")
        elif len(candidates) > 1:
            print("Multiple files found. Please specify one:")
            for c in candidates:
                print(f"  python analyze_file.py {c}")
            sys.exit(1)
        else:
            print("No input file found in current directory.")
            print("Usage: python analyze_file.py <your-file.csv>")
            sys.exit(1)

    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    print(f"\nLoading: {filepath}")
    raw_rows = load_file(filepath)
    if not raw_rows:
        print("File is empty or could not be parsed.")
        sys.exit(1)

    rows = map_columns(raw_rows)
    analyze(rows)


if __name__ == "__main__":
    main()
