from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .db import get_connection, init_db


class AnswerBank:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path is not None else Path(__file__).resolve().parent.parent / "data" / "jobs.db"
        init_db(self.db_path)

    def _normalize(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    def save_answer(self, question: str, answer: str, field_type: str = "text") -> None:
        connection = get_connection(self.db_path)
        try:
            question_norm = self._normalize(question)
            connection.execute(
                """
                INSERT INTO answer_bank (question_norm, answer, field_type, approved, last_used)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(question_norm) DO UPDATE SET
                    answer=excluded.answer,
                    field_type=excluded.field_type,
                    approved=1,
                    last_used=excluded.last_used
                """,
                (question_norm, answer, field_type, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        finally:
            connection.close()

    def lookup(self, question: str) -> str | None:
        connection = get_connection(self.db_path)
        try:
            normalized = self._normalize(question)
            row = connection.execute(
                "SELECT answer FROM answer_bank WHERE question_norm = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            if row:
                return row["answer"]
            exact_partial = connection.execute(
                "SELECT answer FROM answer_bank WHERE question_norm LIKE ? LIMIT 1",
                (f"%{normalized}%",),
            ).fetchone()
            if exact_partial:
                return exact_partial["answer"]
            return None
        finally:
            connection.close()

    def fuzzy_lookup(self, question: str, threshold: int = 90) -> str | None:
        connection = get_connection(self.db_path)
        try:
            normalized = self._normalize(question)
            best_match = None
            best_score = 0
            for row in connection.execute("SELECT question_norm, answer FROM answer_bank"):
                other = row["question_norm"]
                score = 100 if other == normalized else 0
                if other in normalized or normalized in other:
                    score = 90
                if score > best_score:
                    best_score = score
                    best_match = row["answer"]
            if best_score >= threshold:
                return best_match
            return None
        finally:
            connection.close()
