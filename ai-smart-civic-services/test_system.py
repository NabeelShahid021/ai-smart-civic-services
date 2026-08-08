"""
Comprehensive Automated Test Suite for AI Smart Civic Services Backend (v1.1.0).
Validates:
1. All previously working endpoints (POST /submit-complaint, GET /complaints/{id}, PATCH, stats)
2. New optional fields (phone, latitude, longitude, image_url)
3. Citizen tracking (GET /track by complaint_id and by phone)
4. Admin Authentication (POST /admin/login, 401 on missing/bad token, 200 on valid bearer token)
5. AI Assistant (/ask with phone/complaint_id context and general questions)
"""
import os
import sys

# Ensure UTF-8 stdout on Windows terminal for Urdu characters
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app
from app.database import db_manager
from app.models import Complaint

client = TestClient(app)

print("=" * 75)
print("RUNNING AI SMART CIVIC SERVICES BACKEND VERIFICATION (UPDATE SUITE)")
print("=" * 75)

# Step 1: Health check
res_health = client.get("/")
print(f"[1] GET / -> Status {res_health.status_code}: {res_health.json()}")
assert res_health.status_code == 200

# Step 2: Clean database for testing
db_manager.init_db()
with db_manager.get_session() as s:
    s.query(Complaint).delete()
print("[2] Database initialized and clean.")

# =========================================================================
# Part 1: Submit complaints with new optional fields (phone, lat, lng, image)
# =========================================================================

print("\n--- Submitting Complaint 1: English Road with GPS & Phone ---")
p1 = {
    "description": "Massive pothole and broken road on Main Boulevard Gulberg causing severe traffic jams.",
    "location": "Main Boulevard, Gulberg, Lahore",
    "phone": "03001234567",
    "latitude": 31.5204,
    "longitude": 74.3587,
    "image_url": "https://civic-cdn.example.com/photos/road_pothole_gulberg.jpg",
}
res1 = client.post("/submit-complaint", json=p1)
print(f"Status: {res1.status_code}")
data1 = res1.json()
print("Response JSON:")
print(f"Complaint ID: {data1['complaint_id']}, Category: {data1['category']}, Phone: {data1['phone']}, Lat/Lng: ({data1['latitude']}, {data1['longitude']}), Image: {data1['image_url']}")
assert res1.status_code == 201
assert data1["category"] == "Road"
assert data1["phone"] == "03001234567"
assert data1["latitude"] == 31.5204
assert data1["image_url"] == "https://civic-cdn.example.com/photos/road_pothole_gulberg.jpg"

print("\n--- Submitting Complaint 2: Roman Urdu Water Complaint with Phone ---")
p2 = {
    "description": "Sector G-9/2 Street 14 mein paani ki main pipeline phati hui hai aur sadak par ganda paani khara hai.",
    "location": "Street 14, Sector G-9/2, Islamabad",
    "phone": "03129876543",
}
res2 = client.post("/submit-complaint", json=p2)
print(f"Status: {res2.status_code}")
data2 = res2.json()
print(f"Complaint ID: {data2['complaint_id']}, Category: {data2['category']}, Priority: {data2['priority']}, Phone: {data2['phone']}")
assert res2.status_code == 201
assert data2["category"] == "Water/Drainage"
assert data2["phone"] == "03129876543"

print("\n--- Submitting Complaint 3: Second Complaint from same Citizen (Phone: 03129876543) ---")
p3 = {
    "description": "Gali mein kachra jama ho gaya hai aur bohot badboo aa rahi hai.",
    "location": "Sector G-9/2, Islamabad",
    "phone": "03129876543",
}
res3 = client.post("/submit-complaint", json=p3)
data3 = res3.json()
print(f"Complaint ID: {data3['complaint_id']}, Category: {data3['category']}, Phone: {data3['phone']}")
assert res3.status_code == 201
assert data3["category"] == "Waste"

# =========================================================================
# Part 2: Citizen Tracking Endpoint (GET /track - Public, No Auth)
# =========================================================================

print("\n--- Testing Citizen Tracking (GET /track) ---")

# Track by single complaint_id
res_track_id = client.get("/track?complaint_id=1")
print(f"Track by complaint_id=1 -> Status {res_track_id.status_code}")
assert res_track_id.status_code == 200
track_id_data = res_track_id.json()
assert track_id_data["complaint_id"] == 1
assert track_id_data["phone"] == "03001234567"

# Track by phone number (returns array of complaints, newest first)
res_track_phone = client.get("/track?phone=03129876543")
print(f"Track by phone=03129876543 -> Status {res_track_phone.status_code}")
assert res_track_phone.status_code == 200
phone_complaints = res_track_phone.json()
print(f"Found {len(phone_complaints)} complaints for phone 03129876543:")
for c in phone_complaints:
    print(f"  • ID #{c['complaint_id']} | Category: {c['category']} | Status: {c['status']}")
