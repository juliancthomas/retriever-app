# Pydantic schemas for upload responses
from datetime import datetime
from pydantic import BaseModel

class Document(BaseModel):
    id: int
    filename: str
    upload_date: datetime