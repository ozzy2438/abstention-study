#!/usr/bin/env python3
"""Validate the Phase 2 dataset and measure surface-cue and retrieval risks."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
CASES_PATH = DATASET_DIR / "cases.jsonl"
CASES_MANIFEST_PATH = DATASET_DIR / "cases_manifest.json"
PASSAGES_PATH = REPO_ROOT / "corpus" / "passages.jsonl"
RETRIEVAL_PATH = DATASET_DIR / "retrieval.jsonl"
RETRIEVAL_MANIFEST_PATH = DATASET_DIR / "retrieval_manifest.json"
LABELLING_NOTES_PATH = DATASET_DIR / "labelling_notes.md"
SUMMARY_PATH = DATASET_DIR / "audit_summary.json"
LENGTH_PATH = DATASET_DIR / "audit_question_lengths.csv"
CUES_PATH = DATASET_DIR / "audit_lexical_cues.csv"
LEADS_PATH = DATASET_DIR / "audit_leading_phrases.csv"
DUPLICATES_PATH = DATASET_DIR / "audit_near_duplicates.csv"
RETRIEVAL_AUDIT_PATH = DATASET_DIR / "audit_retrieval.csv"

STUDY_SEED = 20260831
FOLDS = 5
TOKEN_RE = re.compile(r"(?u)\b\w+\b")
EXPECTED_KEYS = {
    "case_id",
    "question",
    "category",
    "expected_behaviour",
    "gold_answer",
    "gold_citations",
    "notes",
    "author_confidence",
}
TARGETS = {
    "answerable_clear": 105,
    "answerable_multihop": 45,
    "unanswerable_missing": 45,
    "unanswerable_contradictory": 30,
    "out_of_scope": 45,
    "adversarial": 30,
}
CUE_STOPWORDS = {
    "about",
    "after",
    "also",
    "before",
    "does",
    "every",
    "from",
    "have",
    "into",
    "must",
    "should",
    "that",
    "their",
    "this",
    "under",
    "what",
    "when",
    "which",
    "while",
    "with",
    "would",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def mean(values: Iterable[int]) -> float:
    values_list = list(values)
    return sum(values_list) / len(values_list)


def validate(
    cases: list[dict[str, Any]],
    passages: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[str] = []
    passage_ids = {row["passage_id"] for row in passages}
    case_ids = [row.get("case_id") for row in cases]
    expected_ids = [f"case_{index:04d}" for index in range(1, 301)]

    if len(cases) != 300:
        errors.append(f"case_count={len(cases)}")
    if case_ids != expected_ids:
        errors.append("case IDs are not the exact ordered case_0001..case_0300 set")
    if len(set(case_ids)) != len(case_ids):
        errors.append("duplicate case IDs")
    if Counter(row.get("category") for row in cases) != Counter(TARGETS):
        errors.append("category counts do not match protocol targets")

    normalised_questions: list[str] = []
    for row in cases:
        case_id = row.get("case_id", "unknown")
        if set(row) != EXPECTED_KEYS:
            errors.append(f"{case_id}: schema keys differ")
            continue
        if not isinstance(row["question"], str) or not row["question"].strip():
            errors.append(f"{case_id}: empty question")
        if not isinstance(row["notes"], str) or not row["notes"].strip():
            errors.append(f"{case_id}: empty notes")
        normalised_questions.append(" ".join(row["question"].lower().split()))
        expected = "ANSWER" if row["category"].startswith("answerable_") else "ABSTAIN"
        if row["expected_behaviour"] != expected:
            errors.append(f"{case_id}: incorrect expected behaviour")
        if row["author_confidence"] not in {"high", "medium", "low"}:
            errors.append(f"{case_id}: invalid author confidence")
        if expected == "ANSWER":
            if not isinstance(row["gold_answer"], str) or not row["gold_answer"].strip():
                errors.append(f"{case_id}: answerable case lacks a gold answer")
            if not row["gold_citations"]:
                errors.append(f"{case_id}: answerable case lacks citations")
            if row["category"] == "answerable_clear" and len(row["gold_citations"]) != 1:
                errors.append(f"{case_id}: clear case does not have exactly one citation")
            if row["category"] == "answerable_multihop" and len(set(row["gold_citations"])) < 2:
                errors.append(f"{case_id}: multihop case has fewer than two distinct citations")
        elif row["gold_answer"] is not None or row["gold_citations"] != []:
            errors.append(f"{case_id}: abstain case contains answer gold")
        for passage_id in row["gold_citations"]:
            if passage_id not in passage_ids:
                errors.append(f"{case_id}: missing gold passage {passage_id}")

    if len(set(normalised_questions)) != len(normalised_questions):
        errors.append("duplicate normalised questions")

    labelling_notes = LABELLING_NOTES_PATH.read_text(encoding="utf-8")
    logged_borderline_ids = set(
        re.findall(r"^\| `(case_\d{4})` \|", labelling_notes, flags=re.MULTILINE)
    )
    expected_borderline_ids = {
        row["case_id"]
        for row in cases
        if row["category"] == "unanswerable_contradictory"
        and row["author_confidence"] == "medium"
    }
    if logged_borderline_ids != expected_borderline_ids:
        errors.append("borderline ledger case IDs differ from medium contradictory cases")
    for line in labelling_notes.splitlines():
        if not re.match(r"^\| `case_\d{4}` \|", line):
            continue
        columns = line.split("|")
        conflict_ids = re.findall(
            r"`([a-z0-9_]+-p\d{4}-c\d{3}-[0-9a-f]{12})`", columns[2]
        )
        if len(conflict_ids) < 2:
            errors.append(f"borderline ledger row has fewer than two passages: {line}")
        if any(passage_id not in passage_ids for passage_id in conflict_ids):
            errors.append(f"borderline ledger row contains an unknown passage: {line}")

    retrieval_by_id = {row.get("case_id"): row for row in retrieval_rows}
    if len(retrieval_by_id) != len(retrieval_rows):
        errors.append("duplicate retrieval case IDs")
    if set(retrieval_by_id) != set(case_ids):
        errors.append("retrieval case IDs differ from cases")
    for case_id, row in retrieval_by_id.items():
        retrieved = row.get("passages", [])
        if len(retrieved) != 8:
            errors.append(f"{case_id}: retrieval count is not eight")
            continue
        if [item.get("rank") for item in retrieved] != list(range(1, 9)):
            errors.append(f"{case_id}: invalid retrieval ranks")
        ids = [item.get("passage_id") for item in retrieved]
        if len(set(ids)) != 8 or any(item not in passage_ids for item in ids):
            errors.append(f"{case_id}: invalid retrieved passage IDs")
        expected_order = sorted(
            ((item["score"], item["passage_id"]) for item in retrieved),
            key=lambda item: (-item[0], item[1]),
        )
        observed_order = [(item["score"], item["passage_id"]) for item in retrieved]
        if observed_order != expected_order:
            errors.append(f"{case_id}: retrieval ordering is invalid")

    cases_manifest = json.loads(CASES_MANIFEST_PATH.read_text(encoding="utf-8"))
    retrieval_manifest = json.loads(
        RETRIEVAL_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    if cases_manifest.get("cases_sha256") != sha256_path(CASES_PATH):
        errors.append("cases manifest hash mismatch")
    if retrieval_manifest.get("retrieval_sha256") != sha256_path(RETRIEVAL_PATH):
        errors.append("retrieval manifest hash mismatch")
    if retrieval_manifest.get("cases_sha256") != sha256_path(CASES_PATH):
        errors.append("retrieval manifest cases hash mismatch")

    if errors:
        raise ValueError("Dataset validation failed:\n- " + "\n- ".join(errors))
    return {
        "status": "PASS",
        "checks": {
            "case_count": len(cases),
            "exact_schema": True,
            "case_ids_unique_and_contiguous": True,
            "questions_unique_after_whitespace_case_normalisation": True,
            "gold_behaviour_consistent": True,
            "gold_citations_exist": True,
            "answerable_clear_has_one_gold_passage": True,
            "answerable_multihop_has_at_least_two_gold_passages": True,
            "borderline_ledger_matches_medium_contradictory_cases": True,
            "borderline_ledger_passages_exist": True,
            "retrieval_has_eight_unique_ordered_passages_per_case": True,
            "manifest_hashes_match": True,
        },
    }


def write_length_audit(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, int]]] = defaultdict(list)
    for row in cases:
        by_category[row["category"]].append(
            {
                "words": len(tokens(row["question"])),
                "characters": len(row["question"]),
            }
        )

    output: dict[str, Any] = {}
    with LENGTH_PATH.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "category",
            "n",
            "min_words",
            "p25_words",
            "median_words",
            "p75_words",
            "p95_words",
            "max_words",
            "mean_words",
            "mean_characters",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for category in sorted(by_category):
            word_counts = [item["words"] for item in by_category[category]]
            character_counts = [item["characters"] for item in by_category[category]]
            summary = {
                "category": category,
                "n": len(word_counts),
                "min_words": min(word_counts),
                "p25_words": nearest_rank(word_counts, 0.25),
                "median_words": nearest_rank(word_counts, 0.50),
                "p75_words": nearest_rank(word_counts, 0.75),
                "p95_words": nearest_rank(word_counts, 0.95),
                "max_words": max(word_counts),
                "mean_words": mean(word_counts),
                "mean_characters": mean(character_counts),
            }
            writer.writerow(summary)
            output[category] = {key: value for key, value in summary.items() if key != "category"}
    return output


def lexical_features(question: str) -> Counter[str]:
    unigram_tokens = tokens(question)
    features = Counter(f"u:{token}" for token in unigram_tokens)
    features.update(
        f"b:{left}_{right}" for left, right in zip(unigram_tokens, unigram_tokens[1:])
    )
    return features


def stratified_folds(cases: list[dict[str, Any]]) -> dict[str, int]:
    by_category: dict[str, list[str]] = defaultdict(list)
    for row in cases:
        by_category[row["category"]].append(row["case_id"])
    randomiser = random.Random(STUDY_SEED)
    assignment: dict[str, int] = {}
    for category in sorted(by_category):
        ids = sorted(by_category[category])
        randomiser.shuffle(ids)
        for index, case_id in enumerate(ids):
            assignment[case_id] = index % FOLDS
    return assignment


def macro_recall(truth: list[str], predicted: list[str]) -> float:
    recalls = []
    for category in sorted(TARGETS):
        indices = [index for index, value in enumerate(truth) if value == category]
        recalls.append(
            sum(predicted[index] == category for index in indices) / len(indices)
        )
    return sum(recalls) / len(recalls)


def cross_validated_naive_bayes(cases: list[dict[str, Any]]) -> dict[str, Any]:
    fold_assignment = stratified_folds(cases)
    predicted_by_id: dict[str, str] = {}
    for fold in range(FOLDS):
        training = [row for row in cases if fold_assignment[row["case_id"]] != fold]
        testing = [row for row in cases if fold_assignment[row["case_id"]] == fold]
        document_frequency = Counter()
        training_features: dict[str, Counter[str]] = {}
        for row in training:
            features = lexical_features(row["question"])
            training_features[row["case_id"]] = features
            document_frequency.update(features.keys())
        vocabulary = {feature for feature, count in document_frequency.items() if count >= 2}
        class_counts = Counter(row["category"] for row in training)
        feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
        feature_totals = Counter()
        for row in training:
            filtered = Counter(
                {
                    feature: count
                    for feature, count in training_features[row["case_id"]].items()
                    if feature in vocabulary
                }
            )
            feature_counts[row["category"]].update(filtered)
            feature_totals[row["category"]] += sum(filtered.values())
        vocabulary_size = len(vocabulary)
        for row in testing:
            features = lexical_features(row["question"])
            scores: dict[str, float] = {}
            for category in sorted(TARGETS):
                score = math.log(class_counts[category] / len(training))
                denominator = feature_totals[category] + vocabulary_size
                for feature, count in features.items():
                    if feature not in vocabulary:
                        continue
                    score += count * math.log(
                        (feature_counts[category][feature] + 1) / denominator
                    )
                scores[category] = score
            predicted_by_id[row["case_id"]] = max(
                sorted(scores), key=lambda category: scores[category]
            )

    ordered = sorted(cases, key=lambda row: row["case_id"])
    truth = [row["category"] for row in ordered]
    predicted = [predicted_by_id[row["case_id"]] for row in ordered]
    confusion = {
        actual: {
            prediction: sum(
                one_actual == actual and one_prediction == prediction
                for one_actual, one_prediction in zip(truth, predicted)
            )
            for prediction in sorted(TARGETS)
        }
        for actual in sorted(TARGETS)
    }
    return {
        "method": "stratified 5-fold multinomial naive Bayes over word unigrams and bigrams appearing in at least two training questions",
        "seed": STUDY_SEED,
        "accuracy": sum(a == b for a, b in zip(truth, predicted)) / len(truth),
        "macro_recall": macro_recall(truth, predicted),
        "majority_class_baseline_accuracy": max(TARGETS.values()) / sum(TARGETS.values()),
        "confusion": confusion,
    }


def cross_validated_length_rule(cases: list[dict[str, Any]]) -> dict[str, Any]:
    fold_assignment = stratified_folds(cases)
    predicted_by_id: dict[str, str] = {}
    for fold in range(FOLDS):
        training = [row for row in cases if fold_assignment[row["case_id"]] != fold]
        testing = [row for row in cases if fold_assignment[row["case_id"]] == fold]
        lengths: dict[str, list[int]] = defaultdict(list)
        for row in training:
            lengths[row["category"]].append(len(tokens(row["question"])))
        medians = {
            category: nearest_rank(values, 0.50) for category, values in lengths.items()
        }
        for row in testing:
            length = len(tokens(row["question"]))
            predicted_by_id[row["case_id"]] = min(
                sorted(medians), key=lambda category: (abs(length - medians[category]), category)
            )
    ordered = sorted(cases, key=lambda row: row["case_id"])
    truth = [row["category"] for row in ordered]
    predicted = [predicted_by_id[row["case_id"]] for row in ordered]
    return {
        "method": "stratified 5-fold nearest training-category median question word count",
        "seed": STUDY_SEED,
        "accuracy": sum(a == b for a, b in zip(truth, predicted)) / len(truth),
        "macro_recall": macro_recall(truth, predicted),
    }


def write_lexical_cues(cases: list[dict[str, Any]]) -> dict[str, Any]:
    category_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cases:
        category_rows[row["category"]].append(row)
    token_document_frequency = Counter()
    category_document_frequency: dict[str, Counter[str]] = defaultdict(Counter)
    for row in cases:
        unique_tokens = {
            token
            for token in tokens(row["question"])
            if len(token) >= 3 and token not in CUE_STOPWORDS
        }
        token_document_frequency.update(unique_tokens)
        category_document_frequency[row["category"]].update(unique_tokens)

    cue_rows: list[dict[str, Any]] = []
    for category in sorted(TARGETS):
        category_n = len(category_rows[category])
        other_n = len(cases) - category_n
        scored: list[tuple[float, str, int, int]] = []
        for token, total_df in token_document_frequency.items():
            if total_df < 3:
                continue
            category_df = category_document_frequency[category][token]
            other_df = total_df - category_df
            p_category = (category_df + 0.5) / (category_n + 1.0)
            p_other = (other_df + 0.5) / (other_n + 1.0)
            log_odds = math.log(p_category / (1.0 - p_category)) - math.log(
                p_other / (1.0 - p_other)
            )
            scored.append((log_odds, token, category_df, other_df))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for rank, (log_odds, token, category_df, other_df) in enumerate(
            scored[:12], start=1
        ):
            cue_rows.append(
                {
                    "category": category,
                    "rank": rank,
                    "token": token,
                    "log_odds_vs_other_categories": log_odds,
                    "category_document_frequency": category_df,
                    "other_document_frequency": other_df,
                }
            )
    with CUES_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(cue_rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(cue_rows)

    formulaic_patterns = {
        "category_name": re.compile(
            r"answerable_clear|answerable_multihop|unanswerable|out_of_scope|adversarial",
            re.IGNORECASE,
        ),
        "corpus_does_not_say": re.compile(r"corpus (?:does not|doesn't) say", re.IGNORECASE),
        "not_in_the_corpus": re.compile(r"not in (?:the )?corpus", re.IGNORECASE),
        "outside_scope": re.compile(r"outside (?:the )?scope", re.IGNORECASE),
        "cannot_be_answered": re.compile(r"cannot be answered", re.IGNORECASE),
    }
    formulaic_hits = {
        name: [row["case_id"] for row in cases if pattern.search(row["question"])]
        for name, pattern in formulaic_patterns.items()
    }
    return {
        "top_cues_per_category": 12,
        "cue_method": "smoothed question-level token log odds versus all other categories; tokens must occur in at least three questions",
        "formulaic_question_pattern_hits": formulaic_hits,
    }


def write_leading_phrases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[tuple[str, int, str], int] = Counter()
    for row in cases:
        question_tokens = tokens(row["question"])
        for width in (1, 2, 3):
            phrase = " ".join(question_tokens[:width])
            counts[(row["category"], width, phrase)] += 1
    rows = [
        {"category": category, "token_width": width, "phrase": phrase, "count": count}
        for (category, width, phrase), count in counts.items()
    ]
    rows.sort(key=lambda row: (row["category"], row["token_width"], -row["count"], row["phrase"]))
    with LEADS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return {
        "distinct_first_tokens": len({row["phrase"] for row in rows if row["token_width"] == 1}),
        "maximum_same_category_first_three_token_count": max(
            row["count"] for row in rows if row["token_width"] == 3
        ),
    }


def write_near_duplicates(cases: list[dict[str, Any]]) -> dict[str, Any]:
    token_sets = {row["case_id"]: set(tokens(row["question"])) for row in cases}
    by_id = {row["case_id"]: row for row in cases}
    pairs: list[dict[str, Any]] = []
    ordered_ids = sorted(token_sets)
    for left_index, left_id in enumerate(ordered_ids):
        for right_id in ordered_ids[left_index + 1 :]:
            left = token_sets[left_id]
            right = token_sets[right_id]
            similarity = len(left & right) / len(left | right)
            pairs.append(
                {
                    "left_case_id": left_id,
                    "left_category": by_id[left_id]["category"],
                    "right_case_id": right_id,
                    "right_category": by_id[right_id]["category"],
                    "token_set_jaccard": similarity,
                }
            )
    pairs.sort(
        key=lambda row: (
            -row["token_set_jaccard"],
            row["left_case_id"],
            row["right_case_id"],
        )
    )
    with DUPLICATES_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(pairs[:100])
    return {
        "method": "lowercased Unicode word-token set Jaccard similarity",
        "pair_count_checked": len(pairs),
        "maximum_similarity": pairs[0]["token_set_jaccard"],
        "pairs_at_or_above_0_8": sum(row["token_set_jaccard"] >= 0.8 for row in pairs),
        "saved_highest_pairs": 100,
    }


def write_retrieval_audit(
    cases: list[dict[str, Any]], retrieval_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    retrieval_by_id = {
        row["case_id"]: {item["passage_id"] for item in row["passages"]}
        for row in retrieval_rows
    }
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case["expected_behaviour"] != "ANSWER":
            continue
        retrieved = retrieval_by_id[case["case_id"]]
        gold = set(case["gold_citations"])
        missing = sorted(gold - retrieved)
        rows.append(
            {
                "case_id": case["case_id"],
                "category": case["category"],
                "gold_count": len(gold),
                "retrieved_gold_count": len(gold & retrieved),
                "all_gold_retrieved": not missing,
                "any_gold_retrieved": bool(gold & retrieved),
                "missing_gold_citations": "|".join(missing),
            }
        )
    with RETRIEVAL_AUDIT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    summary: dict[str, Any] = {}
    for category in ["answerable_clear", "answerable_multihop", "all_answerable"]:
        selected = rows if category == "all_answerable" else [row for row in rows if row["category"] == category]
        summary[category] = {
            "n": len(selected),
            "all_gold_retrieved_count": sum(row["all_gold_retrieved"] for row in selected),
            "all_gold_retrieved_rate": sum(row["all_gold_retrieved"] for row in selected) / len(selected),
            "any_gold_retrieved_count": sum(row["any_gold_retrieved"] for row in selected),
            "any_gold_retrieved_rate": sum(row["any_gold_retrieved"] for row in selected) / len(selected),
        }
    summary["cases_missing_at_least_one_gold"] = [
        row["case_id"] for row in rows if not row["all_gold_retrieved"]
    ]
    return summary


def main() -> None:
    cases = read_jsonl(CASES_PATH)
    passages = read_jsonl(PASSAGES_PATH)
    retrieval_rows = read_jsonl(RETRIEVAL_PATH)
    validation = validate(cases, passages, retrieval_rows)
    summary = {
        "schema_version": "1.0.0",
        "source_hashes": {
            "cases_sha256": sha256_path(CASES_PATH),
            "passages_sha256": sha256_path(PASSAGES_PATH),
            "retrieval_sha256": sha256_path(RETRIEVAL_PATH),
        },
        "category_counts": dict(sorted(Counter(row["category"] for row in cases).items())),
        "author_confidence_counts": dict(
            sorted(Counter(row["author_confidence"] for row in cases).items())
        ),
        "validation": validation,
        "question_lengths": write_length_audit(cases),
        "surface_classifier": cross_validated_naive_bayes(cases),
        "length_only_classifier": cross_validated_length_rule(cases),
        "lexical_cues": write_lexical_cues(cases),
        "leading_phrases": write_leading_phrases(cases),
        "near_duplicates": write_near_duplicates(cases),
        "retrieval_gold_coverage": write_retrieval_audit(cases, retrieval_rows),
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "validation": validation["status"],
                "surface_classifier_accuracy": summary["surface_classifier"]["accuracy"],
                "length_only_accuracy": summary["length_only_classifier"]["accuracy"],
                "retrieval_all_gold_rate": summary["retrieval_gold_coverage"]["all_answerable"]["all_gold_retrieved_rate"],
                "audit_summary_sha256": sha256_path(SUMMARY_PATH),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
