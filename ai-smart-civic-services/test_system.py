"""
Automated Test Suite for AI Smart Civic Services Backend.
Validates LLM triage, duplicate detection, priority escalation, statistics, and REST endpoints.
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

print("=" * 70)
print("RUNNING COMPREHENSIVE AI SMART CIVIC SERVICES BACKEND VERIFICATION")
print("=" * 70)

# Step 1: Health check
res_health = client.get("/")
print(f"[1] GET / -> Status {res_health.status_code}: {res_health.json()}")
assert res_health.status_code == 200

# Step 2: Clean database for testing
db_manager.init_db()
with db_manager.get_session() as s:
    s.query(Complaint).delete()
print("[2] Database initialized and clean.")

# Test Case 1: English Road Complaint
print("\n--- Submitting Test 1: English Road Complaint ---")
p1 = {
    "description": "Massive pothole and broken road on Main Boulevard Gulberg causing severe traffic jams and vehicle damage.",
    "location": "Main Boulevard, Gulberg, Lahore",
}
res1 = client.post("/submit-complaint", json=p1)
print(f"Status: {res1.status_code}")
data1 = res1.json()
print(f"Complaint ID: {data1['complaint_id']}, Category: {data1['category']}, Priority: {data1['priority']}, Dept: {data1['assigned_department']}")
assert res1.status_code == 201
assert data1["category"] == "Road"
assert data1["complaint_id"] == 1
assert data1["duplicate_of"] is None

# Test Case 2: Roman Urdu Water/Drainage Complaint
print("\n--- Submitting Test 2: Roman Urdu Water Complaint ---")
p2 = {
    "description": "Sector G-9/2 Street 14 mein paani ki main pipeline phati hui hai aur sadak par ganda paani khara hai.",
    "location": "Street 14, Sector G-9/2, Islamabad",
}
res2 = client.post("/submit-complaint", json=p2)
print(f"Status: {res2.status_code}")
data2 = res2.json()
print(f"Complaint ID: {data2['complaint_id']}, Category: {data2['category']}, Priority: {data2['priority']}, Dept: {data2['assigned_department']}")
assert res2.status_code == 201
assert data2["category"] == "Water/Drainage"
assert data2["complaint_id"] == 2
assert data2["duplicate_of"] is None
assert data2["priority"] in ["Medium", "High"]

# Test Case 3: Urdu Script Electricity Hazard Complaint
print("\n--- Submitting Test 3: Urdu Script Electricity Hazard ---")
p3 = {
    "description": "گلی نمبر 5 میں بجلی کے تار ٹوٹ کر نیچے گر گئے ہیں اور ہر وقت کرنٹ لگنے کا شدید خطرہ ہے۔",
    "location": "Gali 5, Saddar, Rawalpindi",
}
res3 = client.post("/submit-complaint", json=p3)
print(f"Status: {res3.status_code}")
data3 = res3.json()
print(f"Complaint ID: {data3['complaint_id']}, Category: {data3['category']}, Priority: {data3['priority']}, Dept: {data3['assigned_department']}")
assert res3.status_code == 201
assert data3["category"] == "Electricity"
assert data3["complaint_id"] == 3
assert data3["duplicate_of"] is None

# Test Case 4: Duplicate Detection & Priority Escalation Test (Second Citizen reporting same issue in same street)
print("\n--- Submitting Test 4: Duplicate Water Pipeline Complaint in same location ---")
p4 = {
    "description": "Sector G-9/2 Street 14 par paani ki main pipeline phati hui hai aur paani sadak par khara hai bohot zyada.",
    "location": "Street 14, Sector G-9/2, Islamabad",
}
res4 = client.post("/submit-complaint", json=p4)
print(f"Status: {res4.status_code}")
data4 = res4.json()
print(f"Complaint ID: {data4['complaint_id']}, Category: {data4['category']}, Duplicate of: {data4['duplicate_of']}")
assert res4.status_code == 201
assert data4["duplicate_of"] == 2, f"Expected duplicate_of=2, got {data4['duplicate_of']}"

# Verify that original complaint (#2) priority was escalated
res_orig = client.get(f"/complaints/{data2['complaint_id']}")
data_orig = res_orig.json()
print(f"Original Complaint #2 new priority after auto-escalation: {data_orig['priority']}")
assert data_orig["priority"] in ["High", "Critical"]

# Test Case 5: List & Filter Complaints
print("\n--- Testing GET /complaints filtering ---")
res_filter = client.get("/complaints?category=Water/Drainage")
assert res_filter.status_code == 200
water_complaints = res_filter.json()
print(f"Found {len(water_complaints)} Water/Drainage complaints (Expected 2)")
assert len(water_complaints) == 2

# Test Case 6: Patch Complaint to Resolved
print("\n--- Testing PATCH /complaints/1 to Resolved ---")
patch_payload = {"status": "Resolved", "assigned_department": "TEPA Rapid Road Repair Unit"}
res_patch = client.patch("/complaints/1", json=patch_payload)
print(f"Status: {res_patch.status_code}")
data_patch = res_patch.json()
print(f"Updated status: {data_patch['status']}, resolved_at: {data_patch['resolved_at']}")
assert data_patch["status"] == "Resolved"
assert data_patch["resolved_at"] is not None

# Test Case 7: GET /stats
print("\n--- Testing GET /stats ---")
res_stats = client.get("/stats")
print(f"Status: {res_stats.status_code}")
stats_data = res_stats.json()
print("Stats JSON:")
print(stats_data)
assert stats_data["total_complaints"] == 4
assert stats_data["duplicate_count"] == 1
assert stats_data["by_status"]["Resolved"] == 1
assert stats_data["by_status"]["Open"] == 3

# Test Case 8: POST /ask Natural Language Query
print("\n--- Testing POST /ask ---")
ask_payload = {"question": "How many water and drainage complaints are registered and what is their status?"}
res_ask = client.post("/ask", json=ask_payload)
print(f"Status: {res_ask.status_code}")
ask_data = res_ask.json()
print("AI Q&A Response:")
print(f"Question: {ask_data['question']}")
print(f"Answer: {ask_data['answer']}")
assert res_ask.status_code == 200
assert len(ask_data["answer"]) > 10

# Test Case 9: Error Handling
print("\n--- Testing Error Handling (404 and 422) ---")
res_404 = client.get("/complaints/99999")
print(f"GET /complaints/99999 -> Status {res_404.status_code} (Expected 404)")
assert res_404.status_code == 404

res_422 = client.post("/submit-complaint", json={"description": ""})
print(f"POST /submit-complaint with empty description -> Status {res_422.status_code} (Expected 422)")
assert res_422.status_code == 422

print("\n" + "=" * 70)
print("ALL TESTS PASSED WITH 100% SUCCESS!")
print("=" * 70)