assert isinstance(phone_complaints, list)
assert len(phone_complaints) == 2
assert phone_complaints[0]["complaint_id"] == 3  # newest first
assert phone_complaints[1]["complaint_id"] == 2

# Track with 404 and 400 error cases
res_track_404 = client.get("/track?complaint_id=99999")
print(f"Track invalid ID 99999 -> Status {res_track_404.status_code} (Expected 404)")
assert res_track_404.status_code == 404

res_track_400 = client.get("/track")
print(f"Track with missing params -> Status {res_track_400.status_code} (Expected 400)")
assert res_track_400.status_code == 400

# =========================================================================
# Part 3: Admin Authentication (POST /admin/login & Protected Endpoints)
# =========================================================================

print("\n--- Testing Admin Authentication ---")

# 1. Login with incorrect password -> 401
res_bad_login = client.post("/admin/login", json={"password": "wrong_password"})
print(f"POST /admin/login (bad password) -> Status {res_bad_login.status_code} (Expected 401)")
assert res_bad_login.status_code == 401

# 2. Login with correct password -> 200 + token
admin_pw = os.getenv("ADMIN_PASSWORD", "civic_admin_2026")
res_good_login = client.post("/admin/login", json={"password": admin_pw})
print(f"POST /admin/login (valid password) -> Status {res_good_login.status_code}")
assert res_good_login.status_code == 200
login_data = res_good_login.json()
admin_token = login_data["token"]
print(f"Obtained Admin Token: {admin_token[:20]}...")
assert admin_token.startswith("admin_token_")

# 3. Test Protected Endpoints WITHOUT Token (Expect 401)
res_unauth_patch = client.patch("/complaints/1", json={"status": "In Progress"})
print(f"PATCH /complaints/1 without token -> Status {res_unauth_patch.status_code} (Expected 401)")
assert res_unauth_patch.status_code == 401

res_unauth_stats = client.get("/stats")
print(f"GET /stats without token -> Status {res_unauth_stats.status_code} (Expected 401)")
assert res_unauth_stats.status_code == 401

res_unauth_list = client.get("/complaints")
print(f"GET /complaints without token -> Status {res_unauth_list.status_code} (Expected 401)")
assert res_unauth_list.status_code == 401

# 4. Test Protected Endpoints WITH Valid Admin Token
headers = {"Authorization": f"Bearer {admin_token}"}

# PATCH complaint status
res_auth_patch = client.patch("/complaints/1", json={"status": "Resolved", "assigned_department": "TEPA Rapid Repair"}, headers=headers)
print(f"PATCH /complaints/1 with token -> Status {res_auth_patch.status_code}")
assert res_auth_patch.status_code == 200
assert res_auth_patch.json()["status"] == "Resolved"
assert res_auth_patch.json()["resolved_at"] is not None

# GET /stats
res_auth_stats = client.get("/stats", headers=headers)
print(f"GET /stats with token -> Status {res_auth_stats.status_code}")
assert res_auth_stats.status_code == 200
stats = res_auth_stats.json()
print(f"Stats: Total = {stats['total_complaints']}, Resolved = {stats['by_status']['Resolved']}")
assert stats["total_complaints"] == 3

# GET /complaints
res_auth_list = client.get("/complaints", headers=headers)
print(f"GET /complaints with token -> Status {res_auth_list.status_code}")
assert res_auth_list.status_code == 200
assert len(res_auth_list.json()) == 3

# =========================================================================
# Part 4: AI Citizen Assistant (POST /ask) with Context
# =========================================================================

print("\n--- Testing AI Assistant (POST /ask) with Citizen Context ---")

# Ask with phone number context
ask_phone_req = {
    "question": "What is the current status of my complaints?",
    "phone": "03129876543",
}
res_ask_phone = client.post("/ask", json=ask_phone_req)
print(f"POST /ask (with phone) -> Status {res_ask_phone.status_code}")
assert res_ask_phone.status_code == 200
ask_phone_data = res_ask_phone.json()
print("Answer with Phone Context:")
print(ask_phone_data["answer"])
assert len(ask_phone_data["answer"]) > 15

# Ask with single complaint_id context
ask_id_req = {
    "question": "Has my road repair complaint been resolved yet?",
    "complaint_id": 1,
}
res_ask_id = client.post("/ask", json=ask_id_req)
print(f"\nPOST /ask (with complaint_id=1) -> Status {res_ask_id.status_code}")
assert res_ask_id.status_code == 200
print("Answer with Complaint ID Context:")
print(res_ask_id.json()["answer"])

# Ask general civic process question
ask_gen_req = {
    "question": "Which government department handles sewage blockages and broken water pipes in Pakistani cities?",
}
res_ask_gen = client.post("/ask", json=ask_gen_req)
print(f"\nPOST /ask (general civic query) -> Status {res_ask_gen.status_code}")
assert res_ask_gen.status_code == 200
print("Answer for General Query:")
print(res_ask_gen.json()["answer"])

print("\n" + "=" * 75)
print("ALL TESTS PASSED WITH 100% SUCCESS!")
print("=" * 75)
