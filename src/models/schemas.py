from typing import Any, Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Generic envelope
# ---------------------------------------------------------------------------

class APIResponse(BaseModel):
    data: Any = None
    error: Optional[dict] = None
