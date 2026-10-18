"""
ForestChain CAR — Forestry Traceability & Blockchain Prototype
Single-file Panel web app, inspired by the uploaded housing dashboard structure.

Install:
    python -m pip install panel pandas numpy plotly web3  # web3 is needed only for blockchain RPC integration

Run:
    panel serve forestchain_app.py --show --autoreload

Optional GIS:
    Install ArcGIS API for Python in a suitable conda environment:
    conda install -c esri arcgis
    Then configure ARCGIS_PORTAL_URL / ARCGIS_USERNAME / ARCGIS_PASSWORD
    in environment variables if using a secured ArcGIS portal.

Important:
- This is a prototype, not a production blockchain or legal certification system.
- The built-in ledger is a local hash-chained audit log stored in forestchain_ledger.json.
- ArcGIS integration is optional: a web map can be embedded by setting ARCGIS_WEBMAP_ID.
- No credentials are hard-coded. Do not store secrets in source code.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import panel as pn
import plotly.express as px
import plotly.graph_objects as go

pn.extension("plotly", "tabulator", notifications=True, sizing_mode="stretch_width")

APP_TITLE = "ForestChain CAR | Timber Traceability"
LEDGER_PATH = Path(os.getenv("FORESTCHAIN_LEDGER", "forestchain_ledger.json"))
DATA_PATH = Path(os.getenv("FORESTCHAIN_DATA", "forestry_records.csv"))
ARCGIS_WEBMAP_ID = os.getenv("ARCGIS_WEBMAP_ID", "").strip()
ARCGIS_PORTAL_URL = os.getenv("ARCGIS_PORTAL_URL", "").strip()

# Optional EVM-compatible blockchain integration. Keep credentials in environment variables.
BLOCKCHAIN_RPC_URL = os.getenv("BLOCKCHAIN_RPC_URL", "").strip()
BLOCKCHAIN_CONTRACT_ADDRESS = os.getenv("BLOCKCHAIN_CONTRACT_ADDRESS", "").strip()
BLOCKCHAIN_PRIVATE_KEY = os.getenv("BLOCKCHAIN_PRIVATE_KEY", "").strip()


# ---------------------------------------------------------------------
# Demo data: explicitly labelled. Replace with verified operational data.
# ---------------------------------------------------------------------
def make_demo_data(n: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    species = ["Sapelli", "Ayous", "Sipo", "Iroko", "Limba"]
    regions = ["Lobaye", "Sangha-Mbaéré", "Ombella-M'Poko", "Mambéré-Kadéï"]
    statuses = ["Registered", "Harvested", "In Transit", "At Sawmill", "Exported"]
    rows = []
    base = pd.Timestamp("2026-01-01")
    for i in range(n):
        lat = float(rng.uniform(3.8, 6.8))
        lon = float(rng.uniform(15.0, 20.0))

        rows.append({
            "record_id": f"DEMO-{i+1:04d}",
            "tree_lot_id": f"LOT-{rng.integers(1000, 9999)}",
            "species": rng.choice(species),
            "region": rng.choice(regions),
            "harvest_date": (base + pd.Timedelta(days=int(rng.integers(0, 260)))).date().isoformat(),
            "volume_m3": round(float(rng.uniform(0.5, 18)), 2),
            "latitude": lat,
            "longitude": lon,
            "operator": rng.choice(["Forest Unit A", "Forest Unit B", "Community Cooperative"]),
            "status": rng.choice(statuses),
            "permit_id": f"PERMIT-{rng.integers(100, 999)}",
            "destination": rng.choice(["Bangui", "Douala", "Local Sawmill", "Export Terminal"]),
        })
    return pd.DataFrame(rows)


def load_records() -> tuple[pd.DataFrame, str]:
    if DATA_PATH.exists():
        try:
            frame = pd.read_csv(DATA_PATH)
            required = {"record_id", "tree_lot_id", "species", "region", "harvest_date",
                        "volume_m3", "latitude", "longitude", "operator", "status",
                        "permit_id", "destination"}
            missing = required - set(frame.columns)
            if missing:
                return make_demo_data(), (
                    f"**Warning:** `{DATA_PATH}` is missing columns: {', '.join(sorted(missing))}. "
                    "Showing labelled demo data instead."
                )
            return frame, f"**Data source:** `{DATA_PATH}`. Validate all records before operational use."
        except Exception as exc:
            return make_demo_data(), f"**Warning:** Could not read `{DATA_PATH}` ({exc}). Showing demo data."
    return make_demo_data(), (
        f"**DEMO MODE:** `{DATA_PATH}` not found. Synthetic records are shown for demonstration only."
    )


records, source_note = load_records()
required_columns = ["record_id", "tree_lot_id", "species", "region", "harvest_date",
                    "volume_m3", "latitude", "longitude", "operator", "status",
                    "permit_id", "destination"]
for col in required_columns:
    if col not in records:
        records[col] = np.nan
records["volume_m3"] = pd.to_numeric(records["volume_m3"], errors="coerce")
records["latitude"] = pd.to_numeric(records["latitude"], errors="coerce")
records["longitude"] = pd.to_numeric(records["longitude"], errors="coerce")
records["harvest_date"] = pd.to_datetime(records["harvest_date"], errors="coerce")

# ---------------------------------------------------------------------
# Minimal local hash-chain ledger. This is tamper-evident only if ledger
# file is protected and independently replicated; it is NOT a distributed
# blockchain consensus network.
# ---------------------------------------------------------------------
def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def load_ledger() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    try:
        payload = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


def save_ledger(entries: list[dict]) -> None:
    temp_path = LEDGER_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(LEDGER_PATH)


def calculate_hash(entry: dict) -> str:
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def verify_ledger(entries: list[dict]) -> tuple[bool, str]:
    previous = "GENESIS"
    for index, entry in enumerate(entries):
        if entry.get("previous_hash") != previous:
            return False, f"Entry {index + 1}: previous hash does not match."
        if entry.get("entry_hash") != calculate_hash(entry):
            return False, f"Entry {index + 1}: entry hash is invalid."
        previous = entry["entry_hash"]
    return True, f"Verified {len(entries)} ledger entries."


def get_blockchain_client():
    """Return a configured Web3 contract, or None if blockchain settings are absent."""
    if not (BLOCKCHAIN_RPC_URL and BLOCKCHAIN_CONTRACT_ADDRESS and BLOCKCHAIN_PRIVATE_KEY):
        return None
    try:
        from web3 import Web3
        web3 = Web3(Web3.HTTPProvider(BLOCKCHAIN_RPC_URL, request_kwargs={"timeout": 10}))
        if not web3.is_connected():
            raise RuntimeError("Cannot connect to BLOCKCHAIN_RPC_URL.")
        abi = [{
            "inputs": [
                {"internalType": "string", "name": "eventId", "type": "string"},
                {"internalType": "string", "name": "recordId", "type": "string"},
                {"internalType": "string", "name": "eventType", "type": "string"},
                {"internalType": "string", "name": "payloadHash", "type": "string"},
            ],
            "name": "recordEvent", "outputs": [],
            "stateMutability": "nonpayable", "type": "function",
        }]
        contract = web3.eth.contract(
            address=Web3.to_checksum_address(BLOCKCHAIN_CONTRACT_ADDRESS), abi=abi
        )
        account = web3.eth.account.from_key(BLOCKCHAIN_PRIVATE_KEY)
        return web3, contract, account
    except Exception as exc:
        raise RuntimeError(f"Blockchain connection/configuration error: {exc}") from exc


def append_ledger(event_type: str, record: dict, actor: str, notes: str = "") -> dict:
    entries = load_ledger()
    previous_hash = entries[-1]["entry_hash"] if entries else "GENESIS"
    entry = {
        "event_id": str(uuid.uuid4()),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "workflow_stage": (
            "Initiation" if "Initiation" in event_type
            else "Control" if "Control" in event_type or "Inspection" in event_type
            else "Validation" if "Validation" in event_type or "Approved" in event_type or "Rejected" in event_type
            else "Traceability"
        ),
        "record_id": str(record.get("record_id", "")),
        "tree_lot_id": str(record.get("tree_lot_id", "")),
        "species": str(record.get("species", "")),
        "region": str(record.get("region", "")),
        "volume_m3": float(record.get("volume_m3") or 0),
        "latitude": float(record.get("latitude")) if pd.notna(record.get("latitude")) else None,
        "longitude": float(record.get("longitude")) if pd.notna(record.get("longitude")) else None,
        "status": str(record.get("status", "")),
        "permit_id": str(record.get("permit_id", "")),
        "actor": actor.strip(),
        "notes": notes.strip(),
        "previous_hash": previous_hash,
        "blockchain_tx_hash": "",
        "blockchain_status": "Local hash-chain only",
    }
    entry["entry_hash"] = calculate_hash(entry)

    # Optional on-chain anchoring: submit event ID, record ID, event type and payload hash.
    client = get_blockchain_client()
    if client is not None:
        web3, contract, account = client
        tx = contract.functions.recordEvent(
            entry["event_id"], entry["record_id"], entry["event_type"], entry["entry_hash"]
        ).build_transaction({
            "from": account.address,
            "nonce": web3.eth.get_transaction_count(account.address),
            "chainId": web3.eth.chain_id,
            "gas": 300000,
            "gasPrice": web3.eth.gas_price,
        })
        signed_tx = account.sign_transaction(tx)
        raw_tx = getattr(signed_tx, "raw_transaction", None) or signed_tx.rawTransaction
        tx_hash = web3.eth.send_raw_transaction(raw_tx)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if int(receipt.status) != 1:
            raise RuntimeError("Blockchain transaction failed.")
        entry["blockchain_tx_hash"] = tx_hash.hex()
        entry["blockchain_status"] = "Confirmed on configured EVM chain"
        entry["entry_hash"] = calculate_hash(entry)

    entries.append(entry)
    save_ledger(entries)
    return entry


# ---------------------------------------------------------------------
# UI controls
# ---------------------------------------------------------------------
record_options = records["record_id"].dropna().astype(str).tolist()
if not record_options:
    record_options = ["(no records)"]

record_select = pn.widgets.Select(name="Traceability record", options=record_options, value=record_options[0])
event_select = pn.widgets.Select(
    name="New lifecycle event",
    options=["Initiation submitted", "Registered", "Harvested", "Transport dispatched", "Received at mill", "Processed", "Exported", "Control performed", "Validation approved", "Validation rejected", "Inspection"],
    value="Initiation submitted",
)
actor_input = pn.widgets.TextInput(name="Operator / actor", placeholder="e.g., Forest officer or company")
notes_input = pn.widgets.TextAreaInput(name="Event notes", placeholder="Permit checks, inspection notes, document references…", height=90)
add_event_button = pn.widgets.Button(name="Record event / submit to blockchain", button_type="primary")
verify_button = pn.widgets.Button(name="Verify ledger integrity", button_type="success")
ledger_status = pn.pane.Alert("Ledger not yet checked.", alert_type="info")
event_table = pn.widgets.Tabulator(pd.DataFrame(), pagination="local", page_size=10, height=320, sizing_mode="stretch_width")
notice = pn.pane.Markdown("")


def selected_record() -> dict:
    match = records.loc[records["record_id"].astype(str) == str(record_select.value)]
    return match.iloc[0].to_dict() if not match.empty else {}


def selected_record_frame() -> pd.DataFrame:
    """Return the selected record as a one-row frame for cross-tab filtering."""
    return records.loc[records["record_id"].astype(str) == str(record_select.value)].copy()


def selected_ledger_entries() -> list[dict]:
    """Ledger events for the selected record."""
    return [entry for entry in load_ledger()
            if str(entry.get("record_id", "")) == str(record_select.value)]


def refresh_ledger():
    entries = selected_ledger_entries()
    view = pd.DataFrame(entries)
    event_table.value = view.tail(200) if not view.empty else pd.DataFrame(
        columns=["timestamp_utc", "event_type", "record_id", "tree_lot_id", "actor", "entry_hash"]
    )


def on_record_selection_change(_=None):
    refresh_ledger()


def on_add_event(_):
    actor = actor_input.value.strip()
    if not actor:
        ledger_status.object = "Enter an operator/actor before recording an event."
        ledger_status.alert_type = "warning"
        return
    record = selected_record()
    if not record:
        ledger_status.object = "No valid traceability record is selected."
        ledger_status.alert_type = "warning"
        return
    try:
        entry = append_ledger(event_select.value, record, actor, notes_input.value)
        refresh_ledger()
        ledger_status.object = (
            f"Event recorded. **{entry.get('blockchain_status', 'Local hash-chain only')}**. "
            f"Hash: `{entry['entry_hash'][:20]}…`"
            + (f" Transaction: `{entry['blockchain_tx_hash'][:18]}…`"
               if entry.get("blockchain_tx_hash") else "")
        )
        ledger_status.alert_type = "success"
    except Exception as exc:
        ledger_status.object = f"Could not record event: {exc}"
        ledger_status.alert_type = "danger"


def on_verify(_):
    entries = load_ledger()
    ok, message = verify_ledger(entries)
    ledger_status.object = ("**Ledger integrity OK:** " if ok else "**Ledger integrity FAILED:** ") + message
    ledger_status.alert_type = "success" if ok else "danger"
    refresh_ledger()


add_event_button.on_click(on_add_event)
verify_button.on_click(on_verify)
record_select.param.watch(on_record_selection_change, "value")
refresh_ledger()

# ---------------------------------------------------------------------
# GIS map: Plotly point map always available; ArcGIS WebMap embed optional.
# ---------------------------------------------------------------------
def make_forest_map(frame: pd.DataFrame):
    valid = frame.dropna(subset=["latitude", "longitude"]).copy()
    valid = valid[valid["latitude"].between(-90, 90) & valid["longitude"].between(-180, 180)]
    if valid.empty:
        fig = go.Figure()
        fig.update_layout(title="Forest traceability locations", template="plotly_white",
                          annotations=[dict(text="No valid coordinates in current records.", x=.5, y=.5,
                                            xref="paper", yref="paper", showarrow=False)])
        return fig
    fig = px.scatter_mapbox(
        valid, lat="latitude", lon="longitude", color="status", size="volume_m3",
        hover_name="tree_lot_id",
        hover_data=["record_id", "species", "region", "permit_id", "operator", "destination"],
        zoom=4, height=560, title="Timber lots and traceability events (coordinates must be verified)"
    )
    fig.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=50, b=0))
    return fig


@pn.depends(record_select.param.value)
def selected_record_map(_record_id):
    frame = selected_record_frame()
    fig = make_forest_map(frame)
    fig.update_layout(title=f"Selected timber lot: {_record_id}")
    return pn.pane.Plotly(fig, sizing_mode="stretch_width", height=580)


map_pane = selected_record_map
arcgis_pane = pn.pane.HTML(
    f'<iframe title="ArcGIS Web Map" width="100%" height="580" frameborder="0" '
    f'src="https://www.arcgis.com/apps/instant/basic/index.html?appid={ARCGIS_WEBMAP_ID}"></iframe>',
    sizing_mode="stretch_width", height=590
) if ARCGIS_WEBMAP_ID else pn.pane.Markdown(
    "### Optional ArcGIS Online integration\n"
    "Set environment variable `ARCGIS_WEBMAP_ID` to the ID of a published ArcGIS Online Web Map. "
    "The app will embed that map here. This prototype uses a Plotly map by default; it does not "
    "authenticate to ArcGIS or publish edits to a GIS service."
)


# ---------------------------------------------------------------------
# Descriptive dashboard
# ---------------------------------------------------------------------
@pn.depends(record_select.param.value)
def summary_view(selected_id):
    data = selected_record_frame()
    if data.empty:
        return pn.pane.Alert("No matching traceability record is selected.", alert_type="warning")
    total_volume = float(data["volume_m3"].sum(skipna=True))
    ledger_entries = selected_ledger_entries()
    missing_coords = int(data[["latitude", "longitude"]].isna().any(axis=1).sum())
    cards = pn.Row(
        pn.indicators.Number(name="Selected record", value=1, format="{value:,.0f}"),
        pn.indicators.Number(name="Recorded volume (m³)", value=total_volume, format="{value:,.2f}"),
        pn.indicators.Number(name="Audit events", value=len(ledger_entries), format="{value:,.0f}"),
        pn.indicators.Number(name="Missing coordinates", value=missing_coords, format="{value:,.0f}"),
        sizing_mode="stretch_width",
    )
    status_counts = data["status"].fillna("Unknown").value_counts().rename_axis("status").reset_index(name="count")
    fig_status = px.bar(status_counts, x="status", y="count", title="Selected record status", template="plotly_white")
    species_volume = data.groupby("species", dropna=False)["volume_m3"].sum().reset_index()
    fig_species = px.pie(species_volume, names="species", values="volume_m3", title="Selected record volume by species", template="plotly_white")
    region_volume = data.groupby("region", dropna=False)["volume_m3"].sum().reset_index()
    fig_region = px.bar(region_volume, x="region", y="volume_m3", title="Selected record volume by region", template="plotly_white")
    detail_cols = ["record_id", "tree_lot_id", "species", "region", "harvest_date",
                   "volume_m3", "status", "permit_id", "operator", "destination",
                   "latitude", "longitude"]
    detail_table = pn.widgets.Tabulator(data[detail_cols], show_index=False, height=100, sizing_mode="stretch_width")
    return pn.Column(
        pn.pane.Markdown(f"### Traceability summary: `{selected_id}`"),
        cards,
        detail_table,
        pn.Row(pn.pane.Plotly(fig_status, height=300), pn.pane.Plotly(fig_species, height=300)),
        pn.pane.Plotly(fig_region, height=320),
        sizing_mode="stretch_width",
    )


# Record explorer and exports
# ---------------------------------------------------------------------
region_filter = pn.widgets.MultiChoice(name="Filter by region", options=sorted(records["region"].dropna().astype(str).unique()), value=[])
status_filter = pn.widgets.MultiChoice(name="Filter by status", options=sorted(records["status"].dropna().astype(str).unique()), value=[])
search_input = pn.widgets.TextInput(name="Search lot, permit, species, operator", placeholder="Type a keyword…")
export_button = pn.widgets.Button(name="Export filtered records to CSV", button_type="primary")
export_status = pn.pane.Markdown("")


def filtered_records():
    # The sidebar dropdown is the shared record selection across all tabs.
    frame = selected_record_frame()
    if region_filter.value:
        frame = frame[frame["region"].astype(str).isin(region_filter.value)]
    if status_filter.value:
        frame = frame[frame["status"].astype(str).isin(status_filter.value)]
    term = search_input.value.strip().lower()
    if term:
        cols = ["tree_lot_id", "permit_id", "species", "operator", "destination", "record_id"]
        mask = frame[cols].fillna("").astype(str).apply(lambda col: col.str.lower().str.contains(term, regex=False)).any(axis=1)
        frame = frame[mask]
    return frame


@pn.depends(record_select.param.value, region_filter.param.value, status_filter.param.value, search_input.param.value)
def record_explorer(*_):
    return pn.widgets.Tabulator(filtered_records(), pagination="local", page_size=15, height=450, sizing_mode="stretch_width")


def on_export(_):
    frame = filtered_records()
    out = Path("forestchain_filtered_records.csv")
    frame.to_csv(out, index=False)
    export_status.object = f"Exported **{len(frame)} rows** to `{out.resolve()}`."


export_button.on_click(on_export)

# ---------------------------------------------------------------------
# Forestry control path: initiation -> control -> validation
# ---------------------------------------------------------------------
control_actor = pn.widgets.TextInput(name="Controller / inspector", placeholder="Name or institutional ID")
control_result = pn.widgets.Select(
    name="Control result",
    options=["Pending", "Compliant", "Non-compliant", "More evidence required"],
    value="Pending",
)
control_notes = pn.widgets.TextAreaInput(
    name="Control checklist / evidence references",
    placeholder="Permit, concession, GIS coordinates, species, volume, transport documents…",
    height=100,
)
control_button = pn.widgets.Button(name="Record control decision", button_type="primary")
validator_actor = pn.widgets.TextInput(name="Authorized validator", placeholder="Name or institutional ID")
validation_result = pn.widgets.Select(
    name="Validation decision",
    options=["Approved", "Rejected", "Returned for correction"],
    value="Approved",
)
validation_notes = pn.widgets.TextAreaInput(
    name="Validation justification",
    placeholder="Explain the decision and cite supporting evidence.",
    height=90,
)
validation_button = pn.widgets.Button(name="Record validation decision", button_type="success")
workflow_status = pn.pane.Alert("Initiate the record, complete the control step, then validate.", alert_type="info")


def on_control_decision(_):
    actor = control_actor.value.strip()
    if not actor:
        workflow_status.object = "Enter the controller/inspector identity."
        workflow_status.alert_type = "warning"
        return
    if control_result.value == "Pending":
        workflow_status.object = "Select a completed control result before recording it."
        workflow_status.alert_type = "warning"
        return
    try:
        entry = append_ledger(
            f"Control performed — {control_result.value}",
            selected_record(), actor, control_notes.value
        )
        refresh_ledger()
        workflow_status.object = (
            f"Control recorded: **{control_result.value}**. Hash: `{entry['entry_hash'][:20]}…`"
        )
        workflow_status.alert_type = "success"
    except Exception as exc:
        workflow_status.object = f"Could not record control event: {exc}"
        workflow_status.alert_type = "danger"


def on_validation_decision(_):
    actor = validator_actor.value.strip()
    if not actor:
        workflow_status.object = "Enter the authorized validator identity."
        workflow_status.alert_type = "warning"
        return
    if not control_actor.value.strip():
        workflow_status.object = "Record the control step before validation."
        workflow_status.alert_type = "warning"
        return
    if control_result.value != "Compliant" and validation_result.value == "Approved":
        workflow_status.object = (
            "Approval blocked: the control result must be Compliant. "
            "Resolve the finding or return the case for correction."
        )
        workflow_status.alert_type = "warning"
        return
    try:
        entry = append_ledger(
            f"Validation {validation_result.value}",
            selected_record(), actor, validation_notes.value
        )
        refresh_ledger()
        workflow_status.object = (
            f"Validation recorded: **{validation_result.value}**. Hash: `{entry['entry_hash'][:20]}…`"
        )
        workflow_status.alert_type = "success"
    except Exception as exc:
        workflow_status.object = f"Could not record validation: {exc}"
        workflow_status.alert_type = "danger"


control_button.on_click(on_control_decision)
validation_button.on_click(on_validation_decision)

control_path_panel = pn.Column(
    pn.pane.Markdown(
        """
