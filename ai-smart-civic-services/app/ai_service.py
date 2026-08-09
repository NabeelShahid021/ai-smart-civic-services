"""
AI Service for Pak Civic Pulse (AI Smart Civic Services).
Handles multilingual LLM triage (Kimi K3 / Groq / Gemini / local intelligent engine), structured JSON extraction,
explainability keyword generation, department recommendation, and natural conversational AI Assistant queries.
"""
import os
import json
import re
import logging
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger("ai_service")

# Core triage system prompt matching hackathon specifications
SYSTEM_PROMPT = """You are a civic complaint triage assistant for a Pakistani city (Pak Civic Pulse platform).
Input can be in English, Urdu, or Roman Urdu — handle all three fluently.

Given a citizen complaint, return ONLY valid JSON (no markdown, no explanation outside the JSON) with these fields:
{
  "category": one of ["Road", "Water/Drainage", "Waste", "Electricity", "Safety", "Other"],
  "priority": one of ["Low", "Medium", "High", "Critical"],
  "summary": "one-sentence actionable summary in English for the service team",
  "keywords": ["2 to 4 words from the complaint justifying the category/priority decision"],
  "department": "responsible department, e.g. WASA, Roads Authority / TEPA, Electricity Board, Waste Management"
}"""

ASSISTANT_SYSTEM_PROMPT = """You are the official AI Civic Assistant for 'Pak Civic Pulse' in Pakistan.
You are a warm, intelligent, helpful, and natural conversational AI.

Scope & Guidelines:
1. FOCUS ON CIVIC SERVICES: You are dedicated to helping citizens with Pakistani civic issues, complaints, and municipal departments (WASA, TEPA, LESCO/K-Electric, LWMC/SWMC).
2. IRRELEVANT / OFF-TOPIC QUERIES: If a user asks something unrelated to civic/municipal services (e.g. food, restaurants, movies, sports):
   - Politely state that you are specialized in civic and municipal services for Pakistani cities.
   - Summarize what you can help with (reporting issues, live complaint stats, department routing, tracking status).
3. CIVIC & SYSTEM INQUIRIES: When the user asks about civic problems or Pak Civic Pulse:
   - Ground your answer in the provided SYSTEM & DATABASE CONTEXT.
   - For count questions (e.g. "How many water leakage complaints are open?"), state the exact count clearly and conversationally.
   - Guide citizens accurately on departments: WASA (Water & Sanitation), TEPA / Roads Authority (Potholes & Roads), LESCO / K-Electric (Electricity & Power), and LWMC / SWMC (Solid Waste Management).
   - Explain how citizens can file complaints with CNIC, pin GPS location, and attach photos.
4. CLEAN & CONVERSATIONAL: Always respond in natural, friendly markdown or plain text. Never dump raw Python dictionaries, technical logs, or JSON.
5. Support English, Urdu (اردو), and Roman Urdu (e.g. 'pani ka masla kon dekhta ha', 'bijli kahan report karein') fluently and respectfully."""

CATEGORY_KEYWORDS = {
    "Road": ["road", "pothole", "sadak", "gaddha", "cracked", "asphalt", "traffic", "accident", "flyover", "sarak", "street", "footpath"],
    "Water/Drainage": ["water", "leak", "pipe", "paani", "drainage", "gutter", "gatar", "sewage", "sewer", "nalah", "overflow", "supply", "wasa", "tanker"],
    "Waste": ["garbage", "trash", "kachra", "dustbin", "waste", "filth", "badbu", "smell", "dump", "safai", "kuda", "debris"],
    "Electricity": ["electricity", "power", "wire", "taar", "pole", "khamba", "light", "spark", "transformer", "load shedding", "voltage", "current", "bijli", "lesco", "kelectric"],
    "Safety": ["safety", "dark", "crime", "theft", "harassment", "danger", "hazard", "khatra", "open manhole", "unsafe", "threat", "police"],
}

DEPARTMENT_MAP = {
    "Road": "Roads Authority / TEPA",
    "Water/Drainage": "WASA (Water & Sanitation Agency)",
    "Waste": "Solid Waste Management Company (LWMC/SWMC)",
    "Electricity": "Electricity Distribution Board (LESCO/K-Electric)",
    "Safety": "Municipal Enforcement & Police",
    "Other": "General Municipal Services",
}


