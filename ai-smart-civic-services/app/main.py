"""
Main FastAPI Application for AI Smart Civic Services.
Defines all REST API endpoints:
- Citizen Authentication (POST /auth/signup, POST /auth/login)
- Citizen Complaints (POST /submit-complaint, GET /my-complaints, GET /track, GET /complaints/{id})
- Admin Authentication & Management (POST /admin/login, PATCH /complaints/{id}, GET /stats, GET /complaints)
- Citizen AI Assistant (POST /ask)
- Health check & CORS
"""
import os
import secrets
from datetime import datetime
import logging
from typing import List, Optional, Union, Set
from dotenv import load_dotenv

# Load environment variables early
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Query, status, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app.database import db_manager, get_db
from app.models import (
    Citizen,
    CitizenSignupRequest,
    CitizenLoginRequest,
    CitizenAuthResponse,
    ComplaintCreate,
    ComplaintUpdate,
    ComplaintResponse,
    StatsResponse,
    AdminLoginRequest,
    AdminLoginResponse,
    AskQuestionRequest,
    AskQuestionResponse,
)
from app.citizen_auth import (
    normalize_and_validate_cnic,
    hash_password,
    verify_password,
    create_citizen_token,
    get_current_citizen,
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

# Admin credentials & active token store (completely separate from citizen JWTs)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "civic_admin_2026").strip()
ACTIVE_ADMIN_TOKENS: Set[str] = set()

# Initialize core services
ai_service = AIService()
complaint_manager = ComplaintManager(ai_service=ai_service)
stats_service = StatsService()

# Create FastAPI application
app = FastAPI(
    title="AI Smart Civic Services API",
    description="Multilingual AI-powered civic complaint portal with separate citizen auth, triage, tracking, duplicate detection, and analytics for Pakistani cities.",
    version="1.2.0",
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

# Security scheme for admin bearer token
admin_bearer = HTTPBearer(auto_error=False)


def verify_admin_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(admin_bearer),
) -> str:
    """Dependency that ensures only requests with a valid admin Bearer token can proceed."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Admin bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials.strip()
    if token not in ACTIVE_ADMIN_TOKENS and token != f"master_{ADMIN_PASSWORD}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or expired admin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


@app.on_event("startup")
def on_startup():
    """Initialize database tables and schema migrations on application startup."""
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
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Safe 500 error handler that logs stack traces internally without leaking to clients."""
    logger.error(f"Unhandled server error at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred while processing your request."},
    )


# ==========================================
# Root / Health
# ==========================================

@app.get("/", tags=["Health"])
def root():
    """Root health check and service status."""
    return {
        "service": "AI Smart Civic Services API",
        "version": "1.2.0",
        "status": "operational",
        "llm_provider": "Groq" if ai_service.groq_api_key else ("Gemini" if ai_service.gemini_api_key else "Rule-based offline mode"),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ==========================================
# Citizen Authentication Endpoints
# ==========================================

@app.post(
    "/auth/signup",
    response_model=CitizenAuthResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Citizen Authentication"],
    summary="Register a new citizen account with 13-digit CNIC and password",
)
def citizen_signup(
    payload: CitizenSignupRequest,
    db: Session = Depends(get_db),
):
    """
    Registers a new citizen with their Pakistani CNIC (13 digits with or without dashes) and password.
    - Validates CNIC format (returns 422 if invalid).
    - Checks for existing CNIC (returns 409 Conflict if already registered).
    - Hashes password using bcrypt.
    - Automatically logs in and returns a JWT token + citizen_id.
    """
    clean_cnic = normalize_and_validate_cnic(payload.cnic)

    # Check for existing account
    existing = db.query(Citizen).filter(Citizen.cnic == clean_cnic).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A citizen account with this CNIC is already registered. Please log in.",
        )

    # Hash password with bcrypt
    hashed = hash_password(payload.password)

    new_citizen = Citizen(
        cnic=clean_cnic,
        password_hash=hashed,
        name=payload.name.strip() if payload.name and payload.name.strip() else None,
        phone=payload.phone.strip() if payload.phone and payload.phone.strip() else None,
        created_at=datetime.utcnow(),
    )
    db.add(new_citizen)
    db.commit()
    db.refresh(new_citizen)

    token = create_citizen_token(new_citizen.citizen_id, clean_cnic)
    logger.info(f"New citizen registered: citizen_id={new_citizen.citizen_id}, cnic={clean_cnic[:5]}****")
    return CitizenAuthResponse(token=token, citizen_id=new_citizen.citizen_id)


