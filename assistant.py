"""Conversational incident assistant.

Answers are grounded in the selected incident, the stored run records and the
retrieved troubleshooting documents. With an LLM configured, the model writes
the answer from that context; without one, deterministic answers are built
for each supported question type. Either way the response reports its mode
and the sources it used.
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.ai.diagnosis import (build_evidence_pack, confirmed_facts, incident_query, previous_run,
                              similar_incidents)
from app.ai.llm_client import LLMClient, LLMUnavailableError
from app.ai.rag import get_index
from app.database.models import Incident
from app.recovery.policies import ACTIONS, policy_for

INTENTS = [
    ("history", r"\b(before|again|previous incident|similar|happened|recurr|history)\b"),
    ("changed", r"\b(chang|compar|previous run|yesterday|differ|last run)\w*"),
    ("checks", r"\b(check|validation|validat|rule)\w*"),
    ("resolve", r"\b(fix|resolv|resolution|recover|solve|should i|next step|what to do|remediat)\w*"),
    ("docs", r"\b(documentation|docs?|guide|recommend|runbook|best practice)\w*"),
    ("why", r"\b(why|cause|reason|root|fail|happen|wrong|explain)\w*"),
]

ASSISTANT_PROMPT = """You are DataPulse AI's pipeline troubleshooting assistant.
Answer the user's question using ONLY the context below (incident evidence, run records, retrieved documents).
If the context does not contain the answer, say so plainly. Never invent numbers, logs or outcomes, never claim an
action was executed unless the context says so, and never provide shell commands. Executable recovery actions are
limited to: {actions}. Keep answers concise (under 180 words), separate facts from hypotheses, and cite document
titles in square brackets when you use them."""


def classify(question: str) -> str:
    q = question.lower()
    for intent, pattern in INTENTS:
        if re.search(pattern, q):
            return intent
    return "docs"


def chat(db: Session, question: str, incident: Incident | None = None, history: list[dict] | None = None,
         client: LLMClient | None = None) -> dict:
    client = client or LLMClient()
    intent = classify(question)
    query = question if incident is None else f"{question} {incident_query(incident)}"
    retrieval = get_index().search(query)
    docs = retrieval["hits"]
    facts = confirmed_facts(incident, incident.run) if incident else []
    response = {"intent": intent, "sources": [{"title": d["title"], "section": d["section"], "score": d["score"]}
                                              for d in docs],
                "facts_used": facts, "retrieval_backend": retrieval["backend"],
                "relevant_documents_found": retrieval["relevant_found"]}

    if client.configured:
        try:
            context = {"incident_context": build_evidence_pack(db, incident) if incident else None,
                       "system_confirmed_facts": facts,
                       "previous_run": _prev_summary(db, incident) if incident else None}
            docs_text = "\n\n".join(f"[{d['title']} / {d['section']}]\n{d['text']}" for d in docs) or "(none)"
            convo = "".join(f"{m['role'].upper()}: {m['content'][:600]}\n" for m in (history or [])[-6:])
            user_msg = (f"CONTEXT:\n{json.dumps(context, default=str, indent=1)}\n\nDOCUMENTS:\n{docs_text}\n\n"
                        f"CONVERSATION SO FAR:\n{convo}\nQUESTION: {question}")
            answer = client.complete(ASSISTANT_PROMPT.format(actions=", ".join(ACTIONS)), user_msg)
            response.update({"answer": answer.strip(), "mode": "llm", "model": client.model})
            return response
        except LLMUnavailableError as exc:
            response["llm_error"] = str(exc)
    response.update({"answer": _deterministic_answer(db, intent, incident, facts, docs), "mode": "deterministic",
                     "model": None})
    return response


def _prev_summary(db: Session, incident: Incident) -> dict | None:
    prev = previous_run(db, incident.run)
    if prev is None:
        return None
    return {"status": prev.status, "input_records": prev.input_records, "output_records": prev.output_records,
            "quality_score": prev.quality_score, "missing_pct": prev.metrics.get("missing_pct"),
            "duplicate_pct": prev.metrics.get("duplicate_pct"),
            "columns": ((prev.report or {}).get("schema") or {}).get("actual_columns")}


def _deterministic_answer(db: Session, intent: str, incident: Incident | None, facts: list[str],
                          docs: list[dict]) -> str:
    doc_note = (" Relevant guidance: " + "; ".join(f"[{d['title']} / {d['section']}]" for d in docs[:3]) + "."
                ) if docs else " No sufficiently relevant troubleshooting document was found for this question."
    if incident is None:
        if not docs:
            return ("I could not find documentation relevant to that question in the knowledge base. "
                    "Select an incident to ask about a specific run, or rephrase the question.")
        top = docs[0]
        return f"From [{top['title']} / {top['section']}]: {_first_sentences(top['text'], 3)}" + (
            f" See also [{docs[1]['title']}]." if len(docs) > 1 else "")

    run = incident.run
    policy = policy_for(incident.rule_id)
    if intent == "why":
        return ("Confirmed facts: " + " ".join(facts[:5]) + f" Probable cause (hypothesis): {policy.probable_cause}"
                + doc_note)
    if intent == "checks":
        failed = [c for c in (run.report or {}).get("checks", []) if not c.get("passed", True)]
        if not failed:
            return "All recorded validation checks passed for this run." + doc_note
        parts = []
        for c in failed:
            detail = c.get("detail") or c.get("value")
            parts.append(c["check"].replace("_", " ") + (f" ({detail})" if detail not in (None, [], "") else ""))
        return "Failed checks: " + "; ".join(parts) + "."
    if intent == "changed":
        prev = _prev_summary(db, incident)
        if prev is None:
            return "There is no earlier run of this pipeline to compare with."
        cur_cols = ((run.report or {}).get("schema") or {}).get("actual_columns") or []
        lines = [f"Previous run: status {prev['status']}, {prev['input_records'] or 0:,} input records, "
                 f"quality score {prev['quality_score'] if prev['quality_score'] is not None else 'n/a'}.",
                 f"This run: status {run.status}, {run.input_records or 0:,} input records, quality score "
                 f"{run.quality_score if run.quality_score is not None else 'n/a'}."]
        if prev["columns"] and cur_cols:
            added = sorted(set(cur_cols) - set(prev["columns"]))
            removed = sorted(set(prev["columns"]) - set(cur_cols))
            if added or removed:
                lines.append(f"Columns added: {added or 'none'}; columns removed: {removed or 'none'}.")
            else:
                lines.append("The column set is unchanged.")
        return " ".join(lines)
    if intent == "resolve":
        return (f"Policy '{policy.name}': {policy.automatic} Recommended: {policy.recommended_action} "
                f"Executable actions for this incident: {', '.join(policy.allowed_actions)}." + doc_note)
    if intent == "history":
        similar = similar_incidents(db, incident)
        if not similar:
            return "No earlier incident of this type has been recorded for this pipeline."
        resolved = sum(1 for s in similar if s["status"] == "resolved")
        latest = similar[0]
        return (f"Yes: {len(similar)} earlier incident(s) with rule {incident.rule_id} on this pipeline "
                f"({resolved} resolved). Most recent: {latest['created_at'][:16].replace('T', ' ')} UTC, "
                f"status {latest['status']}." + (f" Resolution: {latest['resolution_notes']}"
                                                 if latest["resolution_notes"] else ""))
    if not docs:
        return "The knowledge base has no sufficiently relevant guidance for this incident."
    return " ".join(f"[{d['title']} / {d['section']}] {_first_sentences(d['text'], 2)}" for d in docs[:2])


def _first_sentences(text: str, n: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(sentences[:n])
