import os
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.core.logging import logger

# Scopes required for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

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
    if os.path.exists(settings.GOOGLE_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(settings.GOOGLE_TOKEN_FILE, SCOPES)
        except:
            creds = None
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        else:
            if not os.path.exists(settings.GOOGLE_CREDENTIALS_FILE):
                raise HTTPException(
                    status_code=500,
                    detail=f"Google credentials file '{settings.GOOGLE_CREDENTIALS_FILE}' not found. Please download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(settings.GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        with open(settings.GOOGLE_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)

def parse_notion_date(date_str: str) -> Tuple[Optional[datetime], Optional[str]]:
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

def format_status_text(status: str) -> str:
    """Format status text consistently for calendar event descriptions."""
    return f"Status: {status}"

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
        # Add Notion page ID for identification
        description_parts.append(f"Notion ID: {notion_page_id}")
        if item.get("Customer_Name"):
            description_parts.append(f"Customer: {item.get('Customer_Name')}")
        status = item.get("Status")
        if status:
            description_parts.append(format_status_text(status))
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
        
        created_event = service.events().insert(calendarId=settings.calendar_id, body=event).execute()
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

def update_calendar_event(service, event_id: str, item: Dict, notion_page_id: str):
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
        event = service.events().get(calendarId=settings.calendar_id, eventId=event_id).execute()
        
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
        # Preserve or add Notion page ID for identification
        description_parts.append(f"Notion ID: {notion_page_id}")
        if item.get("Customer_Name"):
            description_parts.append(f"Customer: {item.get('Customer_Name')}")
        status = item.get("Status")
        if status:
            description_parts.append(format_status_text(status))
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
        
        service.events().update(calendarId=settings.calendar_id, eventId=event_id, body=event).execute()
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
        service.events().delete(calendarId=settings.calendar_id, eventId=event_id).execute()
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
        events_result = service.events().list(calendarId=settings.calendar_id, maxResults=2500).execute()
        events = events_result.get('items', [])
        
        logger.info(f"Found {len(events)} events to delete")
        
        # Delete each event
        deleted_count = 0
        for event in events:
            try:
                event_id = event['id']
                service.events().delete(calendarId=settings.calendar_id, eventId=event_id).execute()
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
