from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from contextlib import asynccontextmanager

import os
import json
import asyncio
import logging
import hashlib
from datetime import datetime, timedelta

import requests
import httpx
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# -------------------------
# Load env
# -------------------------
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

# accept either GOOGLE_CALENDAR_ID or your old GOOGLE_CALENDAR_ID_LOCAL
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID") or os.getenv("GOOGLE_CALENDAR_ID_LOCAL") or "primary"

GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

# IMPORTANT: multi data sources require new version (based on your error)
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")

SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "300"))
DATA_SOURCE_ID = os.getenv("DATA_SOURCE_ID", "")
SYNC_API_KEY = os.getenv("SYNC_API_KEY", "")  # optional

if not NOTION_TOKEN:
    raise ValueError("NOTION_TOKEN environment variable is required")
if not DATABASE_ID:
    raise ValueError("DATABASE_ID environment variable is required")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

SYNC_MAPPING_FILE = "sync_mapping.json"
ERROR_LOG_FILE = "error.log"

# -------------------------
# Logging
# -------------------------
logger = logging.getLogger("notion-calendar-sync")
logger.setLevel(logging.INFO)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s | %(message)s"))
logger.addHandler(ch)

fh = logging.FileHandler("sync.log", encoding="utf-8")
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s | %(message)s"))
logger.addHandler(fh)

eh = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")
eh.setLevel(logging.ERROR)
eh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s | %(message)s"))
logger.addHandler(eh)

# -------------------------
# Security (optional API key)
# -------------------------
def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    if not SYNC_API_KEY:
        return
    if not x_api_key or x_api_key != SYNC_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized: missing/invalid X-API-Key")

# -------------------------
# Notion headers
# -------------------------
def notion_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

# -------------------------
# Models
# -------------------------
class NotionItem(BaseModel):
    Project_name: Optional[str] = ""
    Assign_Date: Optional[str] = None
    Attach_file: Optional[str] = None
    Customer_Name: Optional[str] = ""
    End_date: Optional[str] = None
    Start_date: Optional[str] = None
    Status: Optional[str] = None
    Task_Type: Optional[str] = None
    Tasks_Tracker: Optional[str] = ""

class NotionResponse(BaseModel):
    data: List[NotionItem]

