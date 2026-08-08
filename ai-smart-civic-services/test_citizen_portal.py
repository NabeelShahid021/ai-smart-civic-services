"""
Comprehensive Verification Suite for Citizen Authentication & Protected Complaint Workflows (v1.2.0).
"""
import os
import sys

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
from app.models import Citizen, Complaint

client = TestClient(app)

print("=" * 80)
print("RUNNING CITIZEN PORTAL & COMPLAINT SUBMISSION VERIFICATION SUITE")
print("=" * 80)

# Step 1: Health check
res_health = client.get("/")
print(f"[1] GET / -> Status {res_health.status_code}: {res_health.json()}")
assert res_health.status_code == 200

# Step 2: Clean database for testing
db_manager.init_db()
with db_manager.get_session() as s:
    s.query(Complaint).delete()
    s.query(Citizen).delete()
print("[2] Database initialized and clean.")

# =========================================================================
# Part 1: Citizen Signup & Validation
# =========================================================================

print("\n--- Test 1: Citizen Signup with Valid CNIC (with dashes) ---")
signup_payload_1 = {
    "cnic": "35201-1234567-1",
    "password": "Password123!",
    "name": "Ali Khan",
    "phone": "03001234567",
}
res_signup_1 = client.post("/auth/signup", json=signup_payload_1)
print(f"Status: {res_signup_1.status_code}")
assert res_signup_1.status_code == 201
data_signup_1 = res_signup_1.json()
print("Signup Response 1:")
print(f"Citizen ID: {data_signup_1['citizen_id']}, Token: {data_signup_1['token'][:25]}...")
assert "token" in data_signup_1
assert data_signup_1["citizen_id"] == 1
citizen_1_token = data_signup_1["token"]
citizen_1_id = data_signup_1["citizen_id"]

print("\n--- Test 2: Citizen Signup with Duplicate CNIC (Expect 409 Conflict) ---")
# Same CNIC entered without dashes: should be recognized as duplicate!
signup_payload_dup = {
    "cnic": "3520112345671",
    "password": "AnotherPassword456!",
    "name": "Ali K.",
}
res_signup_dup = client.post("/auth/signup", json=signup_payload_dup)
print(f"Status: {res_signup_dup.status_code} (Expected 409)")
print(f"Response: {res_signup_dup.json()}")
assert res_signup_dup.status_code == 409

print("\n--- Test 3: Citizen Signup with Invalid CNIC Pattern (Expect 422) ---")
signup_bad_cnic = {
    "cnic": "12345-ABC",
    "password": "Password123!",
}
res_bad_cnic = client.post("/auth/signup", json=signup_bad_cnic)
print(f"Status: {res_bad_cnic.status_code} (Expected 422)")
assert res_bad_cnic.status_code == 422

# =========================================================================
# Part 2: Citizen Login
# =========================================================================

print("\n--- Test 4: Citizen Login with Correct CNIC & Password ---")
login_payload_good = {
    "cnic": "35201-1234567-1",
    "password": "Password123!",
}
res_login_good = client.post("/auth/login", json=login_payload_good)
print(f"Status: {res_login_good.status_code}")
assert res_login_good.status_code == 200
login_data = res_login_good.json()
print(f"Login successful. Citizen ID: {login_data['citizen_id']}")
assert login_data["citizen_id"] == citizen_1_id
assert "token" in login_data

print("\n--- Test 5: Citizen Login with Wrong Password (Expect 401) ---")
login_payload_bad = {
    "cnic": "35201-1234567-1",
    "password": "WrongPassword!",
}
res_login_bad = client.post("/auth/login", json=login_payload_bad)
print(f"Status: {res_login_bad.status_code} (Expected 401)")
print(f"Response: {res_login_bad.json()}")
assert res_login_bad.status_code == 401

print("\n--- Test 6: Citizen Login with Unregistered CNIC (Expect 401) ---")
login_unreg = {
    "cnic": "99999-9999999-9",
    "password": "SomePassword!",
}
res_unreg = client.post("/auth/login", json=login_unreg)
print(f"Status: {res_unreg.status_code} (Expected 401)")
assert res_unreg.status_code == 401

# Register a second citizen for isolation testing
signup_payload_2 = {
    "cnic": "61101-7654321-2",
    "password": "PasswordCitizen2!",
    "name": "Fatima Zahra",
    "phone": "03129876543",
}
res_signup_2 = client.post("/auth/signup", json=signup_payload_2)
assert res_signup_2.status_code == 201
citizen_2_token = res_signup_2.json()["token"]
citizen_2_id = res_signup_2.json()["citizen_id"]
print(f"Registered Citizen 2 with ID {citizen_2_id}")

# =========================================================================
# Part 3: Protected Complaint Submission (POST /submit-complaint)
# =========================================================================

print("\n--- Test 7: Submit Complaint WITHOUT Citizen Token (Expect 401) ---")
complaint_p1 = {
    "description": "Massive pothole on Main Boulevard Gulberg causing severe traffic jams.",
    "location": "Main Boulevard, Gulberg, Lahore",
}
res_unauth_submit = client.post("/submit-complaint", json=complaint_p1)
print(f"Status without token: {res_unauth_submit.status_code} (Expected 401)")
assert res_unauth_submit.status_code == 401