class AIService:
    """Provides LLM triage, structured JSON normalization, and conversational AI Assistant."""

    def __init__(self):
        self.kimi_endpoint = os.getenv("KIMI_ENDPOINT_URL", "https://nabeeljarwar022--ep-kimi-k3-server.us-west.modal.direct").strip()
        self.kimi_token = os.getenv("KIMI_TOKEN", "wk-salPREHeuXzO1ki8SLXq3.ws-uWOYFM4oxQGgjJbHSzvUjh").strip()
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()

    def _clean_json_string(self, raw_text: str) -> str:
        """Strip markdown fences, leading/trailing commentary, and isolate valid JSON."""
        if not raw_text:
            return ""
        text = raw_text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _call_kimi(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """Execute chat completion using Kimi K3 on Modal."""
        if not self.kimi_endpoint or not self.kimi_token:
            return None
        url = self.kimi_endpoint.rstrip("/")
        if not url.endswith("/v1/chat/completions") and not url.endswith("/chat/completions"):
            url = f"{url}/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.kimi_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "moonshotai/Kimi-K3",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        try:
            with httpx.Client(timeout=2.5) as client:
                res = client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"]
                logger.warning(f"Kimi API returned status {res.status_code}: {res.text[:200]}")
        except Exception as e:
            logger.warning(f"Kimi API call exception: {e}")
        return None

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
            "temperature": 0.2,
        }
        if "return ONLY valid JSON" in system:
            payload["response_format"] = {"type": "json_object"}

        try:
            with httpx.Client(timeout=7.0) as client:
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
        
        models_to_try = [self.gemini_model, "gemini-2.0-flash-lite", "gemini-1.5-flash"]
        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_api_key}"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.gemini_api_key,
            }
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"SYSTEM INSTRUCTION:\n{system}\n\nUSER PROMPT / QUERY:\n{prompt}"}
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json" if "return ONLY valid JSON" in system else "text/plain",
                },
            }
            try:
                with httpx.Client(timeout=6.0) as client:
                    res = client.post(url, headers=headers, json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                    elif res.status_code == 429:
                        logger.warning(f"Gemini API ({model}) rate limit (429) hit.")
                    else:
                        logger.warning(f"Gemini API ({model}) returned status {res.status_code}")
            except Exception as e:
                logger.warning(f"Gemini API ({model}) exception: {e}")
        return None

    def _call_llm(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        """Try Kimi on Modal -> Groq -> Gemini -> fallback."""
        if self.kimi_endpoint and self.kimi_token:
            resp = self._call_kimi(prompt, system)
            if resp:
                return resp
        if self.groq_api_key:
            resp = self._call_groq(prompt, system)
            if resp:
                return resp
        if self.gemini_api_key:
            resp = self._call_gemini(prompt, system)
            if resp:
                return resp
        return None

    def _normalize_category(self, cat_str: str) -> str:
        """Ensure category is strictly one of the 6 allowed values."""
        allowed = ["Road", "Water/Drainage", "Waste", "Electricity", "Safety", "Other"]
        clean = (cat_str or "").strip().lower()
        if "road" in clean or "street" in clean or "pothole" in clean or "sadak" in clean:
            return "Road"
        if "water" in clean or "drain" in clean or "gutter" in clean or "sewer" in clean or "pipe" in clean:
            return "Water/Drainage"
        if "waste" in clean or "garbage" in clean or "trash" in clean or "kachra" in clean:
            return "Waste"
        if "electr" in clean or "wire" in clean or "power" in clean or "taar" in clean or "pole" in clean:
            return "Electricity"
        if "safe" in clean or "danger" in clean or "crime" in clean or "hazard" in clean:
            return "Safety"
        for a in allowed:
            if a.lower() == clean:
                return a
        return "Other"

    def _normalize_priority(self, prio_str: str) -> str:
        """Ensure priority is strictly one of the 4 allowed values."""
        allowed = ["Low", "Medium", "High", "Critical"]
        clean = (prio_str or "").strip().lower()
        for a in allowed:
            if a.lower() == clean:
                return a
        if "crit" in clean or "urgent" in clean or "emergency" in clean:
            return "Critical"
        if "high" in clean or "severe" in clean:
            return "High"
        if "low" in clean or "minor" in clean:
            return "Low"
        return "Medium"

    def _rule_based_fallback(self, text: str) -> Dict[str, Any]:
        """High-accuracy fallback classification engine for English, Urdu, and Roman Urdu."""
        lower = text.lower()
        scores: Dict[str, int] = {cat: 0 for cat in CATEGORY_KEYWORDS}
        matched_keywords: List[str] = []

        for cat, kws in CATEGORY_KEYWORDS.items():
            for kw in kws:
                if kw in lower:
                    scores[cat] += 1
                    if kw not in matched_keywords and len(matched_keywords) < 4:
                        matched_keywords.append(kw)

        best_cat = max(scores, key=scores.get)
        if scores[best_cat] == 0:
            best_cat = "Other"
            matched_keywords = ["civic", "issue"]

        critical_markers = ["spark", "fire", "aag", "urgent", "danger", "khatra", "emergency", "current", "hazard", "burst", "blocked hospital"]
        high_markers = ["overflow", "broken", "toota", "accident", "smell", "dark", "no power", "leakage", "phati"]

        if any(m in lower for m in critical_markers):
            priority = "Critical"
        elif any(m in lower for m in high_markers):
            priority = "High"
        elif len(text.strip()) < 30:
            priority = "Low"
        else:
            priority = "Medium"

        snippet = text.strip().replace("\n", " ")
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        summary = f"Citizen reported {best_cat.lower()} issue: {snippet}"

        return {
            "category": best_cat,
            "priority": priority,
            "summary": summary,
            "keywords": matched_keywords if matched_keywords else [best_cat.lower()],
            "department": DEPARTMENT_MAP.get(best_cat, "General Services"),
        }

    def analyze(self, text: str) -> Dict[str, Any]:
        """Triage a complaint description and return structured JSON dictionary."""
        prompt = f"CITIZEN COMPLAINT TEXT:\n{text.strip()}"
        raw_output = self._call_llm(prompt=prompt, system=SYSTEM_PROMPT)

        parsed_data = None
        if raw_output:
            try:
                cleaned = self._clean_json_string(raw_output)
                parsed_data = json.loads(cleaned)
            except Exception as e:
                logger.warning(f"First JSON parse attempt failed: {e}. Retrying...")
                retry_output = self._call_llm(
                    prompt=f"Previous response was not valid JSON. Please return ONLY raw valid JSON for:\n{text.strip()}",
                    system=SYSTEM_PROMPT,
                )
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

        # Fallback
        logger.info("Using multilingual rule-based fallback for complaint classification.")
        return self._rule_based_fallback(text)

    def _generate_smart_contextual_answer(self, question: str, context: str) -> str:
        """
        Intelligently interprets the question and database context to generate
        a clean, human-like, conversational answer with natural multilingual Pakistani phrasing.
        """
        q = question.lower().strip()

        # -------------------------------------------------------------
        # 1. Parse Database Context Counts & Totals
        # -------------------------------------------------------------
        category_counts = {
            "Water/Drainage": 0,
            "Road": 0,
            "Waste": 0,
            "Electricity": 0,
            "Safety": 0,
            "Other": 0,
        }
        total_complaints = 0
        open_count = 0
        resolved_count = 0

        cat_breakdown_match = re.search(r"Category Breakdown:\s*(\{.*?\})", context)
        if cat_breakdown_match:
            try:
                raw_dict = eval(cat_breakdown_match.group(1))
                if isinstance(raw_dict, dict):
                    for k, v in raw_dict.items():
                        category_counts[k] = int(v)
            except Exception:
                pass

        stat_breakdown_match = re.search(r"Status Breakdown:\s*(\{.*?\})", context)
        if stat_breakdown_match:
            try:
                raw_dict = eval(stat_breakdown_match.group(1))
                if isinstance(raw_dict, dict):
                    open_count = int(raw_dict.get("Open", 0)) + int(raw_dict.get("Assigned", 0)) + int(raw_dict.get("In Progress", 0))
                    resolved_count = int(raw_dict.get("Resolved", 0))
            except Exception:
                pass

        tot_match = re.search(r"Total Complaints in System:\s*(\d+)", context)
        if tot_match:
            total_complaints = int(tot_match.group(1))

        # -------------------------------------------------------------
        # 2. Check for Specific Targeted Complaint #ID Query
        # -------------------------------------------------------------
        is_specific_complaint_query = ("#" in q or "status of my" in q or "my complaint" in q or "complaint #" in q or "update on" in q)
        if is_specific_complaint_query and "TARGET CITIZEN COMPLAINT #" in context:
            cid_match = re.search(r"TARGET CITIZEN COMPLAINT #(\d+):", context)
            status_match = re.search(r"- Status:\s*([^\n]+)", context)
            cat_match = re.search(r"- Category:\s*([^\n|]+)", context)
            prio_match = re.search(r"Priority:\s*([^\n]+)", context)
            dept_match = re.search(r"- Assigned Department:\s*([^\n]+)", context)
            loc_match = re.search(r"- Location:\s*([^\n]+)", context)
            sum_match = re.search(r"- AI Summary:\s*([^\n]+)", context)

            cid = cid_match.group(1) if cid_match else "N/A"
            cstatus = status_match.group(1).strip() if status_match else "Open"
            ccat = cat_match.group(1).strip() if cat_match else "General"
            cprio = prio_match.group(1).strip() if prio_match else "Medium"
            cdept = dept_match.group(1).strip() if dept_match else "General Services"
            cloc = loc_match.group(1).strip() if loc_match else "Not specified"
            csum = sum_match.group(1).strip() if sum_match else ""

            return (
                f"📋 **Status for Complaint #{cid}:**\n"
                f"- **Current Status**: **{cstatus}**\n"
                f"- **Category & Urgency**: {ccat} ({cprio} Priority)\n"
                f"- **Assigned Department**: {cdept}\n"
                f"- **Location**: {cloc}\n"
                f"{f'- **Summary**: {csum}' if csum else ''}\n\n"
                f"You can monitor live progress on the Public Tracker page at any time!"
            )

        # -------------------------------------------------------------
        # 3. Greetings & Pleasantries
        # -------------------------------------------------------------
        greetings = ["hi", "hello", "salam", "assalam", "hey", "aoa", "good morning", "good evening", "adaab", "kese ho", "kaise ho"]
        if any(q.startswith(g) or q == g or g in q for g in greetings):
            return (
                "Walaykum Assalam! I'm your AI Civic Assistant for **Pak Civic Pulse**. How can I help you today? "
                "You can ask me how many complaints are open, which department handles a specific issue (like WASA or TEPA), "
                "check your complaint status, or ask how to file a new municipal report."
            )

        # -------------------------------------------------------------
        # 4. Count Intent Check (how many, kitne, total, open count)
        # -------------------------------------------------------------
        is_count_query = any(cw in q for cw in ["how many", "kitne", "kitni", "count", "number of", "total", "open complaints", "system stats"])

        # -------------------------------------------------------------
        # 5. WATER & SEWERAGE INQUIRIES (WASA)
        # Matches: "pani ka masla kon dekhta ha", "water leak", "gutter", "wasa"
        # -------------------------------------------------------------
        has_water_topic = any(w in q for w in ["water", "pani", "paani", "drainage", "pipe", "leak", "gutter", "gatar", "sewer", "sewage", "nalah", "nalka", "wasa"])
        if has_water_topic:
            if is_count_query:
                count = category_counts.get("Water/Drainage", 0)
                if count == 0:
                    return "There are currently **no Water/Drainage complaints** registered in the system."
                elif count == 1:
                    return f"There is currently **1 Water/Drainage complaint** registered in the system (assigned to WASA)."
                else:
                    return f"There are currently **{count} Water/Drainage complaints** registered in the system (managed by WASA)."
            # Department / Issue guidance
            return (
                "💧 **WASA (Water and Sanitation Agency)** handles all water supply issues, pipeline leaks/bursts, "
                "gutter overflows, and sewer blockages in your city. "
                "You can submit a complaint on the homepage with a photo and GPS location to have it dispatched directly to WASA!"
            )

        # -------------------------------------------------------------
        # 6. ELECTRICITY & POWER INQUIRIES (LESCO / K-Electric)
        # Matches: "bijli ke taar kon theek karega", "electricity", "transformer", "lesco"
        # -------------------------------------------------------------
        has_electric_topic = any(w in q for w in ["electricity", "power", "wire", "taar", "tar", "pole", "khamba", "light", "spark", "transformer", "load shedding", "voltage", "current", "bijli", "lesco", "kelectric"])
        if has_electric_topic:
            if is_count_query:
                count = category_counts.get("Electricity", 0)
                if count == 0:
                    return "There are currently **no Electricity complaints** in the system."
                elif count == 1:
                    return f"There is currently **1 Electricity complaint** in the system (routed to the Electricity Board)."
                else:
                    return f"There are currently **{count} Electricity & Power complaints** in the system (routed to the Electricity Board)."
            return (
                "⚡ **LESCO / K-Electric / Electricity Distribution Board** is responsible for repairing dangling power wires, "
                "broken electricity poles, transformer hazards, and streetlight issues. "
                "Report it via the homepage form for urgent AI triage!"
            )

        # -------------------------------------------------------------
        # 7. ROADS & POTHOLES INQUIRIES (TEPA / Roads Authority)
        # Matches: "sarak tooti hui ha", "potholes", "road", "footpath", "tepa"
        # -------------------------------------------------------------
        has_road_topic = any(w in q for w in ["road", "pothole", "sadak", "sarak", "gaddha", "gadha", "cracked", "asphalt", "traffic", "flyover", "street", "footpath", "tepa", "toota", "tooti"])
        if has_road_topic:
            if is_count_query:
                count = category_counts.get("Road", 0)
                if count == 0:
                    return "There are currently **no Road complaints** in the system."
                elif count == 1:
                    return f"There is currently **1 Road complaint** in the system (routed to the Roads Authority / TEPA)."
                else:
                    return f"There are currently **{count} Road & Infrastructure complaints** in the system (routed to the Roads Authority / TEPA)."
            return (
                "🛣️ **TEPA / Roads Authority** manages road repairs, pothole patching, asphalt recarpeting, and broken footpaths. "
                "You can report road hazards directly on Pak Civic Pulse to notify TEPA dispatchers."
            )

        # -------------------------------------------------------------
        # 8. WASTE & SANITATION INQUIRIES (LWMC / SWMC)
        # Matches: "kachra kahan dalein", "garbage", "trash", "safai", "lwmc"
        # -------------------------------------------------------------
        has_waste_topic = any(w in q for w in ["garbage", "trash", "kachra", "dustbin", "waste", "filth", "badbu", "smell", "dump", "safai", "kuda", "debris", "lwmc", "swmc"])
        if has_waste_topic:
            if is_count_query:
                count = category_counts.get("Waste", 0)
                if count == 0:
                    return "There are currently **no Waste Management complaints** in the system."
                elif count == 1:
                    return f"There is currently **1 Waste Management complaint** in the system (routed to Solid Waste Management)."
                else:
                    return f"There are currently **{count} Waste Management complaints** in the system (routed to Solid Waste Management)."
            return (
                "🗑️ **Solid Waste Management Company (LWMC / SWMC)** is responsible for garbage collection, overflowing waste containers, "
                "and neighborhood street sweeping. File a report with a photo to alert your local sanitation team."
            )

        # -------------------------------------------------------------
        # 9. Total / System Summary Counts
        # -------------------------------------------------------------
        if is_count_query:
            return (
                f"📊 **Current System Summary (Pak Civic Pulse):**\n"
                f"- **Total Complaints**: {total_complaints}\n"
                f"- **Active / Open**: {open_count}\n"
                f"- **Resolved**: {resolved_count}\n"
                f"- **Water/Drainage**: {category_counts['Water/Drainage']} | **Roads**: {category_counts['Road']} | **Electricity**: {category_counts['Electricity']} | **Waste**: {category_counts['Waste']}"
            )

        # -------------------------------------------------------------
        # 10. General Department Overview
        # -------------------------------------------------------------
        if any(w in q for w in ["department", "kon dekhta", "kon sambhalta", "zimedar", "agency", "departments"]):
            return (
                "🏛️ **Municipal Department Routing on Pak Civic Pulse:**\n"
                "- 💧 **WASA**: Water pipeline leaks, sewer overflows, drainage blockages\n"
                "- 🛣️ **Roads Authority / TEPA**: Potholes, broken roads, footpaths\n"
                "- ⚡ **LESCO / K-Electric**: Exposed wires, transformers, streetlights\n"
                "- 🗑️ **Waste Management (LWMC)**: Garbage heaps, trash cleaning\n"
                "- 🛡️ **Municipal Enforcement & Police**: Public safety & open hazards"
            )

        # -------------------------------------------------------------
        # 11. Question: How to File / CNIC / Tracking / System Purpose
        # -------------------------------------------------------------
        if any(w in q for w in ["how to", "file", "submit", "register", "tariqa", "kaise karun", "kaise karein"]):
            return (
                "📝 **How to File a Civic Complaint on Pak Civic Pulse:**\n"
                "1. **Sign In**: Click 'Sign in' on the top-right and enter your 13-digit Pakistani CNIC.\n"
                "2. **Describe Problem**: Type the issue in English, Urdu (اردو), or Roman Urdu.\n"
                "3. **Add Location & Photo**: Pin your GPS location and attach an evidence photo.\n"
                "4. **AI Triage**: Our engine immediately categorizes the issue, detects duplicates, and alerts the responsible department!"
            )

        if "track" in q or "tracking" in q:
            return (
                "🔍 **How to Track Your Complaint:**\n"
                "Click on **'Public Tracker'** in the top navigation and enter your **Complaint ID** or your **phone number** to view live progress from submission to resolution!"
            )

        if any(w in q for w in ["who are you", "what is pak civic pulse", "what can you do", "aap kon ho", "kya kar sakte ho"]):
            return (
                "🏛️ **I am the AI Civic Assistant for Pak Civic Pulse!**\n\n"
                "I am specialized in municipal services for Pakistani cities. I can help you with:\n"
                "- 📊 Live civic complaint statistics across your city.\n"
                "- 🏢 Identifying responsible municipal agencies (WASA, TEPA, LESCO, LWMC).\n"
                "- 🔍 Tracking complaint progress from dispatch to field resolution.\n"
                "- 📝 Guidance on submitting reports with photos and GPS pinning."
            )

        # -------------------------------------------------------------
        # 12. Professional Out-of-Scope Civic Redirection Fallback
        # -------------------------------------------------------------
        return (
            "🏛️ I am the **Pak Civic Pulse AI Assistant**, specialized in municipal services and civic complaint management in Pakistan.\n\n"
            "I can assist you with:\n"
            "- 📊 **Checking live complaint statistics** (e.g. open water, road, electricity, or waste issues)\n"
            "- 🏢 **Finding responsible departments** (WASA, TEPA, LESCO, LWMC)\n"
            "- 🔍 **Tracking complaint status** with your Complaint ID\n"
            "- 📝 **Filing a new civic issue** with CNIC, photo, and GPS\n\n"
            "How can I assist you with civic services today?"
        )

    def answer_question(self, question: str, context: str) -> str:
        """
        Answer any natural language question naturally and conversationally,
        grounding responses in the civic system and live database context.
        """
        user_content = (
            f"SYSTEM KNOWLEDGE & CURRENT CIVIC DATABASE CONTEXT:\n{context}\n\n"
            f"USER INQUIRY / QUESTION:\n{question}\n\n"
            f"NATURAL CONVERSATIONAL RESPONSE:"
        )

        resp = self._call_llm(prompt=user_content, system=ASSISTANT_SYSTEM_PROMPT)
        if resp and resp.strip():
            clean_resp = resp.strip()
            if clean_resp.startswith("```") and clean_resp.endswith("```"):
                clean_resp = "\n".join(clean_resp.split("\n")[1:-1]).strip()
            # If LLM returned a robotic echo or empty text, use smart fallback
            if len(clean_resp) > 5 and not clean_resp.startswith("SYSTEM KNOWLEDGE:"):
                return clean_resp

        # Use the intelligent, human-like contextual answer generator
        return self._generate_smart_contextual_answer(question=question, context=context)
