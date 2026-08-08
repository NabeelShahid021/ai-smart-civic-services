"""
SQLAlchemy ORM models and Pydantic schemas for AI Smart Civic Services.
"""
from datetime import datetime
import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

VALID_CATEGORIES = ["Road", "Water/Drainage", "Waste", "Electricity", "Safety", "Other"]
VALID_PRIORITIES = ["Low", "Medium", "High", "Critical"]
VALID_STATUSES = ["Open", "Assigned", "In Progress", "Resolved"]


class Complaint(Base):
    """SQLAlchemy model for citizen complaints."""
    __tablename__ = "complaints"

    complaint_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    description = Column(Text, nullable=False)
    category = Column(String(50), nullable=False, default="Other")
    priority = Column(String(20), nullable=False, default="Medium")
    location = Column(String(255), nullable=True)
    date_submitted = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(30), default="Open", nullable=False)
    assigned_department = Column(String(100), nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_keywords = Column(Text, nullable=True)  # Stored as JSON string
    duplicate_of = Column(Integer, ForeignKey("complaints.complaint_id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    @property
    def keywords_list(self) -> List[str]:
        """Parse JSON keywords into a Python list."""
        if not self.ai_keywords:
            return []
        try:
            parsed = json.loads(self.ai_keywords)
            if isinstance(parsed, list):
                return [str(k) for k in parsed]
            return [str(parsed)]
        except Exception:
            return []

    @keywords_list.setter
    def keywords_list(self, words: List[str]):
        """Serialize Python list into JSON string."""
        if isinstance(words, list):
            self.ai_keywords = json.dumps(words, ensure_ascii=False)
        elif words is None:
            self.ai_keywords = "[]"
        else:
            self.ai_keywords = json.dumps([str(words)], ensure_ascii=False)


# ==========================================
# Pydantic Request / Response Schemas
# ==========================================

class ComplaintCreate(BaseModel):
    description: str = Field(..., min_length=3, description="Citizen complaint in English, Urdu, or Roman Urdu")
    location: Optional[str] = Field(None, description="Optional street, block, neighborhood, or area")

    @field_validator("description")
    def description_not_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Complaint description cannot be empty or whitespace only.")
        return clean


class ComplaintUpdate(BaseModel):
    status: Optional[str] = Field(None, description="New status: Open, Assigned, In Progress, Resolved")
    assigned_department: Optional[str] = Field(None, description="Department name")

    @field_validator("status")
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            # Normalize casing
            matched = next((s for s in VALID_STATUSES if s.lower() == clean.lower()), None)
            if not matched:
                raise ValueError(f"Invalid status '{v}'. Allowed: {', '.join(VALID_STATUSES)}")
            return matched
        return v


class ComplaintResponse(BaseModel):
    complaint_id: int
    description: str
    category: str
    priority: str
    location: Optional[str] = None
    date_submitted: datetime
    status: str
    assigned_department: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_keywords: List[str] = Field(default_factory=list)
    duplicate_of: Optional[int] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_model(cls, obj: Complaint) -> "ComplaintResponse":
        return cls(
            complaint_id=obj.complaint_id,
            description=obj.description,
            category=obj.category,
            priority=obj.priority,
            location=obj.location,
            date_submitted=obj.date_submitted,
            status=obj.status,
            assigned_department=obj.assigned_department,
            ai_summary=obj.ai_summary,
            ai_keywords=obj.keywords_list,
            duplicate_of=obj.duplicate_of,
            resolved_at=obj.resolved_at,
        )


class StatsResponse(BaseModel):
    total_complaints: int
    by_category: Dict[str, int]
    by_priority: Dict[str, int]
    by_status: Dict[str, int]
    avg_resolution_time_hours: Optional[float] = None
    duplicate_count: int


class AskQuestionRequest(BaseModel):
    question: str = Field(..., min_length=2, description="Natural language question about civic complaints")

    @field_validator("question")
    def question_not_empty(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Question cannot be empty or whitespace only.")
        return clean


class AskQuestionResponse(BaseModel):
    question: str
    answer: str
