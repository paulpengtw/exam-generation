"""Load the approved ICCS content-domain mapping for social studies."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

from src.common.subject_spec import SOCIAL_STUDIES as _SPEC

_DATA_DIR = _SPEC.data_dir
_MAPPING_FILENAME = "內容領域_mapping.csv"


@dataclass(frozen=True)
class DomainMapping:
    """Bidirectional index of learning-content codes and ICCS content domains."""

    code_to_domains: dict[str, set[str]]
    domain_to_codes: dict[str, set[str]]


def _mapping_path(path: Path | None, curriculum_dir: Path | None) -> Path:
    if path is not None:
        return path
    directory = curriculum_dir or Path(
        os.environ.get(_SPEC.curriculum_dir_env, str(_DATA_DIR))
    )
    return directory / _MAPPING_FILENAME


def load_domain_mapping(
    path: Path | None = None,
    *,
    curriculum_dir: Path | None = None,
) -> DomainMapping:
    """Read the UTF-8-SIG mapping CSV and build both lookup directions."""
    source = _mapping_path(path, curriculum_dir)
    code_to_domains: dict[str, set[str]] = {}
    domain_to_codes: dict[str, set[str]] = {}

    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        for row in rows:
            code = (row.get("編碼") or "").strip()
            domains = {
                domain.strip()
                for domain in (row.get("內容領域") or "").split(";")
                if domain.strip()
            }
            if not code or not domains:
                continue
            code_to_domains.setdefault(code, set()).update(domains)
            for domain in domains:
                domain_to_codes.setdefault(domain, set()).add(code)

    return DomainMapping(
        code_to_domains=code_to_domains,
        domain_to_codes=domain_to_codes,
    )


def load_code_to_domains_mapping(
    path: Path | None = None,
    *,
    curriculum_dir: Path | None = None,
) -> dict[str, list[str]]:
    """Read the ICCS mapping as a JSON-serialisable code-to-domains dict."""
    mapping = load_domain_mapping(path, curriculum_dir=curriculum_dir)
    return {
        code: sorted(domains)
        for code, domains in mapping.code_to_domains.items()
    }
