# AI Smart Civic Services - Backend API (v1.1.0)

Production-grade, fully working FastAPI backend for **AI Smart Civic Services**, an intelligent civic complaint triage, tracking, and analytics system designed for Pakistani cities.

Live deployed service: `https://ai-smart-civic-services-sd5w.onrender.com`

---

## What This Backend Does
1. **Multilingual AI Triage**: Categorizes complaints submitted in **English**, **Urdu (اردو)**, or **Roman Urdu** (`Road`, `Water/Drainage`, `Waste`, `Electricity`, `Safety`, `Other`), predicts priority (`Low`, `Medium`, `High`, `Critical`), generates concise summaries, explainability keywords, and assigns responsible departments (e.g. WASA, TEPA, LESCO/K-Electric, Waste Management).
2. **Citizen Tracking (`GET /track`)**: Unauthenticated endpoint allowing citizens to track their complaint by `complaint_id` or view all their submitted complaints by `phone`.
3. **Optional Citizen Metadata**: Citizen `phone`, GPS coordinates (`latitude`, `longitude`), and external `image_url` for photographic evidence.
4. **Duplicate Detection & Auto-Escalation**: Powered by **scikit-learn TF-IDF & Cosine Similarity**. Automatically links duplicate complaints and escalates the original complaint priority to expedite resolution.
5. **Lightweight Admin Authentication**:
   - `ADMIN_PASSWORD` environment variable.
   - `POST /admin/login` returns a secure Bearer token.
   - Protects `PATCH /complaints/{complaint_id}`, `GET /stats`, and `GET /complaints`.
6. **Citizen AI Assistant (`POST /ask`)**: Answers questions with grounding on citizen-specific complaints (`phone` or `complaint_id`) or general municipal workflows.
7. **CORS Enabled (`*`)**: Built to connect with separate frontend clients on any domain.

---

## Project Structure (OOP Architecture)
```
ai-smart-civic-services/
├── app/
│   ├── __init__.py           # Application package
│   ├── main.py               # FastAPI app, routes, auth middleware, CORS (*), exception handlers
│   ├── database.py           # DatabaseManager class (SQLite connection, schema migration, session handling)
│   ├── models.py             # SQLAlchemy ORM models + Pydantic schemas (with phone, lat, lng, image_url, auth)
│   ├── ai_service.py         # AIService class (Groq / Gemini fallback, parsing, retries, intelligent triage)
│   ├── complaint_manager.py  # ComplaintManager class (CRUD, phone queries, TF-IDF duplicate detection & escalation)
│   └── stats_service.py      # StatsService class (aggregation & citizen context summarization)
├── requirements.txt          # Pinned production dependencies
├── .env.example              # Environment variables template
├── .env                      # Local environment configuration
├── render.yaml               # Zero-configuration Render Web Service specification
├── run.py                    # Convenience local server runner
├── test_system.py            # Comprehensive automated test suite
└── README.md                 # Complete documentation & deployment guide
```

---

## API Endpoints Reference

### 1. Citizen Endpoints (Public — No Login Required)

#### `POST /submit-complaint`
Submit a new complaint with optional phone, GPS coordinates, and image URL.

**Request Body:**
```json
{
  "description": "Massive pothole and broken road on Main Boulevard Gulberg causing severe traffic jams.",
  "location": "Main Boulevard, Gulberg, Lahore",
  "phone": "03001234567",
  "latitude": 31.5204,
  "longitude": 74.3587,
  "image_url": "https://civic-cdn.example.com/photos/road_pothole_gulberg.jpg"
}
```

