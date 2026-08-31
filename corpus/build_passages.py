#!/usr/bin/env python3
"""Build canonical, page-bounded passages from the frozen PDF corpus."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pypdf
from pypdf import PdfReader


REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus"
SOURCE_MANIFEST_PATH = CORPUS_DIR / "manifest.json"
PASSAGES_PATH = CORPUS_DIR / "passages.jsonl"
PASSAGES_MANIFEST_PATH = CORPUS_DIR / "passages_manifest.json"

MAX_CODEPOINTS = 1800
BOUNDARY_SEARCH_CODEPOINTS = 400
OVERLAP_CODEPOINTS = 200


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_page_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\t", " ")
    text = re.sub(r" +(?=\n|$)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def chunk_page(text: str) -> list[tuple[int, int, str]]:
    if not text:
        return []

    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CODEPOINTS, len(text))
        if end < len(text):
            search_start = max(start, end - BOUNDARY_SEARCH_CODEPOINTS)
            newline_index = text.rfind("\n", search_start, end)
            if newline_index >= search_start:
                end = newline_index + 1

        chunk_text = text[start:end]
        if chunk_text:
            chunks.append((start, end, chunk_text))

        if end >= len(text):
            break
        next_start = end - OVERLAP_CODEPOINTS
        if next_start <= start:
            raise RuntimeError(
                f"Chunking did not advance: start={start}, end={end}"
            )
        start = next_start

    return chunks


def validate_source(document: dict[str, object]) -> Path:
    path = REPO_ROOT / str(document["local_path"])
    data = path.read_bytes()
    actual_sha256 = sha256_bytes(data)
    if actual_sha256 != document["sha256"]:
        raise ValueError(
            f"Source hash mismatch for {path}: {actual_sha256}"
        )
    if len(data) != document["byte_count"]:
        raise ValueError(f"Source byte count mismatch for {path}")
    return path


def build_passages() -> tuple[list[dict[str, object]], dict[str, int]]:
    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    passages: list[dict[str, object]] = []
    counts: Counter[str] = Counter()

    for document in source_manifest["documents"]:
        source_path = validate_source(document)
        reader = PdfReader(source_path)
        if len(reader.pages) != document["page_count"]:
            raise ValueError(f"Source page count mismatch for {source_path}")

        for page_number, page in enumerate(reader.pages, start=1):
            extracted_text = page.extract_text() or ""
            normalised_text = normalise_page_text(extracted_text)
            if not normalised_text.strip():
                raise ValueError(
                    f"No extractable text for {document['doc_id']} page {page_number}"
                )

            for chunk_index, (start, end, text) in enumerate(
                chunk_page(normalised_text), start=1
            ):
                text_sha256 = sha256_bytes(text.encode("utf-8"))
                passage_id = (
                    f"{document['doc_id']}-p{page_number:04d}-"
                    f"c{chunk_index:03d}-{text_sha256[:12]}"
                )
                passages.append(
                    {
                        "passage_id": passage_id,
                        "doc_id": document["doc_id"],
                        "source_title": document["title"],
                        "source_page": page_number,
                        "start_offset": start,
                        "end_offset": end,
                        "text": text,
                        "text_sha256": text_sha256,
                    }
                )
                counts[str(document["doc_id"])] += 1

    return passages, dict(sorted(counts.items()))


def write_outputs(passages: list[dict[str, object]], counts: dict[str, int]) -> None:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in passages
    )
    PASSAGES_PATH.write_text(payload, encoding="utf-8", newline="\n")
    passages_sha256 = sha256_bytes(PASSAGES_PATH.read_bytes())

    output_manifest = {
        "schema_version": "1.0.0",
        "source_manifest": "corpus/manifest.json",
        "source_manifest_sha256": sha256_bytes(SOURCE_MANIFEST_PATH.read_bytes()),
        "passages_path": "corpus/passages.jsonl",
        "passages_sha256": passages_sha256,
        "passage_count": len(passages),
        "passage_count_by_document": counts,
        "extractor": {
            "python_version": platform.python_version(),
            "pypdf_version": pypdf.__version__,
            "method": "PdfReader.pages[index].extract_text()",
        },
        "chunking": {
            "unit": "unicode_codepoints",
            "page_bounded": True,
            "max_codepoints": MAX_CODEPOINTS,
            "boundary_search_codepoints": BOUNDARY_SEARCH_CODEPOINTS,
            "overlap_codepoints": OVERLAP_CODEPOINTS,
            "newline_boundary_in_preceding_chunk": True,
            "offsets": "zero_based_start_inclusive_end_exclusive",
        },
        "normalisation": [
            "CRLF_to_LF",
            "Unicode_NFC",
            "tab_to_single_space",
            "remove_trailing_horizontal_spaces",
            "three_or_more_LF_to_two_LF",
        ],
    }
    PASSAGES_MANIFEST_PATH.write_text(
        json.dumps(output_manifest, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    passages, counts = build_passages()
    write_outputs(passages, counts)
    print(
        json.dumps(
            {
                "passage_count": len(passages),
                "passage_count_by_document": counts,
                "passages_sha256": sha256_bytes(PASSAGES_PATH.read_bytes()),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