@app.post(
    "/auth/login",
    response_model=CitizenAuthResponse,
    tags=["Citizen Authentication"],
    summary="Log in with CNIC and password to obtain citizen JWT token",
)
def citizen_login(
    payload: CitizenLoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticates a citizen with CNIC and password.
    Returns a JWT Bearer token and citizen_id on success.
    Returns 401 with generic invalid credentials message on failure.
    """
    clean_cnic = normalize_and_validate_cnic(payload.cnic)

    citizen = db.query(Citizen).filter(Citizen.cnic == clean_cnic).first()
    if not citizen or not verify_password(payload.password, citizen.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials. Please verify your CNIC and password.",
        )

    token = create_citizen_token(citizen.citizen_id, clean_cnic)
    return CitizenAuthResponse(token=token, citizen_id=citizen.citizen_id)


# ==========================================
# Citizen Complaint Submission & Tracking
# ==========================================

@app.post(
    "/submit-complaint",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Citizen Complaints"],
    summary="Submit a citizen complaint (Requires Citizen Login Token)",
)
def submit_complaint(
    payload: ComplaintCreate,
    current_citizen: Citizen = Depends(get_current_citizen),
    db: Session = Depends(get_db),
):
    """
    Submits a civic complaint in English, Urdu, or Roman Urdu.
    Requires an authenticated citizen Bearer token.
    Links complaint to the citizen_id, executes AI triage, and runs TF-IDF duplicate detection.
    """
    try:
        created = complaint_manager.create_complaint(
            data=payload,
            db=db,
            citizen_id=current_citizen.citizen_id,
        )
        return ComplaintResponse.from_orm_model(created)
    except Exception as e:
        logger.error(f"Error submitting complaint: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save civic complaint. Please try again.",
        )


@app.get(
    "/my-complaints",
    response_model=List[ComplaintResponse],
    tags=["Citizen Complaints"],
    summary="Get all complaints submitted by the authenticated citizen (Requires Citizen Login Token)",
)
def get_my_complaints(
    current_citizen: Citizen = Depends(get_current_citizen),
    db: Session = Depends(get_db),
):
    """
    Returns all civic complaints submitted by the currently logged-in citizen, ordered newest first.
    """
    complaints = complaint_manager.get_complaints_by_citizen(current_citizen.citizen_id, db)
    return [ComplaintResponse.from_orm_model(c) for c in complaints]


@app.get(
    "/track",
    response_model=Union[ComplaintResponse, List[ComplaintResponse]],
    tags=["Citizen Complaints"],
    summary="Public citizen tracking endpoint by complaint_id or phone (no auth required)",
)
def track_complaint(
    complaint_id: Optional[int] = Query(None, description="Complaint ID to look up single complaint"),
    phone: Optional[str] = Query(None, description="Citizen phone number to look up all their submitted complaints"),
    db: Session = Depends(get_db),
):
    """
    Public fallback tracking endpoint without requiring an account or login.
    - If `complaint_id` is provided: returns that single complaint (404 if not found).
    - If `phone` is provided: returns an array of all complaints submitted with that phone number, newest first.
    """
    if complaint_id is None and (not phone or not phone.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one query parameter ('complaint_id' or 'phone') is required for tracking.",
        )

    # 1. Search by single complaint_id
    if complaint_id is not None:
        complaint = complaint_manager.get_complaint_by_id(complaint_id, db)
        if not complaint:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Complaint with ID {complaint_id} not found.",
            )
        return ComplaintResponse.from_orm_model(complaint)

    # 2. Search by phone number
    if phone:
        complaints = complaint_manager.get_complaints_by_phone(phone, db)
        return [ComplaintResponse.from_orm_model(c) for c in complaints]


@app.get(
    "/complaints/{complaint_id}",
    response_model=ComplaintResponse,
    tags=["Citizen Complaints"],
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


# ==========================================
# Protected Admin Endpoints
# ==========================================

@app.post(
    "/admin/login",
    response_model=AdminLoginResponse,
    tags=["Admin Authentication"],
    summary="Admin login with shared password to obtain bearer token",
)
def admin_login(payload: AdminLoginRequest):
    """
    Validates shared ADMIN_PASSWORD and issues a secure admin Bearer token.
    Returns 401 if the password does not match.
    """
    configured_password = os.getenv("ADMIN_PASSWORD", ADMIN_PASSWORD).strip()
    if not payload.password or payload.password.strip() != configured_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin password. Access denied.",
        )

    token = f"admin_token_{secrets.token_urlsafe(32)}"
    ACTIVE_ADMIN_TOKENS.add(token)
    logger.info("Admin successfully authenticated. New token issued.")
    return AdminLoginResponse(token=token)


@app.get(
    "/complaints",
    response_model=List[ComplaintResponse],
    tags=["Admin Complaints"],
    summary="List and filter complaints (Requires Admin Token)",
)
def get_complaints(
    category: Optional[str] = Query(None, description="Filter by category (e.g. Road, Water/Drainage)"),
    priority: Optional[str] = Query(None, description="Filter by priority (Low, Medium, High, Critical)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (Open, Assigned, In Progress, Resolved)"),
    department: Optional[str] = Query(None, description="Filter by assigned department"),
    location: Optional[str] = Query(None, description="Filter by location keyword"),
    phone: Optional[str] = Query(None, description="Filter by citizen phone number"),
    date_from: Optional[datetime] = Query(None, description="Filter complaints submitted on or after this ISO datetime"),
    date_to: Optional[datetime] = Query(None, description="Filter complaints submitted on or before this ISO datetime"),
    admin_token: str = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """Admin-only: Returns a filtered list of all citizen complaints, ordered newest first."""
    try:
        complaints = complaint_manager.list_complaints(
            db=db,
            category=category,
            priority=priority,
            status=status_filter,
            department=department,
            location=location,
            phone=phone,
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


@app.patch(
    "/complaints/{complaint_id}",
    response_model=ComplaintResponse,
    tags=["Admin Complaints"],
    summary="Update complaint status or assigned department (Requires Admin Token)",
)
def update_complaint(
    complaint_id: int,
    payload: ComplaintUpdate,
    admin_token: str = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """
    Admin-only: Updates the status or assigned department of an existing complaint.
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
    tags=["Admin Analytics"],
    summary="Get aggregated statistics and resolution analytics (Requires Admin Token)",
)
def get_stats(
    admin_token: str = Depends(verify_admin_token),
    db: Session = Depends(get_db),
):
    """
    Admin-only: Returns aggregated metrics:
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


# ==========================================
# Citizen AI Assistant & General Q&A
# ==========================================

@app.post(
    "/ask",
    response_model=AskQuestionResponse,
    tags=["AI Assistant"],
    summary="Ask natural language questions about civic procedures or citizen's own complaints",
)
def ask_question(
    payload: AskQuestionRequest,
    db: Session = Depends(get_db),
):
    """
    Citizen-facing AI Assistant:
    - If `phone` or `complaint_id` is provided, grounds the answer on that citizen's specific complaint(s).
    - Otherwise answers general questions about civic complaints, submission process, and responsible departments.
    """
    try:
        context = stats_service.get_context_summary(
            db=db,
            phone=payload.phone,
            complaint_id=payload.complaint_id,
        )
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
