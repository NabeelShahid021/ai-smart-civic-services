"""
StatsService class for AI Smart Civic Services.
Handles aggregation, category/priority/status distribution calculations,
average resolution time, duplicate counting, and database summary generation for Q&A.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from app.models import (
    Complaint,
    VALID_CATEGORIES,
    VALID_PRIORITIES,
    VALID_STATUSES,
)


class StatsService:
    """Computes all statistical metrics and context summaries for analytics and AI Q&A."""

    def get_stats(self, db: Session) -> Dict[str, Any]:
        """
        Calculates and returns complete civic service metrics:
        - total_complaints
        - by_category
        - by_priority
        - by_status
        - avg_resolution_time_hours
        - duplicate_count
        """
        all_complaints: List[Complaint] = db.query(Complaint).all()
        total_complaints = len(all_complaints)

        # Initialize dictionary structures with zero defaults
        by_category = {cat: 0 for cat in VALID_CATEGORIES}
        by_priority = {prio: 0 for prio in VALID_PRIORITIES}
        by_status = {stat: 0 for stat in VALID_STATUSES}

        duplicate_count = 0
        resolution_durations_hours = []

        for c in all_complaints:
            # Category count
            cat = c.category or "Other"
            by_category[cat] = by_category.get(cat, 0) + 1

            # Priority count
            prio = c.priority or "Medium"
            by_priority[prio] = by_priority.get(prio, 0) + 1

            # Status count
            st = c.status or "Open"
            by_status[st] = by_status.get(st, 0) + 1

            # Duplicate count
            if c.duplicate_of is not None:
                duplicate_count += 1

            # Resolution time
            if (c.status or "").lower() == "resolved" and c.resolved_at and c.date_submitted:
                diff_seconds = (c.resolved_at - c.date_submitted).total_seconds()
                if diff_seconds >= 0:
                    resolution_durations_hours.append(diff_seconds / 3600.0)

        # Average resolution time calculation
        if resolution_durations_hours:
            avg_hours = round(sum(resolution_durations_hours) / len(resolution_durations_hours), 2)
        else:
            avg_hours = None

        return {
            "total_complaints": total_complaints,
            "by_category": by_category,
            "by_priority": by_priority,
            "by_status": by_status,
            "avg_resolution_time_hours": avg_hours,
            "duplicate_count": duplicate_count,
        }

    def get_context_summary(
        self,
        db: Session,
        phone: Optional[str] = None,
        complaint_id: Optional[int] = None,
    ) -> str:
        """
        Builds a comprehensive textual snapshot of database metrics and relevant complaints
        to supply as grounded context for the AI /ask assistant.
        """
        lines = []

        # 1. Citizen-specific complaint context by ID
        if complaint_id:
            c = db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()
            if c:
                lines.append(f"TARGET CITIZEN COMPLAINT #{c.complaint_id}:")
                lines.append(f"- Status: {c.status}")
                lines.append(f"- Category: {c.category} | Priority: {c.priority}")
                lines.append(f"- Assigned Department: {c.assigned_department or 'Under Triage'}")
                lines.append(f"- Location: {c.location or 'Not specified'}")
                lines.append(f"- Submitted Date: {c.date_submitted.isoformat()}")
                if c.resolved_at:
                    lines.append(f"- Resolved At: {c.resolved_at.isoformat()}")
                lines.append(f"- AI Summary: {c.ai_summary or c.description}")
                if c.duplicate_of:
                    lines.append(f"- Note: This is linked as a duplicate of original Complaint #{c.duplicate_of}")
                lines.append("")
            else:
                lines.append(f"CITIZEN QUERY NOTICE: No complaint found matching ID #{complaint_id}.")
                lines.append("")

        # 2. Citizen-specific complaints by Phone Number
        if phone:
            clean_phone = phone.strip()
            user_complaints = (
                db.query(Complaint)
                .filter(Complaint.phone.ilike(f"%{clean_phone}%"))
                .order_by(Complaint.date_submitted.desc())
                .all()
            )
            if user_complaints:
                lines.append(f"CITIZEN TRACKED COMPLAINTS (Phone: {clean_phone}):")
                for c in user_complaints:
                    lines.append(
                        f"• #{c.complaint_id} | Status: {c.status} | Category: {c.category} | Dept: {c.assigned_department} | Date: {c.date_submitted.strftime('%Y-%m-%d')}"
                    )
                    lines.append(f"  Summary: {c.ai_summary}")
                lines.append("")
            else:
                lines.append(f"CITIZEN TRACKED COMPLAINTS: No complaints currently on record for phone {clean_phone}.")
                lines.append("")

        # 3. Overall municipal stats and process knowledge
        stats = self.get_stats(db)
        lines.extend([
            "CIVIC SERVICES SYSTEM KNOWLEDGE & MUNICIPAL OVERVIEW:",
            "- Categories: Road (Potholes, broken roads, TEPA), Water/Drainage (Burst pipes, sewer blockage, WASA), Waste (Garbage heaps, sanitation, Waste Management), Electricity (Fallen wires, transformer hazard, LESCO/K-Electric), Safety (Street crime, dark spots, Police), Other (General municipal services).",
            "- How citizens submit: Via the mobile/web portal in English, Urdu, or Roman Urdu with optional photo URL, phone, and GPS coordinates.",
            "- Duplicate Detection: Automatic priority escalation upon multiple citizen reports for faster emergency dispatch.",
            f"- Total Complaints in System: {stats['total_complaints']}",
            f"- Category Breakdown: {stats['by_category']}",
            f"- Status Breakdown: {stats['by_status']}",
            f"- Average Resolution Time: {stats['avg_resolution_time_hours'] if stats['avg_resolution_time_hours'] is not None else 'N/A'} hours",
        ])

        return "\n".join(lines)
