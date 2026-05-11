"""
Estimate monthly cost per VM and compute potential savings.
Prices are approximate on-demand us-central1 rates (USD).
"""

from config import MACHINE_TYPE_PRICES, MACHINE_CATALOG, MONTHS_BACK

HOURS_PER_MONTH = 730   # average


def _price_key(machine_type: str) -> dict:
    """Find the best matching price entry for a machine type."""
    mt = machine_type.lower()
    for family in MACHINE_TYPE_PRICES:
        if family == "default":
            continue
        if mt.startswith(family):
            return MACHINE_TYPE_PRICES[family]
    return MACHINE_TYPE_PRICES["default"]


def estimate_monthly_cost(vcpus: int | None, ram_gb: float | None, machine_type: str) -> float | None:
    if vcpus is None or ram_gb is None:
        return None
    prices = _price_key(machine_type)
    return round(vcpus * prices["vcpu"] * HOURS_PER_MONTH
                 + ram_gb * prices["ram_gb"] * HOURS_PER_MONTH, 2)


def suggest_rightsized_type(
    machine_type: str,
    avg_cpu_pct: float | None,
    avg_mem_pct: float | None,
    vcpus: int | None,
    ram_gb: float | None,
) -> tuple[str | None, float | None]:
    """
    Suggest a smaller machine type and return (suggested_type, estimated_monthly_cost).
    Returns (None, None) if no suggestion applies.
    """
    if avg_cpu_pct is None or vcpus is None or ram_gb is None:
        return None, None

    # Target: keep ~20% headroom above actual usage
    target_vcpus = max(1, vcpus * (avg_cpu_pct / 100) * 1.25)
    target_ram   = max(0.5, ram_gb * ((avg_mem_pct or 50) / 100) * 1.25)

    # Determine family preference (prefer e2 for cost, keep same if n2/c2)
    mt = machine_type.lower()
    if mt.startswith("c2") or mt.startswith("m1"):
        preferred_families = [machine_type.split("-")[0] + "-" + machine_type.split("-")[1]]
    else:
        preferred_families = ["e2-standard", "e2-highmem", "n2-standard", "n2-highmem"]

    best: str | None = None
    best_cost: float | None = None

    for mtype, (cv, cr) in MACHINE_CATALOG.items():
        if cv < target_vcpus or cr < target_ram:
            continue
        if not any(mtype.startswith(f.rsplit("-", 1)[0]) for f in preferred_families):
            continue
        cost = estimate_monthly_cost(cv, cr, mtype)
        if cost is None:
            continue
        if best_cost is None or cost < best_cost:
            best = mtype
            best_cost = cost

    # Only suggest if it's genuinely smaller than current
    current_cost = estimate_monthly_cost(vcpus, ram_gb, machine_type)
    if best and current_cost and best_cost and best_cost < current_cost * 0.85:
        return best, best_cost

    return None, None


def compute_savings(vms_analysis: list[dict]) -> dict:
    """
    Given list of analysed VM dicts, return summary savings dict.
    Each vm_analysis dict must have: monthly_cost, classification, suggested_type_cost.
    """
    total_current = 0.0
    total_potential = 0.0
    idle_savings = 0.0
    rightsize_savings = 0.0

    for vm in vms_analysis:
        mc = vm.get("monthly_cost") or 0.0
        total_current += mc

        cls = vm.get("classification", "")
        stc = vm.get("suggested_type_cost")

        if cls == "IDLE":
            idle_savings += mc          # shut it down entirely
            total_potential += 0.0
        elif cls == "OVER_PROVISIONED" and stc:
            saving = mc - stc
            rightsize_savings += saving
            total_potential += stc
        else:
            total_potential += mc

    return {
        "total_current_monthly_usd": round(total_current, 2),
        "total_optimized_monthly_usd": round(total_potential, 2),
        "total_savings_monthly_usd": round(total_current - total_potential, 2),
        "total_savings_10month_usd": round((total_current - total_potential) * MONTHS_BACK, 2),
        "idle_savings_monthly_usd": round(idle_savings, 2),
        "rightsize_savings_monthly_usd": round(rightsize_savings, 2),
        "savings_pct": round(
            (total_current - total_potential) / total_current * 100
            if total_current > 0 else 0,
            1,
        ),
    }
