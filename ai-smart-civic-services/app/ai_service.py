"""
AIService class for AI Smart Civic Services.
Handles LLM triage, categorization, priority prediction, multilingual parsing (English, Urdu, Roman Urdu),
and natural language Q&A with Groq/Gemini provider fallback, retry logic, and high-accuracy offline fallback.
"""
import os
import re
import json
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("ai_service")
logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT = """You are a civic complaint triage assistant for a Pakistani city.
Input can be in English, Urdu, or Roman Urdu — handle all three fluently.

Given a citizen complaint, return ONLY valid JSON (no markdown, no explanation outside the JSON) with these fields:
{
  "category": one of ["Road", "Water/Drainage", "Waste", "Electricity", "Safety", "Other"],
  "priority": one of ["Low", "Medium", "High", "Critical"],
  "summary": "one-sentence actionable summary in English for the service team",
  "keywords": ["2 to 4 words from the complaint justifying the category/priority decision"],
  "department": "responsible department, e.g. WASA, Roads Authority, Electricity Board, Waste Management"
}"""

SAFE_FALLBACK: Dict[str, Any] = {
    "category": "Other",
    "priority": "Medium",
    "summary": "Requires manual review — AI classification failed",
    "keywords": [],
    "department": "General Services",
}

VALID_CATEGORIES = ["Road", "Water/Drainage", "Waste", "Electricity", "Safety", "Other"]
VALID_PRIORITIES = ["Low", "Medium", "High", "Critical"]


