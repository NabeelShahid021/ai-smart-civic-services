"""
Main FastAPI Application for AI Smart Civic Services.
Defines all REST API endpoints, CORS middleware, dependency injection, and exception handlers.
"""
from datetime import datetime
import logging
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables early
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Query, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app.database import db_manager, get_db
from app.models import (
    ComplaintCreate,
    ComplaintUpdate,
    ComplaintResponse,
    StatsResponse,
    AskQuestionRequest,
    AskQuestionResponse,
)
from app.ai_service import AIService
from app.complaint_manager import ComplaintManager
from app.stats_service import StatsService

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("civic_api")

# Initialize core services
ai_service = AIService()
complaint_manager = ComplaintManager(ai_service=ai_service)
stats_service = StatsService()

# Create FastAPI application
app = FastAPI(
    title="AI Smart Civic Services API",
    description="Multilingual AI-powered civic complaint triage, duplicate detection, and analytics backend for Pakistani cities.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for all origins (*)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Initialize database tables on application startup."""
    logger.info("Initializing SQLite database tables...")
    db_manager.init_db()
    logger.info("Database initialized successfully.")


# ==========================================
# Custom Exception Handlers
# ==========================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return clean 422 error details when request payload is invalid."""
    errors = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err.get("loc", []))
        msg = err.get("msg", "Invalid input")
        errors.append(f"{field}: {msg}")
    logger.warning(f"Validation error on {request.url.path}: {errors}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": errors},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle standard HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Safe 500 error handler that logs stack traces internally but never leaks them to clients."""
    logger.error(f"Unhandled server error at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred while processing your request."},
    )


# ==========================================
# API Endpoints
# ==========================================

@app.get("/", tags=["Health"])
def root():
    """Root health check and service status."""
    return {
        "service": "AI Smart Civic Services API",
        "version": "1.0.0",
        "status": "operational",
        "llm_provider": "Groq" if ai_service.groq_api_key else ("Gemini" if ai_service.gemini_api_key else "Rule-based offline mode"),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post(
    "/submit-complaint",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Complaints"],
    summary="Submit a citizen complaint for AI triage and duplicate detection",
)
def submit_complaint(
    payload: ComplaintCreate,
    db: Session = Depends(get_db),
):
    """
    Submits a civic complaint in English, Urdu, or Roman Urdu.
    Performs AI classification, priority prediction, department assignment,
    and runs TF-IDF duplicate detection with priority auto-escalation.
    """
    try:
        created = complaint_manager.create_complaint(payload, db)
        return ComplaintResponse.from_orm_model(created)
    except Exception as e:
        logger.error(f"Error submitting complaint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save civic complaint. Please try again.",
        )


@app.get(
    "/complaints",
    response_model=List[ComplaintResponse],
    tags=["Complaints"],
    summary="List and filter complaints, ordered newest first",
)
def get_complaints(
    category: Optional[str] = Query(None, description="Filter by category (e.g. Road, Water/Drainage)"),
    priority: Optional[str] = Query(None, description="Filter by priority (Low, Medium, High, Critical)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (Open, Assigned, In Progress, Resolved)"),
    department: Optional[str] = Query(None, description="Filter by assigned department"),
    location: Optional[str] = Query(None, description="Filter by location keyword"),
    date_from: Optional[datetime] = Query(None, description="Filter complaints submitted on or after this ISO datetime"),
    date_to: Optional[datetime] = Query(None, description="Filter complaints submitted on or before this ISO datetime"),
    db: Session = Depends(get_db),
):
    """Returns a filtered list of citizen complaints, ordered newest first."""
    try:
        complaints = complaint_manager.list_complaints(
            db=db,
            category=category,
            priority=priority,
            status=status_filter,
            department=department,
            location=location,
            date_from=date_from,
            date_to=date_to,
        )
        return [ComplaintResponse.from_orm_model(c) for c in complaints]
    except Exception as e:
        logger.error(f"Error listing complaints: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch complaints list.",
        )


@app.get(
    "/complaints/{complaint_id}",
    response_model=ComplaintResponse,
    tags=["Complaints"],
    summary="Get full details for a single complaint",
)
def get_complaint(
    complaint_id: int,
    db: Session = Depends(get_db),
):
    """Returns a single complaint by its ID, including AI reasoning metadata and duplicate linkage."""
    complaint = complaint_manager.get_complaint_by_id(complaint_id, db)
    if not complaint:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Complaint with ID {complaint_id} not found.",
        )
    return ComplaintResponse.from_orm_model(complaint)


@app.patch(
    "/complaints/{complaint_id}",
    response_model=ComplaintResponse,
    tags=["Complaints"],
    summary="Update complaint status or assigned department",
)
def update_complaint(
    complaint_id: int,
    payload: ComplaintUpdate,
    db: Session = Depends(get_db),
):
    """
    Updates the status or assigned department of an existing complaint.
    When status is marked as 'Resolved', sets resolved_at to the current timestamp.
    """
    updated = complaint_manager.update_complaint(complaint_id, payload, db)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Complaint with ID {complaint_id} not found.",
        )
    return ComplaintResponse.from_orm_model(updated)


@app.get(
    "/stats",
    response_model=StatsResponse,
    tags=["Analytics"],
    summary="Get aggregated statistics and resolution analytics",
)
def get_stats(
    db: Session = Depends(get_db),
):
    """
    Returns aggregated metrics:
    - total_complaints
    - by_category
    - by_priority
    - by_status
    - avg_resolution_time_hours (across resolved complaints, or null)
    - duplicate_count
    """
    try:
        data = stats_service.get_stats(db)
        return StatsResponse(**data)
    except Exception as e:
        logger.error(f"Error computing statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to compute civic statistics.",
        )


@app.post(
    "/ask",
    response_model=AskQuestionResponse,
    tags=["AI Assistant"],
    summary="Ask natural language questions about complaint data",
)
def ask_question(
    payload: AskQuestionRequest,
    db: Session = Depends(get_db),
):
    """
    Takes a natural-language query from an operator or citizen (e.g. 'how many High priority water complaints are open?'),
    builds a summarized context from live DB records, and returns an LLM-synthesized plain-text answer.
    """
    try:
        context = stats_service.get_context_summary(db)
        answer_text = ai_service.answer_question(question=payload.question, context=context)
        return AskQuestionResponse(
            question=payload.question,
            answer=answer_text,
        )
    except Exception as e:
        logger.error(f"Error answering question: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate answer for your query.",
        )