## Forestry control path

**Shared selection:** the timber record selected in the left sidebar is used by Overview, GIS Map, Record Explorer, this workflow, and Blockchain Audit Ledger.

**1. Initiation — operator / forest manager**
- Select the timber lot and submit the initiation event.
- Capture the lot ID, permit, species, declared volume, harvest location and evidence references.
- Initiation does not mean the timber is compliant or approved.

**2. Control — controller / inspector**
- Check the permit and concession, GIS coordinates, harvest date, species, volume, transport documents and chain of custody.
- Record *Compliant*, *Non-compliant*, or *More evidence required*.
- The control finding is an auditable inspection result, not the final authorization.

**3. Validation — authorized official**
- Review the initiation data and control evidence.
- This prototype blocks an **Approved** decision unless the selected control result is **Compliant**.
- Record approval, rejection, or return for correction with a justification.

**4. Blockchain audit**
- Events are timestamped and linked through hashes in the local audit mirror.
- When an EVM-compatible blockchain is configured, the app submits the event ID, record ID, event type and payload hash to a smart contract.
- Store confidential documents in controlled storage; put only their fingerprints/references on-chain.
"""
    ),
    pn.layout.Divider(),
    pn.pane.Markdown("### Control and inspection"),
    control_actor, control_result, control_notes, control_button,
    pn.layout.Divider(),
    pn.pane.Markdown("### Final validation"),
    validator_actor, validation_result, validation_notes, validation_button,
    workflow_status,
    sizing_mode="stretch_width",
)

# ---------------------------------------------------------------------
# Layout modeled on the uploaded dashboard: sidebar + tabs + FastListTemplate
# ---------------------------------------------------------------------
sidebar = pn.Column(
    pn.pane.Markdown("## ForestChain controls"),
    pn.pane.Markdown(source_note),
    record_select,
    event_select,
    actor_input,
    notes_input,
    pn.Row(add_event_button, verify_button),
    ledger_status,
    pn.layout.Divider(),
    pn.pane.Markdown("### Record filters"),
    region_filter,
    status_filter,
    search_input,
    export_button,
    export_status,
    width=440,
    min_width=420,
)

tabs = pn.Tabs(
    ("Overview", summary_view),
    ("GIS Map", pn.Column(
        pn.pane.Markdown("Locations are illustrative in demo mode. Verify coordinates against authoritative GIS layers."),
        map_pane
    )),
    ("ArcGIS Web Map", arcgis_pane),
    ("Record Explorer", record_explorer),
    ("Initiation • Control • Validation", control_path_panel),
    ("Blockchain Audit Ledger", pn.Column(
        pn.pane.Markdown(
            "The ledger below is filtered by the selected timber record. The app maintains a local hash-chain audit mirror and can submit event fingerprints to a configured EVM-compatible blockchain. "
            "Production use requires a permissioned network, audited smart contract, institutional identities, role-based approvals, backups and governance."
        ),
        event_table,
        sizing_mode="stretch_width"
    )),
    dynamic=True,
)

template = pn.template.FastListTemplate(
    title=APP_TITLE,
    sidebar=[sidebar],
    sidebar_width=460,
    main=[
        pn.pane.Markdown(
            "Track timber lots from registration to harvest, transport, processing and export. "
            "Explore GIS locations, follow initiation → control → validation, and preserve an auditable traceability history with optional blockchain transaction anchoring."
        ),
        tabs,
    ],
    accent_base_color="#26734d",
    header_background="#17452b",
)
template.servable()
