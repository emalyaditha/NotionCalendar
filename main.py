from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
from typing import List, Optional, Dict
import os
import requests
import json
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment variables from .env file
load_dotenv()

# Remove existing error log file if it exists
ERROR_LOG_FILE = "error.log"
if os.path.exists(ERROR_LOG_FILE):
    try:
        os.remove(ERROR_LOG_FILE)
    except:
        pass

# Set up clean and readable logging
class CleanFormatter(logging.Formatter):
    """Custom formatter for clean terminal output"""
    
    # Define color codes for different log levels
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        # Get timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        
        # For ERROR and CRITICAL levels, write to error log file only
        if record.levelno >= logging.ERROR:
            error_msg = f"[{timestamp}] {record.levelname} | {record.getMessage()}\n"
            if record.exc_info:
                error_msg += f"{self.formatException(record.exc_info)}\n"
            
            # Write to error log file
            try:
                with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(error_msg)
            except:
                pass  # If we can't write to file, continue anyway
            
            # Return empty string to prevent output to terminal
            return ""
        
        # Format for terminal output (only show INFO and WARNING in terminal)
        level_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        level_name = f"{level_color}{record.levelname:>8}{self.COLORS['RESET']}"
        formatted_message = f"[{timestamp}] {level_name} | {record.getMessage()}"
        return formatted_message

# Configure logging with clean formatter
logging.basicConfig(level=logging.INFO, handlers=[logging.FileHandler("sync.log")])
logger = logging.getLogger(__name__)

# Create console handler with clean formatter
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(CleanFormatter())
logger.addHandler(console_handler)

# Filter out ERROR and CRITICAL logs from console
class ConsoleFilter(logging.Filter):
    def filter(self, record):
        # Only allow INFO and WARNING levels to console
        return record.levelno < logging.ERROR

console_handler.addFilter(ConsoleFilter())

# Initialize FastAPI app
app = FastAPI(
    title="Notion Database API",
    description="API to fetch data from a Notion database",
    version="1.0.0"
)

# Global variable to control automatic sync
auto_sync_enabled = True

# Background task for automatic sync
async def auto_sync_task():
    """Run sync-calendar automatically at regular intervals."""
    # Wait for app to be ready
    await asyncio.sleep(5)
    
    while auto_sync_enabled:
        try:
            logger.info("=" * 60)
            logger.info("AUTOMATIC CALENDAR SYNC STARTED")
            logger.info("=" * 60)
            
            # Call the sync_calendar function
            result = sync_calendar()
            
            logger.info("SYNC COMPLETED SUCCESSFULLY")
            logger.info("-" * 40)
            logger.info(f"Projects Processed:")
            logger.info(f"   Created:  {result.get('created', 0):>3}")
            logger.info(f"   Updated:  {result.get('updated', 0):>3}")
            logger.info(f"   Deleted:  {result.get('deleted', 0):>3}")
            logger.info(f"   Skipped:  {result.get('skipped', 0):>3}")
            logger.info(f"   Total:    {result.get('total_notion_items', 0):>3}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error("AUTOMATIC SYNC FAILED")
            logger.error(f"   Error: {e}")
            logger.exception("   Details:")
        
        # Wait for 10 seconds before next sync (for testing)
        logger.info("Next sync in 10 seconds...")
        await asyncio.sleep(10)

# Register startup event
@app.on_event("startup")
async def startup_event():
    """Start the automatic sync task when the application starts."""
    logger.info("=" * 60)
    logger.info("NOTION GOOGLE CALENDAR SYNC API STARTING")
    logger.info("=" * 60)
    logger.info("Application: Notion Database API")
    logger.info("Version: 1.0.0")
    logger.info("Status: Initializing...")
    logger.info("-" * 40)
    logger.info("Note: Error details will be logged to 'error.log'")
    logger.info("This file is recreated each time the application starts")
    logger.info("-" * 40)
    
    # Start the automatic sync task
    asyncio.create_task(auto_sync_task())
    
    logger.info("Application started successfully!")
    logger.info("Automatic sync task scheduled (10-second intervals for testing)")
    logger.info("=" * 60)

# Configuration - using environment variables for security
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

# Scopes required for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Validate required environment variables
if not NOTION_TOKEN:
    raise ValueError("NOTION_TOKEN environment variable is required")
if not DATABASE_ID:
    raise ValueError("DATABASE_ID environment variable is required")

# Notion API headers
headers = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2025-09-03',  # Latest version supporting multiple data sources
    'Content-Type': 'application/json'
}

