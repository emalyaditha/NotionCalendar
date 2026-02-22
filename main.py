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
    Sync_Hash: Optional[str] = None
    Sync_Event_IDs: Optional[str] = None

class NotionResponse(BaseModel):
    data: List[NotionItem]

# -------------------------
# Mapping helpers (REMOVED: Now using Notion properties)
# -------------------------

def stable_item_hash(item: Dict[str, Any]) -> str:
    # We exclude the sync metadata from the hash calculation
    # to avoid infinite update loops.
    item_copy = {k: v for k, v in item.items() if k not in ["Sync_Hash", "Sync_Event_IDs"]}
    item_copy["_sync_version"] = "2.0.1" 
    payload = json.dumps(item_copy, sort_keys=True, ensure_ascii=False)
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
# -------------------------
# Notion Client (Shared)
# -------------------------
notion_client = httpx.AsyncClient(timeout=60.0)

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

    while True:
        resp = await notion_client.post(url, headers=notion_headers(), json=payload)
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
            "Sync_Hash": get_rich_text(props.get("Sync_Hash", {})),
            "Sync_Event_IDs": get_rich_text(props.get("Sync_Event_IDs", {})),
        }
        out[page_id] = item

    return out

async def patch_notion_page(page_id: str, properties: Dict[str, Any]):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = await notion_client.patch(url, headers=notion_headers(), json={"properties": properties})
    if not resp.is_success:
        logger.error(f"Failed to patch Notion page {page_id}: {resp.text}")
        return False
    return True

async def update_notion_sync_data(page_id: str, hash_val: str, event_ids: List[str]):
    props = {
        "Sync_Hash": {"rich_text": [{"text": {"content": hash_val}}]},
        "Sync_Event_IDs": {"rich_text": [{"text": {"content": ",".join(event_ids)}}]},
    }
    return await patch_notion_page(page_id, props)

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

def create_events_for_item(service, item: Dict[str, Any], page_id: str) -> List[str]:
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
        "extendedProperties": {
            "private": {
                SYNC_MARKER_KEY: SYNC_MARKER_VAL,
                "notion_page_id": page_id
            }
        },
    }
    
    try:
        created = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()
        if created and created.get("id"):
            return [created.get("id")]
    except Exception as e:
        logger.error(f"Event creation failed for {summary}: {e}")
            
    return []

# -------------------------
# Google Calendar Operations (Thread-Safe)
# -------------------------
def delete_event_threadsafe(event_id: str) -> bool:
    try:
        # Each thread gets its own service instance to be thread-safe
        service = get_google_calendar_service()
        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        return True
    except HttpError as e:
        if e.resp.status == 404:
            return True # Already deleted
        logger.error(f"Delete event failed ({event_id}): {e}")
        return False
    except Exception as e:
        logger.error(f"Delete event failed ({event_id}): {e}")
        return False

def create_event_threadsafe(item: Dict[str, Any], page_id: str) -> List[str]:
    try:
        service = get_google_calendar_service()
        return create_events_for_item(service, item, page_id)
    except Exception as e:
        logger.critical(f"Create event CRITICAL failed for {page_id}: {e}", exc_info=True)
        return []

def list_synced_events_threadsafe() -> List[Dict[str, Any]]:
    try:
        service = get_google_calendar_service()
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
    except Exception as e:
        logger.error(f"List synced events failed: {e}")
        return []

# -------------------------
# Core Sync Engine
# -------------------------
async def process_single_item(page_id: str, item: Dict[str, Any], stats: Dict[str, int]):
    new_hash = stable_item_hash(item)
    
    old_hash = item.get("Sync_Hash")
    old_event_ids_str = item.get("Sync_Event_IDs") or ""
    old_event_ids = [eid.strip() for eid in old_event_ids_str.split(",") if eid.strip()]

    # If hash matches, skip to save time and API quota
    if old_hash == new_hash:
        stats["skipped"] += 1
        return

    # Delete old events concurrently
    if old_event_ids:
        delete_tasks = [asyncio.to_thread(delete_event_threadsafe, eid) for eid in old_event_ids]
        await asyncio.gather(*delete_tasks)
    
    # Create new event (each thread build its own service instance)
    new_event_ids = await asyncio.to_thread(create_event_threadsafe, item, page_id)
    if new_event_ids:
        # Critical Step: Update Notion with new sync data
        success = await update_notion_sync_data(page_id, new_hash, new_event_ids)
        if success:
            if old_hash:
                stats["updated"] += 1
            else:
                stats["created"] += 1
        else:
            logger.error(f"Sync logic error: Event created but Notion update FAILED for {page_id}. This will cause a duplicate on next run!")
            # We don't rollback GCal here to avoid accidental deletion, 
            # but we log it as a critical error.
    else:
        stats.setdefault("failed", 0)
        stats["failed"] += 1

async def run_sync_internal() -> Dict[str, Any]:
    logger.info("Starting calendar sync (Notion-based storage)...")
    
    notion_items = await notion_items_with_ids()
    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0, "failed": 0}
    
    if not notion_items:
        logger.info("No Notion items found to sync.")
        return stats

    # Process items in parallel (limit concurrency to 10 to protect GCal API)
    # Semaphore prevents flooding Google with too many simultaneous connections
    semaphore = asyncio.Semaphore(10)
    async def sem_process(pid, itm):
        async with semaphore:
            await process_single_item(pid, itm, stats)

    # Only process items that have at least one valid date
    active_items = {pid: itm for pid, itm in notion_items.items() 
                    if itm.get("Start_date") or itm.get("End_date")}
    
    stats["skipped"] += len(notion_items) - len(active_items)
    
    if active_items:
        tasks = [sem_process(pid, itm) for pid, itm in active_items.items()]
        await asyncio.gather(*tasks)

    logger.info(f"Sync completed. Created: {stats['created']}, Updated: {stats['updated']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")
    
    return {
        "status": "success",
        "created": stats["created"],
        "updated": stats["updated"],
        "deleted": stats["deleted"],
        "skipped": stats["skipped"],
        "failed": stats["failed"],
        "total_notion_items": len(notion_items),
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
    synced = await asyncio.to_thread(list_synced_events_threadsafe)
    
    if not synced:
        deleted_count = 0
    else:
        # Parallelize deletion
        delete_tasks = [asyncio.to_thread(delete_event_threadsafe, ev.get("id")) 
                        for ev in synced if ev.get("id")]
        results = await asyncio.gather(*delete_tasks)
        deleted_count = sum(1 for r in results if r)
    
    # Also clear Notion properties for ALL items to force a full re-sync
    notion_items = await notion_items_with_ids()
    clear_tasks = []
    semaphore = asyncio.Semaphore(10)
    async def sem_clear(pid):
        async with semaphore:
            await update_notion_sync_data(pid, "", [])
    
    for pid in notion_items.keys():
        clear_tasks.append(sem_clear(pid))
    
    await asyncio.gather(*clear_tasks)
    
    return {"status": "success", "deleted": deleted_count, "notion_cleared": len(clear_tasks)}

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
