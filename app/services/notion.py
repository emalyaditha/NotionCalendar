import requests
from fastapi import HTTPException
from typing import Dict, List, Optional
from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import NotionItem

# Notion API headers
headers = {
    'Authorization': f'Bearer {settings.NOTION_TOKEN}',
    'Notion-Version': '2025-09-03',  # Latest version supporting multiple data sources
    'Content-Type': 'application/json'
}

# Cache for data_source_id to avoid repeated API calls
_data_source_id_cache = None

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
        url = f"https://api.notion.com/v1/databases/{settings.DATABASE_ID}"
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

def get_data() -> List[Dict]:
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
        
        return results

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

def get_notion_data_with_ids() -> Dict[str, Dict]:
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
