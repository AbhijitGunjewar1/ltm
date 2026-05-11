"""
Fetch all VM instances in the project across all zones.
Uses the Compute Engine REST API (aggregatedList).
"""

import requests
from typing import Any
from config import PROJECT_ID, MACHINE_CATALOG


def list_all_vms(token: str, project_id: str = PROJECT_ID) -> list[dict]:
    """
    Return a flat list of VM dicts with enriched fields:
    name, zone, status, machine_type, vcpus, ram_gb,
    creation_timestamp, labels, network_interfaces, disks,
    scheduling (preemptible/spot), internal_ip, external_ip.
    """
    url = (
        f"https://compute.googleapis.com/compute/v1/projects/{project_id}"
        f"/aggregated/instances"
    )
    headers = {"Authorization": f"Bearer {token}"}
    vms: list[dict] = []
    page_token = None

    while True:
        params: dict[str, Any] = {"maxResults": 500}
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for zone_key, zone_data in data.get("items", {}).items():
            for inst in zone_data.get("instances", []):
                vms.append(_enrich(inst, zone_key))

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return vms


def _enrich(inst: dict, zone_key: str) -> dict:
    zone = zone_key.replace("zones/", "")
    mt_full = inst.get("machineType", "")
    machine_type = mt_full.split("/")[-1]

    vcpus, ram_gb = MACHINE_CATALOG.get(machine_type, (None, None))

    # Try to extract from machineType URL if custom
    if vcpus is None:
        vcpus, ram_gb = _parse_custom_machine(inst, machine_type)

    net = inst.get("networkInterfaces", [{}])[0]
    internal_ip = net.get("networkIP", "")
    access_configs = net.get("accessConfigs", [{}])
    external_ip = access_configs[0].get("natIP", "") if access_configs else ""

    scheduling = inst.get("scheduling", {})

    disks = [
        {
            "source": d.get("source", "").split("/")[-1],
            "type": d.get("type", "PERSISTENT"),
            "mode": d.get("mode", "READ_WRITE"),
            "boot": d.get("boot", False),
            "auto_delete": d.get("autoDelete", False),
        }
        for d in inst.get("disks", [])
    ]

    return {
        "name": inst.get("name"),
        "zone": zone,
        "status": inst.get("status"),
        "machine_type": machine_type,
        "vcpus": vcpus,
        "ram_gb": ram_gb,
        "creation_timestamp": inst.get("creationTimestamp"),
        "labels": inst.get("labels", {}),
        "tags": inst.get("tags", {}).get("items", []),
        "internal_ip": internal_ip,
        "external_ip": external_ip,
        "preemptible": scheduling.get("preemptible", False),
        "provisioning_model": scheduling.get("provisioningModel", "STANDARD"),
        "disks": disks,
        "num_disks": len(disks),
        "self_link": inst.get("selfLink", ""),
        "id": inst.get("id", ""),
    }


def _parse_custom_machine(inst: dict, machine_type: str):
    """Handle custom-N-VCPU-RAM and n2d-custom-* patterns."""
    parts = machine_type.lower().split("-")
    try:
        if "custom" in parts:
            idx = parts.index("custom")
            vcpus = int(parts[idx + 1])
            ram_mb = int(parts[idx + 2])
            return vcpus, ram_mb / 1024
    except (IndexError, ValueError):
        pass

    # Try guestCpus / memoryMb from machineType description if available
    mt_desc = inst.get("machineTypeDescription", {})
    if mt_desc:
        return mt_desc.get("guestCpus"), mt_desc.get("memoryMb", 0) / 1024

    return None, None


def print_vm_table(vms: list[dict]) -> None:
    from tabulate import tabulate
    rows = [
        [
            v["name"],
            v["zone"],
            v["status"],
            v["machine_type"],
            v["vcpus"],
            f'{v["ram_gb"]} GB' if v["ram_gb"] else "?",
            "YES" if v["preemptible"] else "no",
        ]
        for v in vms
    ]
    print(
        tabulate(
            rows,
            headers=["Name", "Zone", "Status", "Machine Type", "vCPUs", "RAM", "Spot"],
            tablefmt="github",
        )
    )
