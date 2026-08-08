"""
ComplaintManager class for AI Smart Civic Services.
Handles business logic: complaint creation, LLM triage coordination,
TF-IDF + cosine similarity duplicate detection, priority escalation, querying, and updating.
"""
import os
from datetime import datetime
import logging
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models import Complaint, ComplaintCreate, ComplaintUpdate
from app.ai_service import AIService

logger = logging.getLogger("complaint_manager")

DEFAULT_SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.55"))
PRIORITY_ESCALATION_ORDER = {
    "Low": "Medium",
    "Medium": "High",
    "High": "Critical",
    "Critical": "Critical",
}


class ComplaintManager:
    """Manages civic complaint lifecycle, AI integration, and duplicate detection."""

    def __init__(self, ai_service: Optional[AIService] = None, similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD):
        self.ai_service = ai_service or AIService()
        self.similarity_threshold = float(os.getenv("SIMILARITY_THRESHOLD", str(similarity_threshold)))

    def _are_locations_similar(self, loc1: Optional[str], loc2: Optional[str]) -> bool:
        """
        Check if two locations are textually similar.
        If either location is missing/empty, they are treated as compatible.
        """
        if not loc1 or not loc2:
            return True
        l1 = loc1.lower().strip()
        l2 = loc2.lower().strip()
        if not l1 or not l2:
            return True
        if l1 in l2 or l2 in l1:
            return True
        # Check token overlap
        tokens1 = set(filter(None, l1.replace(",", " ").replace("-", " ").replace("/", " ").split()))
        tokens2 = set(filter(None, l2.replace(",", " ").replace("-", " ").replace("/", " ").split()))
        if not tokens1 or not tokens2:
            return True
        common = tokens1.intersection(tokens2)
        # If any significant area/sector/street matches
        return len(common) > 0

    def detect_duplicate_and_escalate(
        self,
        new_description: str,
        new_category: str,
        new_location: Optional[str],
        db: Session,
    ) -> Tuple[Optional[int], Optional[Complaint], float]:
        """
        Finds open/assigned/in-progress complaints in the same category, computes TF-IDF cosine similarity,
        and if similarity >= threshold (and locations match), escalates original priority and returns original ID.
        """
        active_statuses = ["Open", "Assigned", "In Progress"]
        candidates: List[Complaint] = (
            db.query(Complaint)
            .filter(Complaint.category == new_category, Complaint.status.in_(active_statuses))
            .all()
        )

        if not candidates:
            return None, None, 0.0

        corpus = [c.description for c in candidates]
        corpus.append(new_description)

        try:
            # Word-level TF-IDF
            word_vec = TfidfVectorizer(ngram_range=(1, 2), token_pattern=r"(?u)\b\w+\b")
            word_matrix = word_vec.fit_transform(corpus)
            word_sim = cosine_similarity(word_matrix[-1], word_matrix[:-1]).flatten()

            # Sub-word char_wb TF-IDF (robust for Roman Urdu spelling variations)
            char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
            char_matrix = char_vec.fit_transform(corpus)
            char_sim = cosine_similarity(char_matrix[-1], char_matrix[:-1]).flatten()

            # Combined max similarity
            combined_sim = [max(w, c) for w, c in zip(word_sim, char_sim)]

            best_idx = int(max(range(len(combined_sim)), key=lambda i: combined_sim[i]))
            best_sim = float(combined_sim[best_idx])

            logger.info(f"Duplicate check: best similarity {best_sim:.4f} with complaint_id={candidates[best_idx].complaint_id}")

            if best_sim >= self.similarity_threshold:
                best_candidate = candidates[best_idx]
                if self._are_locations_similar(new_location, best_candidate.location):
                    # Escalate original priority if not already Critical
                    current_prio = best_candidate.priority or "Medium"
                    escalated_prio = PRIORITY_ESCALATION_ORDER.get(current_prio, "Critical")
                    if current_prio != escalated_prio:
                        logger.info(
                            f"Escalating original complaint {best_candidate.complaint_id} priority from {current_prio} to {escalated_prio}"
                        )
                        best_candidate.priority = escalated_prio
                        db.add(best_candidate)
                        db.commit()
                        db.refresh(best_candidate)

                    return best_candidate.complaint_id, best_candidate, best_sim

        except Exception as e:
            logger.error(f"Error during TF-IDF duplicate detection: {e}", exc_info=True)

        return None, None, 0.0

    def create_complaint(self, data: ComplaintCreate, db: Session) -> Complaint:
        """
        Submits a citizen complaint:
        1. Calls AIService.analyze() for category, priority, summary, keywords, and department
        2. Executes TF-IDF duplicate detection & priority escalation on original
        3. Persists new complaint to SQLite DB and returns it
        """
        # Step 1: AI Triage
        ai_result: Dict[str, Any] = self.ai_service.analyze(data.description)

        category = ai_result.get("category", "Other")
        priority = ai_result.get("priority", "Medium")
        summary = ai_result.get("summary", "Civic complaint logged.")
        keywords = ai_result.get("keywords", [])
        department = ai_result.get("department", "General Services")

        # Step 2: Duplicate Detection
        dup_id, original_complaint, score = self.detect_duplicate_and_escalate(
            new_description=data.description,
            new_category=category,
            new_location=data.location,
            db=db,
        )

        # Step 3: Create & Save Model
        new_complaint = Complaint(
            description=data.description,
            category=category,
            priority=priority,
            location=data.location,
            date_submitted=datetime.utcnow(),
            status="Open",
            assigned_department=department,
            ai_summary=summary,
            duplicate_of=dup_id,
            resolved_at=None,
        )
        new_complaint.keywords_list = keywords

        db.add(new_complaint)
        db.commit()
        db.refresh(new_complaint)
        return new_complaint

    def list_complaints(
        self,
        db: Session,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        department: Optional[str] = None,
        location: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> List[Complaint]:
        """Query and filter complaints, ordered newest first."""
        query = db.query(Complaint)

        if category:
            query = query.filter(Complaint.category.ilike(f"%{category.strip()}%"))
        if priority:
            query = query.filter(Complaint.priority.ilike(f"%{priority.strip()}%"))
        if status:
            query = query.filter(Complaint.status.ilike(f"%{status.strip()}%"))
        if department:
            query = query.filter(Complaint.assigned_department.ilike(f"%{department.strip()}%"))
        if location:
            query = query.filter(Complaint.location.ilike(f"%{location.strip()}%"))
        if date_from:
            query = query.filter(Complaint.date_submitted >= date_from)
        if date_to:
            query = query.filter(Complaint.date_submitted <= date_to)

        return query.order_by(Complaint.date_submitted.desc()).all()

    def get_complaint_by_id(self, complaint_id: int, db: Session) -> Optional[Complaint]:
        """Fetch a single complaint by its primary key ID."""
        return db.query(Complaint).filter(Complaint.complaint_id == complaint_id).first()

    def update_complaint(self, complaint_id: int, update_data: ComplaintUpdate, db: Session) -> Optional[Complaint]:
        """
        Update complaint status or assigned department.
        If status is updated to 'Resolved', sets resolved_at to now.
        """
        complaint = self.get_complaint_by_id(complaint_id, db)
        if not complaint:
            return None

        if update_data.status is not None:
            normalized_status = update_data.status.strip()
            complaint.status = normalized_status
            if normalized_status.lower() == "resolved" and complaint.resolved_at is None:
                complaint.resolved_at = datetime.utcnow()

        if update_data.assigned_department is not None:
            complaint.assigned_department = update_data.assigned_department.strip()

        db.add(complaint)
        db.commit()
        db.refresh(complaint)
        return complaint
