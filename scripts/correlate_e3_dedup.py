#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON inválido en {path}:{line_no}: {exc}") from exc
    return rows


def analyze_raw(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    contents = []
    normalized_events = []

    for row in raw_rows:
        message = row.get("message") or {}
        content = message.get("content", "")
        contents.append(content)

        normalized = {
            "model": row.get("model"),
            "done": row.get("done"),
            "done_reason": row.get("done_reason"),
            "content": content,
        }
        normalized_events.append(json.dumps(normalized, sort_keys=True, ensure_ascii=False))

    consecutive_duplicates = 0
    for i in range(1, len(contents)):
        if contents[i] and contents[i] == contents[i - 1]:
            consecutive_duplicates += 1

    empty_chunks = sum(1 for c in contents if c == "")

    counter = Counter(normalized_events)
    exact_duplicate_events = sum(count - 1 for count in counter.values() if count > 1)

    return {
        "raw_chunk_count": len(raw_rows),
        "empty_chunk_count": empty_chunks,
        "consecutive_duplicate_count": consecutive_duplicates,
        "exact_duplicate_event_count": exact_duplicate_events,
    }


def classify(raw_metrics: dict[str, Any], gui_metrics: dict[str, Any]) -> str:
    raw_dup_consec = raw_metrics.get("consecutive_duplicate_count", 0)
    raw_dup_exact = raw_metrics.get("exact_duplicate_event_count", 0)

    gui_dup_consec = gui_metrics.get("duplicate_consecutive_count", 0)
    gui_dup_fulltext = gui_metrics.get("duplicate_fulltext_count", 0)
    dedup_enabled = gui_metrics.get("dedup_enabled", True)

    if raw_dup_consec > 0 or raw_dup_exact > 0:
        if dedup_enabled:
            return "SERVER_OR_TRANSPORT_DUPLICATION_MITIGATED_BY_CLIENT"
        return "SERVER_OR_TRANSPORT_DUPLICATION_VISIBLE"

    if gui_dup_consec > 0 or gui_dup_fulltext > 0:
        if dedup_enabled:
            return "CLIENT_SIDE_DUPLICATION_MITIGATED_BY_DEDUP"
        return "CLIENT_SIDE_DUPLICATION_VISIBLE_WITH_DEDUP_DISABLED"

    if not dedup_enabled:
        return "NO_DUPLICATION_OBSERVED_IN_RAW_OR_CLIENT_WITH_DEDUP_DISABLED"

    return "NO_DUPLICATION_OBSERVED_BUT_DEDUP_ACTIVE"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Correlaciona stream raw de Ollama con métricas de dedup del GUI."
    )
    parser.add_argument("--raw", required=True, type=Path, help="JSONL raw de Ollama")
    parser.add_argument(
        "--gui-metrics",
        required=True,
        type=Path,
        help="JSONL con métricas emitidas por finishAnswer()",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Imprimir JSON legible",
    )
    args = parser.parse_args()

    raw_rows = load_jsonl(args.raw)
    gui_rows = load_jsonl(args.gui_metrics)

    if not gui_rows:
        raise SystemExit("No hay métricas GUI en el archivo indicado.")

    raw_metrics = analyze_raw(raw_rows)

    # Se usa la última métrica GUI, correspondiente a la última respuesta terminada.
    gui_metrics = gui_rows[-1]

    classification = classify(raw_metrics, gui_metrics)

    report = {
        "raw_metrics": raw_metrics,
        "gui_metrics": gui_metrics,
        "classification": classification,
    }

    if args.pretty:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()