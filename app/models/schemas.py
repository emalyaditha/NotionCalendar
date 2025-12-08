from typing import List, Optional
from pydantic import BaseModel

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
