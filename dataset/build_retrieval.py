#!/usr/bin/env python3
"""Precompute deterministic BM25 retrieval for the frozen evaluation cases."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
from collections import Counter
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
CASES_PATH = DATASET_DIR / "cases.jsonl"
PASSAGES_PATH = REPO_ROOT / "corpus" / "passages.jsonl"
RETRIEVAL_PATH = DATASET_DIR / "retrieval.jsonl"
MANIFEST_PATH = DATASET_DIR / "retrieval_manifest.json"
DIAGNOSTICS_PATH = DATASET_DIR / "retrieval_diagnostics.json"

TOKEN_PATTERN = r"(?u)\b\w+\b"
TOKEN_RE = re.compile(TOKEN_PATTERN)
K1 = 1.5
B = 0.75
TOP_K = 8


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def build_index(passages: list[dict[str, Any]]) -> dict[str, Any]:
    term_frequencies: list[Counter[str]] = []
    document_frequencies: Counter[str] = Counter()
    document_lengths: list[int] = []

    for passage in passages:
        frequencies = Counter(tokenize(passage["text"]))
        term_frequencies.append(frequencies)
        document_frequencies.update(frequencies.keys())
        document_lengths.append(sum(frequencies.values()))

    if not passages or any(length == 0 for length in document_lengths):
        raise ValueError("The canonical passage corpus must be non-empty and tokenisable")

    return {
        "term_frequencies": term_frequencies,
        "document_frequencies": document_frequencies,
        "document_lengths": document_lengths,
        "average_document_length": sum(document_lengths) / len(document_lengths),
    }


def score_passage(
    query_tokens: list[str],
    frequencies: Counter[str],
    document_frequencies: Counter[str],
    document_length: int,
    average_document_length: float,
    corpus_size: int,
) -> float:
    score = 0.0
    length_normalisation = K1 * (
        1.0 - B + B * document_length / average_document_length
    )
    for token in query_tokens:
        frequency = frequencies.get(token, 0)
        if frequency == 0:
            continue
        matching_documents = document_frequencies[token]
        inverse_document_frequency = math.log1p(
            (corpus_size - matching_documents + 0.5) / (matching_documents + 0.5)
        )
        score += inverse_document_frequency * (
            frequency * (K1 + 1.0) / (frequency + length_normalisation)
        )
    return score


def retrieve(
    cases: list[dict[str, Any]], passages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    index = build_index(passages)
    rows: list[dict[str, Any]] = []
    for case in cases:
        query_tokens = tokenize(case["question"])
        scored = []
        for passage_index, passage in enumerate(passages):
            score = score_passage(
                query_tokens=query_tokens,
                frequencies=index["term_frequencies"][passage_index],
                document_frequencies=index["document_frequencies"],
                document_length=index["document_lengths"][passage_index],
                average_document_length=index["average_document_length"],
                corpus_size=len(passages),
            )
            scored.append((score, passage["passage_id"]))
        scored.sort(key=lambda item: (-item[0], item[1]))
        rows.append(
            {
                "case_id": case["case_id"],
                "passages": [
                    {"rank": rank, "passage_id": passage_id, "score": score}
                    for rank, (score, passage_id) in enumerate(
                        scored[:TOP_K], start=1
                    )
                ],
            }
        )
    return rows


def build_diagnostics(
    cases: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, dict[str, str]]:
    retrieval_by_id = {
        row["case_id"]: {item["passage_id"] for item in row["passages"]}
        for row in rows
    }
    diagnostics: dict[str, dict[str, str]] = {}
    for case in sorted(cases, key=lambda item: item["case_id"]):
        if case["expected_behaviour"] != "ANSWER":
            continue
        gold = set(case["gold_citations"])
        retrieved_gold = gold & retrieval_by_id[case["case_id"]]
        if retrieved_gold == gold:
            hit = "full"
        elif retrieved_gold:
            hit = "partial"
        else:
            hit = "none"
        diagnostics[case["case_id"]] = {"bm25_top8_gold_hit": hit}
    return diagnostics


def write_outputs(
    cases: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, int]:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=False) + "\n" for row in rows
    )
    RETRIEVAL_PATH.write_text(payload, encoding="utf-8", newline="\n")
    diagnostics = build_diagnostics(cases, rows)
    DIAGNOSTICS_PATH.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    diagnostic_counts = dict(
        sorted(
            Counter(
                item["bm25_top8_gold_hit"] for item in diagnostics.values()
            ).items()
        )
    )
    manifest = {
        "schema_version": "1.0.0",
        "python_version": platform.python_version(),
        "cases_path": "dataset/cases.jsonl",
        "cases_sha256": sha256_path(CASES_PATH),
        "passages_path": "corpus/passages.jsonl",
        "passages_sha256": sha256_path(PASSAGES_PATH),
        "retrieval_path": "dataset/retrieval.jsonl",
        "retrieval_sha256": sha256_path(RETRIEVAL_PATH),
        "retrieval_diagnostics_path": "dataset/retrieval_diagnostics.json",
        "retrieval_diagnostics_sha256": sha256_path(DIAGNOSTICS_PATH),
        "retrieval_diagnostics_answerable_count": len(diagnostics),
        "retrieval_diagnostics_counts": diagnostic_counts,
        "case_count": len(rows),
        "passage_count": len(load_jsonl(PASSAGES_PATH)),
        "token_pattern": TOKEN_PATTERN,
        "lowercase": True,
        "query_term_multiplicity": "retained",
        "k1": K1,
        "b": B,
        "top_k": TOP_K,
        "idf": "ln(1 + (N - n_t + 0.5) / (n_t + 0.5))",
        "tie_break": "passage_id ascending",
        "score_serialisation": "CPython standard JSON binary64 float",
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return diagnostic_counts


def main() -> None:
    cases = load_jsonl(CASES_PATH)
    passages = load_jsonl(PASSAGES_PATH)
    rows = retrieve(cases, passages)
    diagnostic_counts = write_outputs(cases, rows)
    print(
        json.dumps(
            {
                "case_count": len(rows),
                "retrieval_sha256": sha256_path(RETRIEVAL_PATH),
                "retrieval_diagnostics_sha256": sha256_path(DIAGNOSTICS_PATH),
                "retrieval_diagnostics_counts": diagnostic_counts,
                "top_k": TOP_K,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
