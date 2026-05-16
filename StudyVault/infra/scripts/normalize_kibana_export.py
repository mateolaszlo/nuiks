from __future__ import annotations

import json
from pathlib import Path


RAW_EXPORT_PATH = Path(__file__).resolve().parents[1] / "kibana" / "export.ndjson"
NORMALIZED_EXPORT_PATH = Path(__file__).resolve().parents[1] / "kibana" / "studyvault-observability.ndjson"
DATA_VIEW_IDS_BY_TITLE = {
    "studyvault-logs-*": "studyvault-logs",
    "metricbeat*": "metricbeat",
    "studyvault-storage-*": "studyvault-storage",
}
DROP_TYPES = {"config", "config-global", "index-pattern"}
KEEP_TYPES = {"search", "dashboard"}


def is_export_footer(payload: dict[str, object]) -> bool:
    return "exportedCount" in payload and "missingReferences" in payload


def load_exported_index_patterns(lines: list[str]) -> dict[str, str]:
    patterns: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("type") != "index-pattern":
            continue
        attributes = payload.get("attributes", {})
        title = attributes.get("title")
        if isinstance(title, str):
            patterns[payload["id"]] = title
    return patterns


def normalize_references(
    references: list[dict[str, object]],
    exported_patterns: dict[str, str],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for reference in references:
        if reference.get("type") != "index-pattern":
            normalized.append(reference)
            continue
        reference_id = reference.get("id")
        title = exported_patterns.get(reference_id)
        if title is None:
            raise RuntimeError(f"Unknown exported data view id in reference: {reference_id}")
        stable_id = DATA_VIEW_IDS_BY_TITLE.get(title)
        if stable_id is None:
            raise RuntimeError(f"Unsupported exported data view title: {title}")
        updated = dict(reference)
        updated["id"] = stable_id
        normalized.append(updated)
    return normalized


def normalize_export(raw_path: Path = RAW_EXPORT_PATH, output_path: Path = NORMALIZED_EXPORT_PATH) -> int:
    lines = raw_path.read_text().splitlines()
    exported_patterns = load_exported_index_patterns(lines)
    normalized_lines: list[str] = []

    for line in lines:
        if not line.strip():
            continue
        payload = json.loads(line)
        if is_export_footer(payload):
            continue
        payload_type = payload.get("type")
        if payload_type in DROP_TYPES:
            continue
        if payload_type not in KEEP_TYPES:
            raise RuntimeError(f"Unsupported Kibana saved object type in export: {payload_type}")
        payload["references"] = normalize_references(payload.get("references", []), exported_patterns)
        normalized_lines.append(json.dumps(payload, separators=(",", ":")))

    output_path.write_text("\n".join(normalized_lines) + "\n")
    return len(normalized_lines)


def main() -> int:
    count = normalize_export()
    print(f"Normalized {count} Kibana saved objects into {NORMALIZED_EXPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