# Cache for data_source_id to avoid repeated API calls
_data_source_id_cache = None

# File to store mapping between Notion items and Google Calendar events
SYNC_MAPPING_FILE = "sync_mapping.json"

def load_sync_mapping() -> Dict:
    """Load the sync mapping from file."""
    if os.path.exists(SYNC_MAPPING_FILE):
        try:
            with open(SYNC_MAPPING_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sync_mapping(mapping: Dict):
    """Save the sync mapping to file."""
    with open(SYNC_MAPPING_FILE, 'w') as f:
        json.dump(mapping, f, indent=2)

def get_google_calendar_service():
    """Get authenticated Google Calendar service."""
    creds = None
    # Check if token file exists
    if os.path.exists(GOOGLE_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
        except:
            creds = None
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise HTTPException(
                    status_code=500,
                    detail=f"Google credentials file '{GOOGLE_CREDENTIALS_FILE}' not found. Please download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(GOOGLE_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)

# --- Helper functions to safely extract values from Notion properties ---
# Defining these outside the endpoint avoids redefining them on every request.
def get_title(prop):
    if not prop or not isinstance(prop, dict):
        return ""
    try:
        title_list = prop.get("title", [])
        if title_list and len(title_list) > 0:
            return title_list[0].get("plain_text", "")
        return ""
    except (KeyError, IndexError, AttributeError):
        return ""

def get_rich_text(prop):
    if not prop or not isinstance(prop, dict):
        return ""
    try:
        rt_list = prop.get("rich_text", [])
        if rt_list and len(rt_list) > 0:
            return rt_list[0].get("plain_text", "")
        return ""
    except (KeyError, IndexError, AttributeError):
        return ""

def get_date(prop):
    if not prop or not isinstance(prop, dict):
        return None
    try:
        date_obj = prop.get("date")
        if date_obj and isinstance(date_obj, dict):
            return date_obj.get("start")
        return None
    except (KeyError, AttributeError):
        return None

def get_select(prop):
    if not prop or not isinstance(prop, dict):
        return None
    try:
        # Handle both legacy "select" and new "status" property types
        if "status" in prop and isinstance(prop["status"], dict):
            return prop["status"].get("name")
        elif "select" in prop and isinstance(prop["select"], dict):
            return prop["select"].get("name")
        elif "multi_select" in prop and isinstance(prop["multi_select"], list):
            return ", ".join([s.get("name") for s in prop["multi_select"] if "name" in s])
        return None
    except Exception:
        return None


def get_files(prop):
    if not prop or not isinstance(prop, dict):
        return None
    try:
        files_list = prop.get("files", [])
        if files_list and len(files_list) > 0:
            file_obj = files_list[0].get("file", {})
            if file_obj and isinstance(file_obj, dict):
                return file_obj.get("url", "")
        return None
    except (KeyError, IndexError, AttributeError):
        return None

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

@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirects the root path to the API documentation."""
    return RedirectResponse(url="/docs")

def get_data_source_id():
    """
    Get the data source ID from the database.
    For databases with multiple data sources, we use the first one.
    """
    global _data_source_id_cache
    if _data_source_id_cache:
        return _data_source_id_cache
    
    try:
        # First, get the database information to retrieve data sources
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        db_info = response.json()
        
        # Get data sources from the database
        data_sources = db_info.get("data_sources", [])
        if not data_sources:
            raise HTTPException(
                status_code=400,
                detail="No data sources found in the database"
            )
        
        # Use the first data source ID
        _data_source_id_cache = data_sources[0].get("id")
        if not _data_source_id_cache:
            raise HTTPException(
                status_code=400,
                detail="Unable to retrieve data source ID from database"
            )
        
        return _data_source_id_cache
    except requests.exceptions.HTTPError as http_err:
        error_detail = f"Notion API error: {http_err}"
        if hasattr(http_err.response, 'text'):
            try:
                error_body = http_err.response.json()
                error_detail = f"Notion API error: {error_body.get('message', str(http_err))}"
            except:
                error_detail = f"Notion API error: {http_err.response.text if hasattr(http_err.response, 'text') else str(http_err)}"
        raise HTTPException(
            status_code=http_err.response.status_code if hasattr(http_err, 'response') else 500,
            detail=error_detail
        )

@app.get("/get-data", response_model=NotionResponse, tags=["Notion"])
def get_data():
    """
    Fetch all records from the configured Notion database.
    """
    try:
        # Get the data source ID (required for API version 2025-09-03+)
        data_source_id = get_data_source_id()
        
        # Query using the data source ID instead of database ID
        url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
        response = requests.post(url, headers=headers, json={})
        response.raise_for_status()
        data = response.json()

        results = []
        for page in data.get("results", []):
            try:
                props = page.get("properties", {})
                if not props:
                    continue
                    
                item = {
                    "Project_name": get_title(props.get("Project name", {})),
                    "Assign_Date": get_date(props.get("Assign Date", {})),
                    "Attach_file": get_files(props.get("Attach file", {})),
                    "Customer_Name": get_rich_text(props.get("Customer Name", {})),
                    "End_date": get_date(props.get("End date", {})),
                    "Start_date": get_date(props.get("Start date", {})),
                    "Status": get_select(props.get("Status", {})),
                    "Task_Type": get_select(props.get("Task Type", {})),
                    "Tasks_Tracker": get_rich_text(props.get("Tasks Tracker", {})),
                }
                results.append(item)
            except Exception as page_error:
                # Log the error but continue processing other pages
                logger.error(f"Error processing page: {str(page_error)}", exc_info=True)
                continue

        # Sort results by Project_name so items are grouped project-wise
        results.sort(key=lambda x: (x.get("Project_name", "").lower(), x.get("Start_date") or ""))
        
        return {"data": results}

    except requests.exceptions.HTTPError as http_err:
        error_detail = f"Notion API error: {http_err}"
        if hasattr(http_err.response, 'text'):
            try:
                error_body = http_err.response.json()
                error_detail = f"Notion API error: {error_body.get('message', str(http_err))}"
            except:
                error_detail = f"Notion API error: {http_err.response.text if hasattr(http_err.response, 'text') else str(http_err)}"
        raise HTTPException(status_code=http_err.response.status_code if hasattr(http_err, 'response') else 500, detail=error_detail)
    except requests.exceptions.RequestException as req_err:
        raise HTTPException(status_code=503, detail=f"Failed to connect to Notion API: {str(req_err)}")
    except Exception as e:
        logger.error("Internal server error in get_data endpoint", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

def get_notion_data_with_ids():
    """
    Fetch all records from Notion database with page IDs for tracking.
    Returns a dictionary with page_id as key and item data as value.
    """
    try:
        data_source_id = get_data_source_id()
        url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
        response = requests.post(url, headers=headers, json={})
        response.raise_for_status()
        data = response.json()

        notion_items = {}
        for page in data.get("results", []):
            try:
                page_id = page.get("id")
                props = page.get("properties", {})
                if not props or not page_id:
                    continue
                    
                item = {
                    "Project_name": get_title(props.get("Project name", {})),
                    "Assign_Date": get_date(props.get("Assign Date", {})),
                    "Attach_file": get_files(props.get("Attach file", {})),
                    "Customer_Name": get_rich_text(props.get("Customer Name", {})),
                    "End_date": get_date(props.get("End date", {})),
                    "Start_date": get_date(props.get("Start date", {})),
                    "Status": get_select(props.get("Status", {})),
                    "Task_Type": get_select(props.get("Task Type", {})),
                    "Tasks_Tracker": get_rich_text(props.get("Tasks Tracker", {})),
                }
                notion_items[page_id] = item
            except Exception as page_error:
                logger.error(f"Error processing page: {str(page_error)}", exc_info=True)
                continue

        return notion_items
    except Exception as e:
        logger.error(f"Error fetching Notion data: {str(e)}", exc_info=True)
        raise

def parse_notion_date(date_str: str):
    """Parse Notion date string and return datetime object and format type."""
    if not date_str:
        return None, None
    
    # For all-day events, we only care about the date part, not time
    # Check if it's a date-only format (YYYY-MM-DD)
    if 'T' not in date_str:
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            return dt, 'date'  # Always treat as date for all-day events
        except:
            try:
                dt = datetime.fromisoformat(date_str)
                return dt, 'date'  # Always treat as date for all-day events
            except:
                logger.warning(f"Error parsing date '{date_str}': Could not parse")
                return None, None
    else:
        # Even if it contains time, we'll treat it as an all-day event
        # Extract just the date part
        date_part = date_str.split('T')[0]
        try:
            dt = datetime.strptime(date_part, '%Y-%m-%d')
            return dt, 'date'  # Always treat as date for all-day events
        except:
            logger.warning(f"Error parsing datetime '{date_str}': Could not parse")
            return None, None

def create_calendar_event(service, item: Dict, notion_page_id: str) -> Optional[str]:
    """Create a calendar event from Notion item and return event ID."""
    if not item.get("Start_date"):
        logger.info(f"Skipping item '{item.get('Project_name')}' - no start date")
        return None
    
    # Initialize variables for error logging
    start_time = ""
    end_time = ""
    event = {}
    
    try:
        # Parse start date
        start_date_str = item.get("Start_date")
        start_dt, start_format = parse_notion_date(start_date_str or "")
        
        if start_dt is None:
            logger.warning(f"Error parsing start date for '{item.get('Project_name')}': {start_date_str}")
            return None
        
        # For all-day events, we always use 'date' format
        time_format = 'date'
        
        # Parse end date
        end_dt = start_dt  # Default to start date
        if item.get("End_date"):
            end_date_str = item.get("End_date")
            parsed_end_dt, end_format = parse_notion_date(end_date_str or "")
            
            if parsed_end_dt is not None:
                end_dt = parsed_end_dt
            # If parsing fails, we keep end_dt as start_dt (same day event)
        
        # For all-day events, we need to add one day to the end date
        # Google Calendar all-day events end date is exclusive
        end_dt = end_dt + timedelta(days=1)
        
        # Format dates for Google Calendar API (YYYY-MM-DD format for all-day events)
        start_time = start_dt.strftime('%Y-%m-%d')
        end_time = end_dt.strftime('%Y-%m-%d')
        
        # Validate that start_time is not empty
        if not start_time:
            logger.warning(f"Skipping item '{item.get('Project_name')}' - invalid start date format")
            return None
            
        # Validate that end_time is not empty
        if not end_time:
            logger.warning(f"Skipping item '{item.get('Project_name')}' - invalid end date format")
            return None
            
        # Validate that start_time is not after end_time
        try:
            start_date_obj = datetime.strptime(start_time, '%Y-%m-%d')
            end_date_obj = datetime.strptime(end_time, '%Y-%m-%d')
            
            if start_date_obj > end_date_obj:
                logger.warning(f"Skipping item '{item.get('Project_name')}' - start date is after end date")
                return None
        except ValueError:
            logger.warning(f"Skipping item '{item.get('Project_name')}' - invalid date format")
            return None
        
        # Build event description
        description_parts = []
        if item.get("Customer_Name"):
            description_parts.append(f"Customer: {item.get('Customer_Name')}")
        if item.get("Status"):
            description_parts.append(f"Status: {item.get('Status')}")
        if item.get("Task_Type"):
            description_parts.append(f"Task Type: {item.get('Task_Type')}")
        if item.get("Tasks_Tracker"):
            description_parts.append(f"Tasks Tracker: {item.get('Tasks_Tracker')}")
        if item.get("Attach_file"):
            description_parts.append(f"Attachment: {item.get('Attach_file')}")
        
        description = "\n".join(description_parts) if description_parts else ""
        
        event = {
            'summary': item.get("Project_name") or "Untitled Project",
            'description': description,
            'start': {
                time_format: start_time,
            },
            'end': {
                time_format: end_time,
            },
        }
        
        created_event = service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        return created_event.get('id')
    except HttpError as e:
        if e.resp.status == 400:
            logger.error(f"HttpError 400 for item '{item.get('Project_name', 'Unknown')}': {e.reason}")
            logger.error(f"  Start time: {start_time}, End time: {end_time}")
            logger.error(f"  Event data: {event}")
        else:
            logger.error(f"HttpError {e.resp.status} creating calendar event: {e.reason}")
        return None
    except Exception as e:
        logger.error(f"Error creating calendar event: {str(e)}", exc_info=True)
        return None

def update_calendar_event(service, event_id: str, item: Dict):
    """Update an existing calendar event."""
    if not item.get("Start_date"):
        logger.info(f"Skipping update for item '{item.get('Project_name')}' - no start date")
        return
    
    # Initialize variables for error logging
    start_time = ""
    end_time = ""
    event = {}
    
    try:
        # Get existing event
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        
        # Parse dates using the same helper function
        start_date_str = item.get("Start_date")
        start_dt, start_format = parse_notion_date(start_date_str or "")
        
        if start_dt is None:
            logger.warning(f"Error parsing start date for update '{item.get('Project_name')}': {start_date_str}")
            return
        
        # For all-day events, we always use 'date' format
        time_format = 'date'
        
        # Parse end date
        end_dt = start_dt  # Default to start date
        if item.get("End_date"):
            end_date_str = item.get("End_date")
            parsed_end_dt, end_format = parse_notion_date(end_date_str or "")
            
            if parsed_end_dt is not None:
                end_dt = parsed_end_dt
            # If parsing fails, we keep end_dt as start_dt (same day event)
        
        # For all-day events, we need to add one day to the end date
        # Google Calendar all-day events end date is exclusive
        end_dt = end_dt + timedelta(days=1)
        
        # Format dates for Google Calendar API (YYYY-MM-DD format for all-day events)
        start_time = start_dt.strftime('%Y-%m-%d')
        end_time = end_dt.strftime('%Y-%m-%d')
        
        # Validate that start_time is not empty
        if not start_time:
            logger.warning(f"Skipping update for item '{item.get('Project_name')}' - invalid start date format")
            return
            
        # Validate that end_time is not empty
        if not end_time:
            logger.warning(f"Skipping update for item '{item.get('Project_name')}' - invalid end date format")
            return
            
        # Validate that start_time is not after end_time
        try:
            start_date_obj = datetime.strptime(start_time, '%Y-%m-%d')
            end_date_obj = datetime.strptime(end_time, '%Y-%m-%d')
            
            if start_date_obj > end_date_obj:
                logger.warning(f"Skipping update for item '{item.get('Project_name')}' - start date is after end date")
                return None
        except ValueError:
            logger.warning(f"Skipping update for item '{item.get('Project_name')}' - invalid date format")
            return None
        
        # Build description
        description_parts = []
        if item.get("Customer_Name"):
            description_parts.append(f"Customer: {item.get('Customer_Name')}")
        if item.get("Status"):
            description_parts.append(f"Project Status: {item.get('Status')}")
        if item.get("Task_Type"):
            description_parts.append(f"Task Type: {item.get('Task_Type')}")
        if item.get("Tasks_Tracker"):
            description_parts.append(f"Tasks Tracker: {item.get('Tasks_Tracker')}")
        if item.get("Attach_file"):
            description_parts.append(f"Attachment: {item.get('Attach_file')}")
        
        description = "\n".join(description_parts) if description_parts else ""
        
        # Update event
        event['summary'] = item.get("Project_name") or "Untitled Project"
        event['description'] = description
        event['start'] = {time_format: start_time}
        event['end'] = {time_format: end_time}
        
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute()
    except HttpError as e:
        if e.resp.status == 400:
            logger.error(f"HttpError 400 updating item '{item.get('Project_name', 'Unknown')}': {e.reason}")
            logger.error(f"  Start time: {start_time}, End time: {end_time}")
            logger.error(f"  Event data: {event}")
        else:
            logger.error(f"HttpError {e.resp.status} updating calendar event: {e.reason}")
        raise
    except Exception as e:
        logger.error(f"Error updating calendar event: {str(e)}", exc_info=True)
        raise

def delete_calendar_event(service, event_id: str):
    """Delete a calendar event."""
    try:
        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
    except HttpError as e:
        if e.resp.status == 404:
            logger.info(f"Event {event_id} not found, may have been already deleted")
        else:
            logger.error(f"HttpError deleting calendar event {event_id}: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Error deleting calendar event {event_id}: {str(e)}", exc_info=True)
        raise

def delete_all_calendar_events(service):
    """Delete all events from the Google Calendar."""
    try:
        # Get all events from the calendar
        logger.info("Fetching all events from calendar...")
        events_result = service.events().list(calendarId=GOOGLE_CALENDAR_ID, maxResults=2500).execute()
        events = events_result.get('items', [])
        
        logger.info(f"Found {len(events)} events to delete")
        
        # Delete each event
        deleted_count = 0
        for event in events:
            try:
                event_id = event['id']
                service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
                deleted_count += 1
                if deleted_count % 50 == 0:  # Log progress every 50 deletions
                    logger.info(f"Deleted {deleted_count} events so far...")
            except HttpError as e:
                event_id = event.get('id', 'unknown')
                if e.resp.status == 404:
                    # Event already deleted
                    pass
                else:
                    logger.error(f"HttpError deleting event {event_id}: {str(e)}")
            except Exception as e:
                event_id = event.get('id', 'unknown')
                logger.error(f"Error deleting event {event_id}: {str(e)}")
        
        logger.info(f"Successfully deleted {deleted_count} events from calendar")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error fetching or deleting events: {str(e)}", exc_info=True)
        raise

@app.post("/clear-calendar", tags=["Calendar Management"])
def clear_calendar():
    """
    Delete all events from the Google Calendar.
    This will remove all events from the specified calendar.
    """
    try:
        logger.info("Starting calendar clear operation...")
        logger.info("Connecting to Google Calendar API...")
        
        # Get Google Calendar service
        service = get_google_calendar_service()
        logger.info("Google Calendar API connection established")
        
        # Delete all events
        deleted_count = delete_all_calendar_events(service)
        
        # Clear the sync mapping file
        logger.info("Clearing sync mapping file...")
        save_sync_mapping({})
        logger.info("Sync mapping file cleared")
        
        result = {
            "status": "success",
            "deleted": deleted_count,
            "message": f"Successfully deleted {deleted_count} events from calendar"
        }
        
        logger.info(f"Calendar clear operation completed! Deleted {deleted_count} events.")
        return result
        
    except Exception as e:
        logger.error(f"Internal server error during calendar clear: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/sync-calendar", tags=["Calendar Sync"])
def sync_calendar():
    """
    Sync Notion database with Google Calendar.
    Creates new events for new projects, updates existing events, and deletes removed projects.
    """
    try:
        logger.info("Starting calendar synchronization...")
        logger.info("Connecting to Google Calendar API...")
        
        # Get Google Calendar service
        service = get_google_calendar_service()
        logger.info("✓ Google Calendar API connection established")
        
        # Load existing sync mapping
        logger.info("Loading sync mapping...")
        sync_mapping = load_sync_mapping()
        logger.info(f"✓ Loaded {len(sync_mapping)} existing mappings")
        
        # Get current Notion data with page IDs
        logger.info("Fetching data from Notion...")
        notion_items = get_notion_data_with_ids()
        logger.info(f"Retrieved {len(notion_items)} items from Notion")
        
        # Track stats
        created_count = 0
        updated_count = 0
        deleted_count = 0
        skipped_count = 0
        
        logger.info("Processing items...")
        # Process each Notion item
        for page_id, item in notion_items.items():
            # Skip items without start date
            if not item.get("Start_date"):
                skipped_count += 1
                continue
            
            # Check if this page was already synced
            if page_id in sync_mapping:
                # Check if item has changed (compare key fields)
                existing_item = sync_mapping[page_id]
                event_id = existing_item.get("event_id")
                
                # Check if significant fields changed (using a stable hash)
                hash_fields = (
                    str(item.get("Project_name", "")),
                    str(item.get("Start_date", "")),
                    str(item.get("End_date", "")),
                    str(item.get("Customer_Name", "")),
                    str(item.get("Status", "")),
                    str(item.get("Task_Type", "")),
                    str(item.get("Tasks_Tracker", ""))
                )
                item_hash = hash(hash_fields)
                
                if existing_item.get("hash") != item_hash:
                    # Item changed, update calendar event
                    try:
                        update_calendar_event(service, event_id, item)
                        existing_item["hash"] = item_hash
                        existing_item.update(item)
                        updated_count += 1
                    except Exception as e:
                        logger.error(f"  Error updating event for page {page_id}: {str(e)}")
                else:
                    # No changes
                    existing_item.update(item)
            else:
                # New item, create calendar event
                try:
                    event_id = create_calendar_event(service, item, page_id)
                    if event_id:
                        hash_fields = (
                            str(item.get("Project_name", "")),
                            str(item.get("Start_date", "")),
                            str(item.get("End_date", "")),
                            str(item.get("Customer_Name", "")),
                            str(item.get("Status", "")),
                            str(item.get("Task_Type", "")),
                            str(item.get("Tasks_Tracker", ""))
                        )
                        sync_mapping[page_id] = {
                            "event_id": event_id,
                            "hash": hash(hash_fields),
                            **item
                        }
                        created_count += 1
                    else:
                        skipped_count += 1
                except Exception as e:
                    logger.error(f"  Error creating event for page {page_id}: {str(e)}")
        
        # Find and delete events for items that no longer exist in Notion
        logger.info("Checking for deleted items...")
        notion_page_ids = set(notion_items.keys())
        sync_page_ids = set(sync_mapping.keys())
        
        for page_id in sync_page_ids - notion_page_ids:
            # Item was deleted from Notion
            try:
                event_id = sync_mapping[page_id].get("event_id")
                if event_id:
                    delete_calendar_event(service, event_id)
                    deleted_count += 1
                del sync_mapping[page_id]
            except Exception as e:
                logger.error(f"  Error deleting event for removed page {page_id}: {str(e)}")
        
        # Save updated sync mapping
        logger.info("Saving sync mapping...")
        save_sync_mapping(sync_mapping)
        logger.info("Sync mapping saved")
        
        result = {
            "status": "success",
            "created": created_count,
            "updated": updated_count,
            "deleted": deleted_count,
            "skipped": skipped_count,
            "total_notion_items": len(notion_items),
            "total_synced": len(sync_mapping)
        }
        
        logger.info("Calendar synchronization completed successfully!")
        return result
        
    except requests.exceptions.HTTPError as http_err:
        error_detail = f"Notion API error: {http_err}"
        if hasattr(http_err.response, 'text'):
            try:
                error_body = http_err.response.json()
                error_detail = f"Notion API error: {error_body.get('message', str(http_err))}"
            except:
                error_detail = f"Notion API error: {http_err.response.text if hasattr(http_err.response, 'text') else str(http_err)}"
        logger.error(f"Notion API error: {error_detail}")
        raise HTTPException(status_code=http_err.response.status_code if hasattr(http_err, 'response') else 500, detail=error_detail)
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Failed to connect to Notion API: {str(req_err)}")
        raise HTTPException(status_code=503, detail=f"Failed to connect to Notion API: {str(req_err)}")
    except Exception as e:
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.get("/auto-sync/start", tags=["Auto Sync"])
def start_auto_sync():
    """Start automatic sync"""
    global auto_sync_enabled
    auto_sync_enabled = True
    return {"status": "success", "message": "Automatic sync started"}

@app.get("/auto-sync/stop", tags=["Auto Sync"])
def stop_auto_sync():
    """Stop automatic sync"""
    global auto_sync_enabled
    auto_sync_enabled = False
    return {"status": "success", "message": "Automatic sync stopped"}

@app.get("/auto-sync/status", tags=["Auto Sync"])
def auto_sync_status():
    """Get automatic sync status"""
    global auto_sync_enabled
    return {"status": "success", "auto_sync_enabled": auto_sync_enabled}

@app.get("/logs/latest", tags=["Logs"])
def get_latest_logs():
    """Get the latest log entries"""
    try:
        with open("sync.log", "r") as f:
            lines = f.readlines()
            # Return the last 20 lines
            return {"status": "success", "logs": lines[-20:] if len(lines) > 20 else lines}
    except FileNotFoundError:
        return {"status": "error", "message": "Log file not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "notion-api"}

# Only used if running directly (e.g., `python main.py`)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
