**Response (201 Created):**
```json
{
  "complaint_id": 1,
  "description": "Massive pothole and broken road on Main Boulevard Gulberg causing severe traffic jams.",
  "category": "Road",
  "priority": "High",
  "location": "Main Boulevard, Gulberg, Lahore",
  "phone": "03001234567",
  "latitude": 31.5204,
  "longitude": 74.3587,
  "image_url": "https://civic-cdn.example.com/photos/road_pothole_gulberg.jpg",
  "date_submitted": "2026-08-08T19:38:28.925008",
  "status": "Open",
  "assigned_department": "Roads Authority / TEPA",
  "ai_summary": "Road maintenance issue reported: Massive pothole and broken road on Main Boulevard Gulberg causing severe traffic jams.",
  "ai_keywords": ["pothole", "road damage", "sadak"],
  "duplicate_of": null,
  "resolved_at": null
}
```

---

#### `GET /track`
Citizen tracking endpoint by either `complaint_id` or `phone`.

- **By Complaint ID**: `GET /track?complaint_id=1`
  Returns the single complaint object (`ComplaintResponse`), or 404 if not found.
- **By Phone Number**: `GET /track?phone=03001234567`
  Returns an array of all complaints submitted by that phone number (`List[ComplaintResponse]`), ordered newest first.

---

#### `GET /complaints/{complaint_id}`
Public lookup for a single complaint's details and AI triage output.

---

#### `POST /ask`
Citizen and operator AI Assistant.

**Request Body:**
```json
{
  "question": "What is the status of my road repair complaint?",
  "complaint_id": 1
}
```
*(Or provide `"phone": "03001234567"` to ground on all user complaints, or omit both for general municipal inquiries).*

**Response (200 OK):**
```json
{
  "question": "What is the status of my road repair complaint?",
  "answer": "Your complaint #1 regarding Road maintenance on Main Boulevard, Gulberg is currently Open and assigned to Roads Authority / TEPA."
}
```

---

### 2. Admin Endpoints (Protected — Requires Bearer Token)

#### `POST /admin/login`
Authenticate with the shared `ADMIN_PASSWORD`.

**Request Body:**
```json
{
  "password": "your_admin_password"
}
```

**Response (200 OK):**
```json
{
  "token": "admin_token_6pkxz0lt..."
}
```
*(If password does not match, returns 401 Unauthorized).*

---

#### `PATCH /complaints/{complaint_id}`
**Headers:** `Authorization: Bearer <admin_token>`
Update complaint status or assigned department. If status is set to `Resolved`, `resolved_at` is timestamped automatically.

**Request Body:**
```json
{
  "status": "Resolved",
  "assigned_department": "TEPA Rapid Repair Unit"
}
```

---

#### `GET /stats`
**Headers:** `Authorization: Bearer <admin_token>`
Returns system aggregate analytics:
```json
{
  "total_complaints": 3,
  "by_category": {
    "Road": 1,
    "Water/Drainage": 1,
    "Waste": 1,
    "Electricity": 0,
    "Safety": 0,
    "Other": 0
  },
  "by_priority": {
    "Low": 0,
    "Medium": 0,
    "High": 2,
    "Critical": 1
  },
  "by_status": {
    "Open": 2,
    "Assigned": 0,
    "In Progress": 0,
    "Resolved": 1
  },
  "avg_resolution_time_hours": 0.0,
  "duplicate_count": 0
}
```

---

#### `GET /complaints`
**Headers:** `Authorization: Bearer <admin_token>`
Filtered list of all complaints for admin portal with optional filters: `category`, `priority`, `status`, `department`, `location`, `phone`, `date_from`, `date_to`.

---

## Render Deployment Settings

1. **Environment Variables on Render**:
   - `ADMIN_PASSWORD`: `<your-admin-password>` (e.g. `civic_admin_2026`)
   - `GEMINI_API_KEY`: Google Gemini API Key
   - `GROQ_API_KEY`: *(Optional)* Groq API Key
   - `DATABASE_URL`: `sqlite:///./civic_services.db`
   - `SIMILARITY_THRESHOLD`: `0.55`
   - `PYTHON_VERSION`: `3.11.9`

2. **Start Command**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

3. **Public Base URL**:
   `https://ai-smart-civic-services-sd5w.onrender.com`
   (Swagger UI available at `/docs`).