# -------------------------
# Mapping helpers
# -------------------------
def load_sync_mapping() -> Dict[str, Any]:
    if os.path.exists(SYNC_MAPPING_FILE):
        try:
            with open(SYNC_MAPPING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_sync_mapping(mapping: Dict[str, Any]):
    with open(SYNC_MAPPING_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)

def stable_item_hash(item: Dict[str, Any]) -> str:
    # We add a version marker here to force a re-sync of all items
    # whenever we change the core sync logic (like switching to "End Date Only").
    item_with_version = item.copy()
    item_with_version["_sync_version"] = "2.0.1" 
    payload = json.dumps(item_with_version, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# -------------------------
# Notion property extractors
# -------------------------
def get_title(prop: Dict[str, Any]) -> str:
    try:
        title_list = prop.get("title", [])
        if title_list:
            return title_list[0].get("plain_text", "") or ""
        return ""
    except Exception:
        return ""

def get_rich_text(prop: Dict[str, Any]) -> str:
    try:
        rt_list = prop.get("rich_text", [])
        if rt_list:
            return rt_list[0].get("plain_text", "") or ""
        return ""
    except Exception:
        return ""

def get_date(prop: Dict[str, Any]) -> Optional[str]:
    try:
        date_obj = prop.get("date")
        if isinstance(date_obj, dict):
            return date_obj.get("start")
        return None
    except Exception:
        return None

def get_date_end(prop: Dict[str, Any]) -> Optional[str]:
    try:
        date_obj = prop.get("date")
        if isinstance(date_obj, dict):
            return date_obj.get("end")
        return None
    except Exception:
        return None

def get_select(prop: Dict[str, Any]) -> Optional[str]:
    try:
        if "status" in prop and isinstance(prop["status"], dict):
            return prop["status"].get("name")
        if "select" in prop and isinstance(prop["select"], dict):
            return prop["select"].get("name")
        if "multi_select" in prop and isinstance(prop["multi_select"], list):
            vals = [s.get("name") for s in prop["multi_select"] if s.get("name")]
            return ", ".join(vals) if vals else None
        return None
    except Exception:
        return None

def get_files(prop: Dict[str, Any]) -> Optional[str]:
    try:
        files_list = prop.get("files", [])
        if files_list:
            f0 = files_list[0]
            if "file" in f0 and isinstance(f0["file"], dict):
                return f0["file"].get("url", "")
            if "external" in f0 and isinstance(f0["external"], dict):
                return f0["external"].get("url", "")
        return None
    except Exception:
        return None

# -------------------------
# Notion query (CORRECT ENDPOINT)
# -------------------------
async def notion_query_all_pages() -> List[Dict[str, Any]]:
    """
    Fetch ALL rows from database using:
      - New path: /v1/data_sources/{DATA_SOURCE_ID}/query (if DATA_SOURCE_ID exists)
      - Legacy path: /v1/databases/{DATABASE_ID}/query
    """
    if DATA_SOURCE_ID:
        url = f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query"
    else:
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"

    all_results: List[Dict[str, Any]] = []
    payload: Dict[str, Any] = {"page_size": 100}

    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.post(url, headers=notion_headers(), json=payload, timeout=60.0)
            if not resp.is_success:
                raise HTTPException(status_code=resp.status_code, detail=f"Notion query failed: {resp.text}")

            data = resp.json()
            all_results.extend(data.get("results", []))

            if not data.get("has_more"):
                break

            payload["start_cursor"] = data.get("next_cursor")

    return all_results

async def notion_items_with_ids() -> Dict[str, Dict[str, Any]]:
    pages = await notion_query_all_pages()
    out: Dict[str, Dict[str, Any]] = {}

    for page in pages:
        page_id = page.get("id")
        props = page.get("properties") or {}
        if not page_id or not props:
            continue

        item = {
            "Project_name": get_title(props.get("Project name", {})) or get_title(props.get("Task name", {})),
            "Assign_Date": get_date(props.get("Assign Date", {})),
            "Attach_file": get_files(props.get("Attach file", {})),
            "Customer_Name": get_rich_text(props.get("Customer Name", {})),
            "End_date": get_date(props.get("End date", {})) or get_date_end(props.get("Due date", {})),
            "Start_date": get_date(props.get("Start date", {})) or get_date(props.get("Due date", {})),
            "Status": get_select(props.get("Status", {})),
            "Task_Type": get_select(props.get("Task Type", {})),
            "Tasks_Tracker": get_rich_text(props.get("Tasks Tracker", {})) or get_rich_text(props.get("Description", {})),
        }
        out[page_id] = item

    return out

# -------------------------
# Google Calendar
# -------------------------
def get_google_calendar_service():
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise HTTPException(status_code=500, detail=f"Missing {GOOGLE_CREDENTIALS_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

SYNC_MARKER_KEY = "notion_sync"
SYNC_MARKER_VAL = "true"

# Google Calendar Color IDs
# 1: Blue, 2: Light Green, 3: Purple, 4: Pink, 5: Yellow, 
# 6: Orange, 7: Light Blue, 8: Grey, 9: Dark Blue, 10: Green, 11: Red
STATUS_COLORS = {
    "To Do (Pending)": "8",                   # Grey
    "Discussion with Client Required": "5",   # Yellow (Banana)
    "In progress": "9",                       # Blue (Blueberry)
    "Discussion with Dev Team Required": "3", # Purple (Grape)
    "Costing": "3",                           # Purple (Grape)
    "Pending Client Approval": "4",           # Pink (Flamingo)
    "Marketing": "4",                         # Pink (Flamingo)
    "Development": "8",                       # Grey
    "UAT Client Approval Pending": "6",       # Orange (Tangerine)
    "Hold": "8",                              # Brown/Grey
    "Canceled": "11",                         # Red (Tomato)
    "Rejected": "11",                         # Red (Tomato)
    "Done": "10",                             # Green (Basil)
}

def parse_notion_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    date_part = date_str.split("T")[0]
    try:
        return datetime.strptime(date_part, "%Y-%m-%d")
    except Exception:
        return None

def build_event_description(item: Dict[str, Any]) -> str:
    parts = []
    if item.get("Customer_Name"):
        parts.append(f"Customer: {item['Customer_Name']}")
    if item.get("Status"):
        parts.append(f"Status: {item['Status']}")
    if item.get("Task_Type"):
        parts.append(f"Task Type: {item['Task_Type']}")
    if item.get("Tasks_Tracker"):
        parts.append(f"Tasks Tracker: {item['Tasks_Tracker']}")
    if item.get("Attach_file"):
        parts.append(f"Attachment: {item['Attach_file']}")
    return "\n".join(parts)

def create_events_for_item(service, item: Dict[str, Any]) -> List[str]:
    # Use End_date if available, otherwise Start_date
    target_dt_str = item.get("End_date") or item.get("Start_date")
    target_dt = parse_notion_date(target_dt_str)
    
    if not target_dt:
        return []

    summary = item.get("Project_name") or "Untitled Project"
    logger.info(f"Creating event for '{summary}' on {target_dt.strftime('%Y-%m-%d')}")
    
    body = {
        "summary": summary,
        "description": build_event_description(item),
        "start": {"date": target_dt.strftime("%Y-%m-%d")},
        "end": {"date": (target_dt + timedelta(days=1)).strftime("%Y-%m-%d")},
        "colorId": STATUS_COLORS.get(item.get("Status"), "1"),
        "extendedProperties": {"private": {SYNC_MARKER_KEY: SYNC_MARKER_VAL}},
    }
    
    try:
        created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()
        if created and created.get("id"):
            return [created.get("id")]
    except Exception as e:
        logger.error(f"Create event failed: {e}", exc_info=True)
            
    return []

def delete_event(service, event_id: str) -> bool:
    try:
        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        return True
    except HttpError as e:
        if getattr(e, "resp", None) and e.resp.status == 404:
            return True
        logger.error(f"Delete event failed ({event_id}): {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Delete event failed ({event_id}): {e}", exc_info=True)
        return False

def list_synced_events(service) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    page_token = None
    while True:
        resp = service.events().list(calendarId=GOOGLE_CALENDAR_ID, maxResults=2500, pageToken=page_token).execute()
        for ev in resp.get("items", []):
            priv = (ev.get("extendedProperties") or {}).get("private") or {}
            if priv.get(SYNC_MARKER_KEY) == SYNC_MARKER_VAL:
                events.append(ev)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events

# -------------------------
# Sync core
# -------------------------
def run_sync_internal() -> Dict[str, Any]:
    logger.info("Starting calendar sync...")
    service = get_google_calendar_service()

    sync_mapping = load_sync_mapping()
    notion_items = notion_items_with_ids()

    created = updated = deleted = skipped = 0

    for page_id, item in notion_items.items():
        if not item.get("Start_date") and not item.get("End_date"):
            skipped += 1
            continue

        new_hash = stable_item_hash(item)

async def process_single_item(service, page_id, item, sync_mapping, stats):
    new_hash = stable_item_hash(item)
    
    # Use to_thread for blocking Google API calls
    if page_id in sync_mapping:
        old_event_ids = sync_mapping[page_id].get("event_ids", [])
        legacy_event_id = sync_mapping[page_id].get("event_id")
        if legacy_event_id and legacy_event_id not in old_event_ids:
            old_event_ids.append(legacy_event_id)

        old_hash = sync_mapping[page_id].get("hash")

        if old_hash != new_hash:
            # Delete old events concurrently
            delete_tasks = [asyncio.to_thread(delete_event, service, eid) for eid in old_event_ids]
            await asyncio.gather(*delete_tasks)
            
            # Create new event
            new_event_ids = await asyncio.to_thread(create_events_for_item, service, item)
            if new_event_ids:
                sync_mapping[page_id] = {"event_ids": new_event_ids, "hash": new_hash, **item}
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            sync_mapping[page_id] = {"event_ids": old_event_ids, "hash": old_hash, **item}
    else:
        new_event_ids = await asyncio.to_thread(create_events_for_item, service, item)
        if new_event_ids:
            sync_mapping[page_id] = {"event_ids": new_event_ids, "hash": new_hash, **item}
            stats["created"] += 1
        else:
            stats["skipped"] += 1

async def run_sync_internal() -> Dict[str, Any]:
    logger.info("Starting calendar sync...")
    service = await asyncio.to_thread(get_google_calendar_service)

    sync_mapping = load_sync_mapping()
    notion_items = await notion_items_with_ids()

    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
    
    # Process active items in parallel (limit concurrency to 10)
    semaphore = asyncio.Semaphore(10)
    async def sem_process(pid, itm):
        async with semaphore:
            await process_single_item(service, pid, itm, sync_mapping, stats)

    active_tasks = [sem_process(pid, itm) for pid, itm in notion_items.items() 
                    if itm.get("Start_date") or itm.get("End_date")]
    
    # Count skipped items that have no dates
    stats["skipped"] += len(notion_items) - len(active_tasks)
    
    if active_tasks:
        await asyncio.gather(*active_tasks)

    # Handle removals
    notion_ids = set(notion_items.keys())
    mapped_ids = set(sync_mapping.keys())
    removed_ids = list(mapped_ids - notion_ids)
    
    if removed_ids:
        async def remove_item(removed_id):
            async with semaphore:
                ev_ids = sync_mapping.get(removed_id, {}).get("event_ids", [])
                legacy_ev_id = sync_mapping.get(removed_id, {}).get("event_id")
                if legacy_ev_id and legacy_ev_id not in ev_ids:
                    ev_ids.append(legacy_ev_id)
                    
                delete_tasks = [asyncio.to_thread(delete_event, service, eid) for eid in ev_ids]
                results = await asyncio.gather(*delete_tasks)
                stats["deleted"] += sum(1 for r in results if r)
                sync_mapping.pop(removed_id, None)

        await asyncio.gather(*[remove_item(rid) for rid in removed_ids])

    save_sync_mapping(sync_mapping)

    return {
        "status": "success",
        "created": stats["created"],
        "updated": stats["updated"],
        "deleted": stats["deleted"],
        "skipped": stats["skipped"],
        "total_notion_items": len(notion_items),
        "total_synced": len(sync_mapping),
    }

# -------------------------
# Auto sync loop + lifespan
# -------------------------
auto_sync_enabled = True
auto_sync_task_handle: Optional[asyncio.Task] = None

async def auto_sync_loop():
    global auto_sync_enabled
    await asyncio.sleep(2)
    logger.info(f"Auto-sync loop started (interval={SYNC_INTERVAL}s)")

    while auto_sync_enabled:
        try:
            await run_sync_internal()
            logger.info("Auto-sync completed")
        except Exception as e:
            logger.error(f"Auto-sync failed: {e}", exc_info=True)

        await asyncio.sleep(SYNC_INTERVAL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global auto_sync_enabled, auto_sync_task_handle

    auto_sync_enabled = True
    auto_sync_task_handle = asyncio.create_task(auto_sync_loop())
    logger.info("Application started. Auto-sync scheduled.")
    yield
    auto_sync_enabled = False
    if auto_sync_task_handle and not auto_sync_task_handle.done():
        auto_sync_task_handle.cancel()

app = FastAPI(
    title="Notion → Google Calendar Sync API",
    version="3.0.0",
    lifespan=lifespan,
)

# -------------------------
# Endpoints
# -------------------------
@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/docs")

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy"}

@app.get("/get-data", response_model=NotionResponse, tags=["Notion"])
async def get_data():
    items = await notion_items_with_ids()
    results = list(items.values())
    results.sort(key=lambda x: (x.get("Project_name", "").lower(), x.get("Start_date") or ""))
    return {"data": results}

@app.post("/sync-calendar", tags=["Calendar Sync"])
async def sync_calendar(_: Any = Depends(require_api_key)):
    return await run_sync_internal()

@app.post("/clear-calendar", tags=["Calendar Management"])
async def clear_calendar(_: Any = Depends(require_api_key)):
    service = await asyncio.to_thread(get_google_calendar_service)
    synced = await asyncio.to_thread(list_synced_events, service)
    
    if not synced:
        return {"status": "success", "deleted": 0}

    # Parallelize deletion
    delete_tasks = []
    for ev in synced:
        ev_id = ev.get("id")
        if ev_id:
            delete_tasks.append(asyncio.to_thread(delete_event, service, ev_id))
    
    results = await asyncio.gather(*delete_tasks)
    deleted_count = sum(1 for r in results if r)
    
    save_sync_mapping({})
    return {"status": "success", "deleted": deleted_count}

@app.get("/auto-sync/status", tags=["Auto Sync"])
def auto_sync_status():
    return {
        "auto_sync_enabled": auto_sync_enabled,
        "interval_seconds": SYNC_INTERVAL,
        "task_running": bool(auto_sync_task_handle and not auto_sync_task_handle.done()),
    }

@app.get("/auto-sync/stop", tags=["Auto Sync"])
def stop_auto_sync(_: Any = Depends(require_api_key)):
    global auto_sync_enabled, auto_sync_task_handle
    auto_sync_enabled = False
    if auto_sync_task_handle and not auto_sync_task_handle.done():
        auto_sync_task_handle.cancel()
    return {"status": "success", "message": "Auto-sync stopped"}

@app.get("/auto-sync/start", tags=["Auto Sync"])
def start_auto_sync(_: Any = Depends(require_api_key)):
    global auto_sync_enabled, auto_sync_task_handle
    auto_sync_enabled = True
    if not auto_sync_task_handle or auto_sync_task_handle.done():
        auto_sync_task_handle = asyncio.create_task(auto_sync_loop())
    return {"status": "success", "message": "Auto-sync started"}

@app.get("/logs/latest", tags=["Logs"])
def get_latest_logs():
    try:
        with open("sync.log", "r", encoding="utf-8") as f:
            lines = f.readlines()
        return {"status": "success", "logs": lines[-50:] if len(lines) > 50 else lines}
    except FileNotFoundError:
        return {"status": "error", "message": "Log file not found"}

# -------------------------
# Run directly
# -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