print("\n--- Test 8: Submit Complaint WITH Citizen 1 Token ---")
auth_header_1 = {"Authorization": f"Bearer {citizen_1_token}"}
res_submit_1 = client.post("/submit-complaint", json=complaint_p1, headers=auth_header_1)
print(f"Status with Citizen 1 token: {res_submit_1.status_code}")
assert res_submit_1.status_code == 201
c1_data = res_submit_1.json()
print("Complaint 1 Stored Data:")
print(f"Complaint ID: {c1_data['complaint_id']}, Citizen ID: {c1_data['citizen_id']}, Category: {c1_data['category']}, Dept: {c1_data['assigned_department']}")
assert c1_data["citizen_id"] == citizen_1_id
assert c1_data["category"] == "Road"

print("\n--- Test 9: Submit Complaint WITH Citizen 2 Token ---")
complaint_p2 = {
    "description": "Sector G-9/2 Street 14 mein paani ki main pipeline phati hui hai aur sadak par ganda paani khara hai.",
    "location": "Street 14, Sector G-9/2, Islamabad",
    "phone": "03129876543",
}
auth_header_2 = {"Authorization": f"Bearer {citizen_2_token}"}
res_submit_2 = client.post("/submit-complaint", json=complaint_p2, headers=auth_header_2)
assert res_submit_2.status_code == 201
c2_data = res_submit_2.json()
print(f"Complaint 2 Stored Data: ID={c2_data['complaint_id']}, Citizen ID={c2_data['citizen_id']}, Category={c2_data['category']}")
assert c2_data["citizen_id"] == citizen_2_id
assert c2_data["category"] == "Water/Drainage"

# =========================================================================
# Part 4: Citizen "My Complaints" Endpoint (GET /my-complaints)
# =========================================================================

print("\n--- Test 10: GET /my-complaints for Citizen 1 ---")
res_my_1 = client.get("/my-complaints", headers=auth_header_1)
print(f"Status: {res_my_1.status_code}")
assert res_my_1.status_code == 200
my_1_list = res_my_1.json()
print(f"Citizen 1 has {len(my_1_list)} complaints (Expected 1)")
assert len(my_1_list) == 1
assert my_1_list[0]["citizen_id"] == citizen_1_id
assert my_1_list[0]["complaint_id"] == c1_data["complaint_id"]

print("\n--- Test 11: GET /my-complaints for Citizen 2 ---")
res_my_2 = client.get("/my-complaints", headers=auth_header_2)
assert res_my_2.status_code == 200
my_2_list = res_my_2.json()
print(f"Citizen 2 has {len(my_2_list)} complaints (Expected 1)")
assert len(my_2_list) == 1
assert my_2_list[0]["citizen_id"] == citizen_2_id
assert my_2_list[0]["complaint_id"] == c2_data["complaint_id"]

# =========================================================================
# Part 5: Public Citizen Tracking (GET /track - No Auth Required)
# =========================================================================

print("\n--- Test 12: Public GET /track by Complaint ID ---")
res_track_id = client.get(f"/track?complaint_id={c1_data['complaint_id']}")
print(f"GET /track?complaint_id={c1_data['complaint_id']} -> Status {res_track_id.status_code}")
assert res_track_id.status_code == 200
assert res_track_id.json()["complaint_id"] == c1_data["complaint_id"]

print("\n--- Test 13: Public GET /track by Phone ---")
res_track_phone = client.get("/track?phone=03129876543")
print(f"GET /track?phone=03129876543 -> Status {res_track_phone.status_code}")
assert res_track_phone.status_code == 200
assert len(res_track_phone.json()) >= 1

# =========================================================================
# Part 6: Admin Authentication & Regression Check
# =========================================================================

print("\n--- Test 14: Admin Authentication & Protected Endpoints ---")
admin_pw = os.getenv("ADMIN_PASSWORD", "civic_admin_2026")
res_admin_login = client.post("/admin/login", json={"password": admin_pw})
assert res_admin_login.status_code == 200
admin_token = res_admin_login.json()["token"]
admin_header = {"Authorization": f"Bearer {admin_token}"}
print(f"Admin logged in successfully. Token: {admin_token[:20]}...")

# Admin patch
res_patch = client.patch(f"/complaints/{c1_data['complaint_id']}", json={"status": "Resolved"}, headers=admin_header)
print(f"PATCH /complaints/{c1_data['complaint_id']} (Admin) -> Status {res_patch.status_code}")
assert res_patch.status_code == 200
assert res_patch.json()["status"] == "Resolved"

# Admin stats
res_stats = client.get("/stats", headers=admin_header)
assert res_stats.status_code == 200
print(f"GET /stats (Admin) -> Total Complaints: {res_stats.json()['total_complaints']}")

# Admin complaints list
res_all = client.get("/complaints", headers=admin_header)
assert res_all.status_code == 200
print(f"GET /complaints (Admin) -> Retrieved {len(res_all.json())} complaints across all citizens.")

# =========================================================================
# Part 7: AI Assistant (POST /ask)
# =========================================================================

print("\n--- Test 15: AI Assistant (POST /ask) ---")
res_ask = client.post("/ask", json={"question": "What is the status of my road complaint?", "complaint_id": c1_data["complaint_id"]})
assert res_ask.status_code == 200
print("AI Assistant response:")
print(res_ask.json()["answer"][:200])

print("\n" + "=" * 80)
print("ALL CITIZEN PORTAL & COMPLAINT WORKFLOW TESTS PASSED 100%!")
print("=" * 80)
