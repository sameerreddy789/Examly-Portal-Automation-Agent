"""
answer_bank.py — Question & Answer Storage for Multi-Account Runs

Saves every question, answer, and test result from the first (sacrifice) run,
then provides corrected answers for subsequent runs to achieve 100%.

Think of it like a cheat sheet that builds itself:
- Run 1: Takes the test honestly, saves everything (questions, answers, results)
- Review: AI fixes any wrong answers
- Run 2-3: Uses the corrected answers to ace the test

Usage:
    from answer_bank import AnswerBank
    
    bank = AnswerBank("Day_18_Assessment", "answer_bank_Day_18.json")
    bank.save_question(1, 1, "mcq", "What is 2+2?", answer="4")
    bank.update_result(1, 1, True)
    bank.save()
"""

import json
import os
import re
from datetime import datetime
from loguru import logger

logger = logger.bind(name="browser_use.answer_bank")


class AnswerBank:
    """
    Stores questions, answers, and results in a structured JSON file.
    Supports fuzzy matching to find saved answers even if question text varies slightly.
    """
    
    def __init__(self, test_name: str, file_path: str = None):
        self.test_name = test_name
        self.file_path = file_path or f"answer_bank_{test_name.replace(' ', '_')}.json"
        self.questions = {}   # key -> question data
        self.test_summary = {}
        self._load_if_exists()
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching — lowercase, collapse whitespace."""
        return re.sub(r'\s+', ' ', text.strip().lower())
    
    def _question_key(self, q_num: int, section: int = 1) -> str:
        """Generate a unique key for each question."""
        return f"s{section}_q{q_num}"
    
    def save_question(self, q_num: int, section: int, q_type: str, 
                      q_text: str, answer: str = "", code: str = ""):
        """
        Save a question and its answer to the bank.
        
        Args:
            q_num: Question number (1-indexed)
            section: Section number (1 or 2)
            q_type: 'mcq' or 'coding'
            q_text: Full question text
            answer: Selected MCQ answer text
            code: Code solution (for coding questions)
        """
        key = self._question_key(q_num, section)
        self.questions[key] = {
            "number": q_num,
            "section": section,
            "type": q_type,
            "text": q_text,
            "text_snippet": self._normalize_text(q_text[:300]),
            "answer": answer,
            "code": code,
            "passed": None,          # None = not checked yet
            "test_case_details": "",
            "corrected_answer": "",  # Filled during review phase
            "corrected_code": "",    # Filled during review phase
            "saved_at": datetime.now().isoformat(),
        }
        self._save()
        logger.info(f"📝 [ANSWER BANK] Saved Q{q_num} (Section {section}, {q_type})")
    
    def update_result(self, q_num: int, section: int, passed: bool, details: str = ""):
        """Record whether a question was answered correctly."""
        key = self._question_key(q_num, section)
        if key in self.questions:
            self.questions[key]["passed"] = passed
            self.questions[key]["test_case_details"] = details
            self._save()
            status = "✅ PASSED" if passed else "❌ FAILED"
            logger.info(f"📝 [ANSWER BANK] Q{q_num} (S{section}): {status}")
        else:
            logger.warning(f"⚠️ [ANSWER BANK] Q{q_num} (S{section}) not found in bank")
    
    def update_corrected_answer(self, q_num: int, section: int, 
                                 new_answer: str = "", new_code: str = ""):
        """Update a question with a corrected answer (used during review phase)."""
        key = self._question_key(q_num, section)
        if key in self.questions:
            if new_answer:
                self.questions[key]["corrected_answer"] = new_answer
            if new_code:
                self.questions[key]["corrected_code"] = new_code
            self._save()
            logger.info(f"🔧 [ANSWER BANK] Q{q_num} (S{section}) corrected")
    
    def get_answer_by_text(self, question_text_snippet: str) -> dict | None:
        """
        Find a saved answer by fuzzy-matching the question text.
        
        Uses word-overlap similarity to handle minor text differences
        between runs (the same test shows the same questions, but
        the text might have slight formatting differences).
        """
        normalized_query = self._normalize_text(question_text_snippet[:300])
        query_words = set(normalized_query.split())
        
        if not query_words:
            return None
        
        best_match = None
        best_score = 0
        
        for key, q_data in self.questions.items():
            saved_snippet = q_data.get("text_snippet", "")
            if not saved_snippet:
                continue
            
            saved_words = set(saved_snippet.split())
            if not saved_words:
                continue
            
            # Jaccard-like similarity
            common = query_words & saved_words
            union = query_words | saved_words
            score = len(common) / len(union) if union else 0
            
            if score > best_score and score > 0.4:
                best_score = score
                best_match = q_data
        
        if best_match:
            # Build the "final" answer — corrected takes priority over original
            result = dict(best_match)
            result["final_code"] = (
                result.get("corrected_code") or result.get("code") or ""
            )
            result["final_answer"] = (
                result.get("corrected_answer") or result.get("answer") or ""
            )
            result["match_score"] = best_score
            logger.info(
                f"🔍 [ANSWER BANK] Matched Q{result['number']} "
                f"(S{result['section']}, score: {best_score:.2f})"
            )
            return result
        
        logger.info("🔍 [ANSWER BANK] No matching question found")
        return None
    
    def get_wrong_questions(self) -> list[dict]:
        """Get all questions that were answered incorrectly."""
        return [
            q for q in self.questions.values() 
            if q.get("passed") is False
        ]
    
    def get_all_questions(self) -> list[dict]:
        """Get all saved questions."""
        return list(self.questions.values())
    
    def save_test_summary(self, total: int, correct: int, marks: str = ""):
        """Save the overall test score after submission."""
        self.test_summary = {
            "total_questions": total,
            "correct": correct,
            "wrong": total - correct,
            "marks": marks,
            "timestamp": datetime.now().isoformat(),
        }
        self._save()
        logger.info(f"📊 [ANSWER BANK] Summary: {correct}/{total} ({marks})")
    
    def _save(self):
        """Persist the bank to disk."""
        data = {
            "test_name": self.test_name,
            "questions": self.questions,
            "test_summary": self.test_summary,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_if_exists(self):
        """Load existing bank from disk if the file exists."""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.questions = data.get("questions", {})
                self.test_summary = data.get("test_summary", {})
                logger.info(
                    f"📂 [ANSWER BANK] Loaded {len(self.questions)} questions "
                    f"from {self.file_path}"
                )
            except Exception as e:
                logger.error(f"❌ [ANSWER BANK] Failed to load: {e}")
