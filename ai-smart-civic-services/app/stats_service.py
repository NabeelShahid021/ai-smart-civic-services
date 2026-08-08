"""
StatsService class for AI Smart Civic Services.
Handles aggregation, category/priority/status distribution calculations,
average resolution time, duplicate counting, and database summary generation for Q&A.
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func
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

    def get_context_summary(self, db: Session) -> str:
        """
        Builds a comprehensive textual snapshot of database metrics and recent complaints
        to supply as grounded context for the AI /ask endpoint.
        """
        stats = self.get_stats(db)
        recent_complaints = (
            db.query(Complaint)
            .order_by(Complaint.date_submitted.desc())
            .limit(20)
            .all()
        )

        lines = [
            f"SYSTEM AGGREGATE SUMMARY:",
            f"- Total Complaints Logged: {stats['total_complaints']}",
            f"- Complaints by Category: {stats['by_category']}",
            f"- Complaints by Priority: {stats['by_priority']}",
            f"- Complaints by Status: {stats['by_status']}",
            f"- Average Resolution Time (Hours): {stats['avg_resolution_time_hours'] if stats['avg_resolution_time_hours'] is not None else 'N/A (No complaints resolved yet)'}",
            f"- Total Linked Duplicates: {stats['duplicate_count']}",
            "",
            "RECENT COMPLAINTS DETAIL:",
        ]

        if not recent_complaints:
            lines.append("No complaints currently submitted in the database.")
        else:
            for idx, c in enumerate(recent_complaints, 1):
                loc = f", Location: {c.location}" if c.location else ""
                dup = f", Duplicate of #{c.duplicate_of}" if c.duplicate_of else ""
                lines.append(
                    f"#{c.complaint_id} | Category: {c.category} | Priority: {c.priority} | Status: {c.status} | Dept: {c.assigned_department}{loc}{dup}"
                )
                lines.append(f"   Summary: {c.ai_summary}")
                lines.append(f"   Keywords: {c.keywords_list}")

        return "\n".join(lines)
