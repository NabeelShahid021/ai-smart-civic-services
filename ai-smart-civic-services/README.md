# AI Smart Civic Services - Backend API

Production-grade, fully working FastAPI backend for **AI Smart Civic Services**, an intelligent civic complaint management system designed for Pakistani cities.

## System Overview
Citizens can submit civic complaints (e.g. broken streetlights, garbage heaps, damaged roads, water leakage, sewer blockages, unsafe areas, dangling electric wires) in **English**, **Urdu (اردو)**, or **Roman Urdu**.

The backend provides:
1. **Multilingual AI Triage**: Automatic classification (`Road`, `Water/Drainage`, `Waste`, `Electricity`, `Safety`, `Other`), priority prediction (`Low`, `Medium`, `High`, `Critical`), one-sentence English summary, explainability keywords, and responsible department recommendations (e.g. WASA, TEPA/Roads Authority, LESCO/K-Electric, Waste Management).
2. **LLM Swappable Provider with Fallback**: Primary integration via **Groq API** (`llama-3.3-70b-versatile`), automated fallback to **Google Gemini API** (`gemini-2.5-flash`), plus robust offline rule-based triage.
3. **Local Fast Duplicate Detection & Auto-Escalation**: Powered by **scikit-learn TF-IDF + Cosine Similarity**. Automatically links duplicates and escalates the original complaint's priority (e.g., `Medium` -> `High`) to reflect multiple citizen reports.
4. **Statistical Analytics (`GET /stats`)**: Real-time distribution by category, priority, status, average resolution time, and duplicate counts.
5. **AI Q&A Assistant (`POST /ask`)**: Natural-language conversational query endpoint grounded on live database records and summary context.
6. **Decoupled Frontend Ready**: Wildcard CORS (`*`) enabled for seamless external frontend integration.

---

## Project Structure (OOP Architecture)
```
ai-smart-civic-services/
├── app/
│   ├── __init__.py           # Application package
│   ├── main.py               # FastAPI app, route definitions, CORS, error handling
│   ├── database.py           # DatabaseManager class (SQLite setup, session handling)
│   ├── models.py             # SQLAlchemy ORM models + Pydantic schemas
│   ├── ai_service.py         # AIService class (Groq/Gemini, parsing, retries, fallback)
│   ├── complaint_manager.py  # ComplaintManager class (CRUD, TF-IDF duplicate detection & escalation)
│   └── stats_service.py      # StatsService class (aggregation & statistical logic)
├── requirements.txt          # Pinned production dependencies
├── .env.example              # Environment variables template
├── .env                      # Local environment configuration
├── render.yaml               # Zero-configuration Render Web Service specification
├── run.py                    # Convenience local server runner
└── README.md                 # Complete documentation & deployment guide
```

---

## Quick Start (Local Setup)

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone <your-repo-url>
cd ai-smart-civic-services
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env` and provide either your `GROQ_API_KEY` or `GEMINI_API_KEY`:
```bash
cp .env.example .env
```
Edit `.env`:
```ini
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
GEMINI_MODEL=gemini-2.5-flash
DATABASE_URL=sqlite:///./civic_services.db
SIMILARITY_THRESHOLD=0.6
```

### 4. Running the Server
Run with Uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Or use the runner:
```bash
python run.py
```
Open **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## REST API Endpoints

### 1. `POST /submit-complaint`
Submits a new complaint for AI triage and duplicate check.

**Request Body:**
```json
{
  "description": "Hamare mohallay mein pichlay 4 din se paani ki main pipeline phati hui hai aur ganda paani sadak par khara hai.",
  "location": "Sector G-9/2, Islamabad"
}
```

**Response (201 Created):**
```json
{
  "complaint_id": 1,
  "description": "Hamare mohallay mein pichlay 4 din se paani ki main pipeline phati hui hai aur ganda paani sadak par khara hai.",
  "category": "Water/Drainage",
  "priority": "High",
  "location": "Sector G-9/2, Islamabad",
  "date_submitted": "2026-08-08T18:25:00.123456",
  "status": "Open",
  "assigned_department": "WASA",
  "ai_summary": "Main water pipeline burst causing sewage accumulation on road for 4 days.",
  "ai_keywords": ["pipeline burst", "paani", "drainage", "water leak"],
  "duplicate_of": null,
  "resolved_at": null
}
```

---

### 2. `GET /complaints`
Query and filter complaints with multiple criteria.

**Query Parameters (Optional):**
- `category`: `Road`, `Water/Drainage`, `Waste`, `Electricity`, `Safety`, `Other`
- `priority`: `Low`, `Medium`, `High`, `Critical`
- `status`: `Open`, `Assigned`, `In Progress`, `Resolved`
- `department`: e.g. `WASA`, `Roads Authority`
- `location`: keyword search
- `date_from`, `date_to`: ISO format datetime

---

### 3. `GET /complaints/{complaint_id}`
Fetch single complaint by ID with full AI classification details.

---

### 4. `PATCH /complaints/{complaint_id}`
Update complaint status or assigned department. If marked as `Resolved`, `resolved_at` is automatically set to the current UTC timestamp.

**Request Body:**
```json
{
  "status": "Resolved",
  "assigned_department": "WASA Emergency Team"
}
```

---

### 5. `GET /stats`
Returns aggregated analytics across the complaint database.

**Response (200 OK):**
```json
{
  "total_complaints": 4,
  "by_category": {
    "Road": 1,
    "Water/Drainage": 2,
    "Waste": 0,
    "Electricity": 1,
    "Safety": 0,
    "Other": 0
  },
  "by_priority": {
    "Low": 0,
    "Medium": 1,
    "High": 2,
    "Critical": 1
  },
  "by_status": {
    "Open": 3,
    "Assigned": 0,
    "In Progress": 0,
    "Resolved": 1
  },
  "avg_resolution_time_hours": 1.25,
  "duplicate_count": 1
}
```

---

### 6. `POST /ask`
Natural language Q&A assistant grounded on live database records and summary context.

**Request Body:**
```json
{
  "question": "How many water and drainage complaints are currently active?"
}
```

**Response (200 OK):**
```json
{
  "question": "How many water and drainage complaints are currently active?",
  "answer": "Currently, there are 2 Water/Drainage complaints registered in the system, with 1 Open and 1 Resolved."
}
```

---

## Render Deployment Instructions

### Method 1: Deploy with `render.yaml` (Blueprint)
1. Push this repository to GitHub or GitLab.
2. Log into [Render.com](https://render.com).
3. Click **New +** -> **Blueprint**.
4. Connect your repository. Render will automatically detect `render.yaml`.
5. Under Environment Variables, supply your `GEMINI_API_KEY` and/or `GROQ_API_KEY`.
6. Click **Apply**.

### Method 2: Manual Web Service Setup on Render
1. Click **New +** -> **Web Service**.
2. Connect your repo.
3. Configure the following settings:
   - **Name**: `ai-smart-civic-services`
   - **Environment**: `Python 3`
   - **Region**: Any (e.g., Oregon)
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add Environment Variables:
   - `GEMINI_API_KEY`: `your_gemini_api_key`
   - `GROQ_API_KEY`: `your_groq_api_key` (optional)
   - `PYTHON_VERSION`: `3.11.9`
5. Click **Create Web Service**.

Your live public API base URL will be:
`https://ai-smart-civic-services.onrender.com`
(Interactive Swagger Docs available at `https://ai-smart-civic-services.onrender.com/docs`).
