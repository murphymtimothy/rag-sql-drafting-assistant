from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from assistant.sql_assistant import (
    answer_question,
    log_result,
    CHROMA_PATH,
    LOGS_PATH,
    DEFAULT_MODEL,
    EMBED_MODEL,
    RERANKER_MODEL,
    DEFAULT_K,
    _retrieval_mode,
)
from eval.checker import check_answer, SCHEMA_DOCS

TEST_QUESTIONS = Path(__file__).parent / "test_questions.yaml"
DEFAULT_REPORT = ROOT / "logs" / "eval_report.md"


def run_eval(
    report_path: Path = DEFAULT_REPORT,
    model: str = DEFAULT_MODEL,
    chroma_path: Path = CHROMA_PATH,
    logs_path: Path = LOGS_PATH,
    schema_docs: Path = SCHEMA_DOCS,
) -> dict:
    questions = yaml.safe_load(TEST_QUESTIONS.read_text(encoding="utf-8"))
    rows: list[dict] = []

    for i, q in enumerate(questions, 1):
        question = q["question"]
        expected_tables = q.get("expected_tables", [])
        expected_columns = q.get("expected_columns", [])
        print(f"[{i}/{len(questions)}] {question[:70]}...")

        rag_result = answer_question(question, rag_enabled=True, model=model, chroma_path=chroma_path)
        rag_check = check_answer(rag_result, expected_tables, expected_columns, schema_docs)
        rag_result["eval_score"] = rag_check["score"]
        rag_result["eval_reason"] = rag_check["reason"]
        log_result(rag_result, logs_path)

        no_rag_result = answer_question(question, rag_enabled=False, model=model, chroma_path=chroma_path)
        no_rag_check = check_answer(no_rag_result, expected_tables, expected_columns, schema_docs)
        no_rag_result["eval_score"] = no_rag_check["score"]
        no_rag_result["eval_reason"] = no_rag_check["reason"]
        log_result(no_rag_result, logs_path)

        rows.append({
            "question": question,
            "rag": rag_check,
            "no_rag": no_rag_check,
            "citations": rag_result["citations"],
            "rag_latency_ms": rag_result["latency_ms"],
        })
        print(f"  RAG={rag_check['score']:.1f}  no-RAG={no_rag_check['score']:.1f}  {rag_check['reason']}")

    rag_scores = [r["rag"]["score"] for r in rows]
    no_rag_scores = [r["no_rag"]["score"] for r in rows]
    report_md = _build_report(rows, rag_scores, no_rag_scores, model)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\nReport written → {report_path}")
    print(f"RAG mean score:    {sum(rag_scores)/len(rag_scores):.2f}")
    print(f"No-RAG mean score: {sum(no_rag_scores)/len(no_rag_scores):.2f}")

    return {
        "rag_mean": sum(rag_scores) / len(rag_scores),
        "no_rag_mean": sum(no_rag_scores) / len(no_rag_scores),
        "rows": rows,
    }


def _build_report(rows: list[dict], rag_scores: list, no_rag_scores: list, model: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# SQL Assistant Eval Report",
        f"Generated: {ts} | Model: {model}",
        "",
        f"**Retrieval config:** embed=`{EMBED_MODEL}` · Top-K={DEFAULT_K} · "
        f"reranker=`{RERANKER_MODEL}` · mode: {_retrieval_mode()}",
        "",
        "## Summary",
        "",
        "| | Mean Score |",
        "|---|---|",
        f"| RAG enabled | **{sum(rag_scores)/len(rag_scores):.2f}** |",
        f"| No RAG (baseline) | {sum(no_rag_scores)/len(no_rag_scores):.2f} |",
        "",
        "## Question-by-question results",
        "",
        "| # | Question | RAG | No-RAG | Δ | Citations | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(rows, 1):
        delta = row["rag"]["score"] - row["no_rag"]["score"]
        delta_str = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
        q_short = row["question"][:55] + ("…" if len(row["question"]) > 55 else "")
        cites = ", ".join(row["citations"]) or "—"
        lines.append(
            f"| {i} | {q_short} | {row['rag']['score']:.1f} | {row['no_rag']['score']:.1f} "
            f"| {delta_str} | {cites} | {row['rag']['reason']} |"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    run_eval()