class AIService:
    """Encapsulates all AI and LLM operations with provider fallback, strict JSON validation, and retries."""

    def __init__(self, groq_api_key: Optional[str] = None, gemini_api_key: Optional[str] = None):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    def _normalize_category(self, cat: str) -> str:
        """Normalize category string variations to exact valid schema values."""
        if not cat or not isinstance(cat, str):
            return "Other"
        cat_clean = cat.strip()
        for valid in VALID_CATEGORIES:
            if valid.lower() == cat_clean.lower() or valid.replace("/", "-").lower() == cat_clean.lower():
                return valid

        cat_lower = cat_clean.lower()
        if "water" in cat_lower or "drain" in cat_lower or "sewer" in cat_lower or "paani" in cat_lower or "pipeline" in cat_lower:
            return "Water/Drainage"
        if "waste" in cat_lower or "garbage" in cat_lower or "trash" in cat_lower or "kachra" in cat_lower:
            return "Waste"
        if "electr" in cat_lower or "power" in cat_lower or "wire" in cat_lower or "bijli" in cat_lower:
            return "Electricity"
        if "safe" in cat_lower or "crime" in cat_lower or "danger" in cat_lower or "khatra" in cat_lower:
            return "Safety"
        if "road" in cat_lower or "street" in cat_lower or "pothole" in cat_lower or "sadak" in cat_lower:
            return "Road"
        return "Other"

    def _normalize_priority(self, prio: str) -> str:
        """Normalize priority string variations."""
        if not prio or not isinstance(prio, str):
            return "Medium"
        prio_lower = prio.lower().strip()
        if "crit" in prio_lower or "urg" in prio_lower or "emergency" in prio_lower:
            return "Critical"
        if "high" in prio_lower:
            return "High"
        if "low" in prio_lower:
            return "Low"
        if "med" in prio_lower:
            return "Medium"
        for valid in VALID_PRIORITIES:
            if valid.lower() == prio_lower:
                return valid
        return "Medium"

    def _clean_json_string(self, raw_text: str) -> str:
        """Extract clean JSON substring from potential LLM markdown codeblocks or conversational text."""
        text = raw_text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
        if fence_match:
            return fence_match.group(1).strip()
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return text[start_idx : end_idx + 1].strip()
        return text

    def _call_groq(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """Execute chat completion using Groq API."""
        if not self.groq_api_key:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=6.0) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"]
                logger.warning(f"Groq API returned status {res.status_code}: {res.text[:200]}")
        except Exception as e:
            logger.warning(f"Groq API call exception: {e}")
        return None

    def _call_gemini(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """Execute content generation using Google Gemini REST API with rate-limit protection."""
        if not self.gemini_api_key:
            return None
        
        models_to_try = [self.gemini_model, "gemini-2.0-flash-lite"]
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"SYSTEM INSTRUCTION:\n{system}\n\nUSER COMPLAINT / QUERY:\n{prompt}"}
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json" if "return ONLY valid JSON" in system else "text/plain",
                },
            }
            try:
                with httpx.Client(timeout=5.0) as client:
                    res = client.post(url, headers=headers, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif res.status_code == 429:
                        logger.warning("Gemini API rate limit (429) hit. Gracefully falling back to local intelligence.")
                        return None
                    else:
                        logger.warning(f"Gemini API ({model}) returned status {res.status_code}")
            except Exception as e:
                logger.warning(f"Gemini API ({model}) exception: {e}")
        return None

    def _call_llm(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """Call Groq first, then fallback to Gemini."""
        if self.groq_api_key:
            resp = self._call_groq(prompt, system)
            if resp:
                return resp
        if self.gemini_api_key:
            resp = self._call_gemini(prompt, system)
            if resp:
                return resp
        return None

    def _rule_based_fallback(self, text: str) -> Dict[str, Any]:
        """High-accuracy multilingual rule-based classifier (English, Urdu script, Roman Urdu)."""
        t = text.lower()

        # 1. Electricity / Power hazard
        # Urdu words: بجلی, تار, کرنٹ, ٹرانسفارمر
        if any(k in t for k in ["بجلی", "تار", "کرنٹ", "ٹرانسفارمر", "bijli", "taar", "tar ", "current", "spark", "transformer", "wire", "voltage", "electric", "pole"]):
            is_crit = any(u in t for u in ["ٹوٹ", "گر", "خطرہ", "shock", "fell", "spark", "khatra", "danger", "down", "gir", "toot"])
            return {
                "category": "Electricity",
                "priority": "Critical" if is_crit else "High",
                "summary": f"Electrical hazard reported: {text[:100]}",
                "keywords": ["electricity hazard", "wires", "bijli"],
                "department": "Electricity Board (LESCO/K-Electric)",
            }

        # 2. Water / Drainage / Sewerage
        # Urdu words: پانی, پائپ, گٹر, سیوریج, نالی
        if any(k in t for k in ["پانی", "پائپ", "گٹر", "سیوریج", "نالی", "paani", "pani", "water", "pipe", "pipeline", "drain", "drainage", "sewer", "gutar", "nali", "overflow", "leak"]):
            is_high = any(u in t for u in ["din", "days", "ganda", "flooding", "phati", "burst", "severe", "khara"])
            return {
                "category": "Water/Drainage",
                "priority": "High" if is_high else "Medium",
                "summary": f"Water supply or drainage issue reported: {text[:100]}",
                "keywords": ["pipeline burst", "paani", "drainage"],
                "department": "WASA",
            }

        # 3. Waste / Garbage / Sanitation
        # Urdu words: کچرا, کوڑا, صفائی, بدبو
        if any(k in t for k in ["کچرا", "کوڑا", "صفائی", "بدبو", "kachra", "kura", "garbage", "trash", "waste", "safai", "smell", "badboo", "dumper", "litter"]):
            return {
                "category": "Waste",
                "priority": "Medium",
                "summary": f"Garbage accumulation and sanitation request: {text[:100]}",
                "keywords": ["waste accumulation", "garbage", "kachra"],
                "department": "Waste Management Company (LWMC/SSWMB)",
            }

        # 4. Public Safety / Crime / Danger
        # Urdu words: چوری, خطرہ, ڈکیتی, اندھیرا, غیر محفوظ
        if any(k in t for k in ["چوری", "خطرہ", "ڈکیتی", "اندھیرا", "غیر محفوظ", "crime", "safety", "robbery", "dark", "unsafe", "chori", "khatra", "danger", "security"]):
            return {
                "category": "Safety",
                "priority": "High",
                "summary": f"Public safety concern reported: {text[:100]}",
                "keywords": ["safety hazard", "crime prevention", "khatra"],
                "department": "City Safety & Police",
            }

        # 5. Road / Pothole / Street damage
        # Urdu words: سڑک, گڑھا, کھڈا, ٹوٹ پھوٹ
        if any(k in t for k in ["سڑک", "گڑھا", "کھڈا", "ٹوٹی", "road", "pothole", "sadak", "gaddha", "khadda", "street damage", "asphalt", "crater"]):
            is_high = any(u in t for u in ["massive", "severe", "traffic", "vehicle damage", "danger", "kharnak", "jam"])
            return {
                "category": "Road",
                "priority": "High" if is_high else "Medium",
                "summary": f"Road maintenance issue reported: {text[:100]}",
                "keywords": ["pothole", "road damage", "sadak"],
                "department": "Roads Authority / TEPA",
            }

        return SAFE_FALLBACK.copy()

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Analyze a citizen complaint in English, Urdu, or Roman Urdu.
        Returns parsed JSON dict matching the schema. Retries once if JSON is invalid.
        Falls back gracefully if LLM is unavailable.
        """
        if not text or not text.strip():
            return SAFE_FALLBACK.copy()

        parsed_data = None
        raw_output = self._call_llm(prompt=text, system=SYSTEM_PROMPT)

        if raw_output:
            try:
                cleaned = self._clean_json_string(raw_output)
                parsed_data = json.loads(cleaned)
            except Exception as e:
                logger.warning(f"Initial JSON parse failed: {e}. Retrying with strict instruction...")
                retry_system = SYSTEM_PROMPT + "\n\nCRITICAL: Respond with valid JSON only. Do not output anything else."
                retry_output = self._call_llm(prompt=text, system=retry_system)
                if retry_output:
                    try:
                        cleaned_retry = self._clean_json_string(retry_output)
                        parsed_data = json.loads(cleaned_retry)
                    except Exception as e2:
                        logger.warning(f"Retry JSON parse failed: {e2}")

        if parsed_data and isinstance(parsed_data, dict):
            try:
                category = self._normalize_category(parsed_data.get("category", "Other"))
                priority = self._normalize_priority(parsed_data.get("priority", "Medium"))
                summary = str(parsed_data.get("summary", "Civic complaint registered.")).strip()
                raw_keywords = parsed_data.get("keywords", [])
                if isinstance(raw_keywords, list):
                    keywords = [str(k).strip() for k in raw_keywords if str(k).strip()]
                elif isinstance(raw_keywords, str):
                    keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
                else:
                    keywords = []

                department = str(parsed_data.get("department", "General Services")).strip()
                if not department:
                    department = "General Services"

                return {
                    "category": category,
                    "priority": priority,
                    "summary": summary,
                    "keywords": keywords[:6],
                    "department": department,
                }
            except Exception as validation_err:
                logger.error(f"Error normalizing LLM response: {validation_err}")

        # Intelligent multilingual rule-based fallback
        logger.info("Using multilingual rule-based fallback for complaint classification.")
        return self._rule_based_fallback(text)

    def answer_question(self, question: str, context: str) -> str:
        """
        Answer a natural language question about current civic complaints using provided summary context.
        """
        system = """You are the AI Assistant for the 'AI Smart Civic Services' complaint management system in Pakistan.
Given the current database context summary and statistics, answer the user's natural language question accurately, concisely, and professionally in plain text.
If the context does not contain enough data, answer based on the available metrics and provide helpful civic assistance."""

        user_content = f"DATABASE CONTEXT & STATISTICS:\n{context}\n\nCITIZEN/OPERATOR QUESTION:\n{question}\n\nANSWER (plain text):"

        resp = self._call_llm(prompt=user_content, system=system)
        if resp and resp.strip():
            clean_resp = resp.strip()
            if clean_resp.startswith("```") and clean_resp.endswith("```"):
                clean_resp = "\n".join(clean_resp.split("\n")[1:-1]).strip()
            return clean_resp

        # Intelligent contextual plain-text answer
        return (
            f"Based on current municipal records:\n{context}\n\n"
            f"Regarding '{question}': The system has cataloged these civic issues with priority triage and department assignments."
        )
