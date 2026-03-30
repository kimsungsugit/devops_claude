from __future__ import annotations

from typing import List


def route_retrieval_domains(question_type: str) -> List[str]:
    qt = str(question_type or "general").strip().lower()
    if qt == "coverage":
        return ["reports", "docs"]
    if qt == "findings":
        return ["reports", "docs"]
    if qt == "troubleshooting":
        return ["reports", "logs", "docs", "code"]
    if qt == "jenkins":
        return ["jenkins", "logs", "docs"]
    if qt == "git":
        return ["docs"]
    if qt == "code":
        return ["code", "docs"]
    if qt == "docs":
        return ["docs"]
    return ["reports", "docs"]
