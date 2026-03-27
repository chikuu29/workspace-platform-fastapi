from pydantic import BaseModel
from typing import Dict, Any, List

class UploadFileResponse(BaseModel):
    filename: str
    originalName: str
    size: int
    mimeType: str
    absolutePath: str
    accessObjectPath: str
    accessUrl: str
