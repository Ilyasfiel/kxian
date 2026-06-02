from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from kxian_bot.evidence import redact_for_evidence, write_evidence
from kxian_bot.market_data import load_klines_from_file


SAMPLE_MANIFEST_SCHEMA = "kxian.sample_manifest.v1"
SAMPLE_MANIFEST_SCHEMA_VERSION = 1
STRATEGY_RESEARCH_EVIDENCE_SCHEMA = "kxian.strategy_research.evidence.v1"
STRATEGY_RESEARCH_EVIDENCE_SCHEMA_VERSION = 1
FINAL_OOS_TOUCH_POLICY = "do_not_use_for_screening_until_candidate_locked"


def build_sample_manifest(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    train_files: list[str],
    validation_files: list[str] | None = None,
    final_oos_files: list[str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for role, files in (
        ("train", train_files),
        ("validation", validation_files or []),
        ("final_oos", final_oos_files or []),
    ):
        for index, file_path in enumerate(files, start=1):
            samples.append(_sample_record(file_path, role=role, role_index=index))
    if not samples:
        raise ValueError("sample manifest requires at least one sample file")
    if not train_files:
        raise ValueError("sample manifest requires at least one train file")

    frozen_scope = {
        "exchange": exchange,
        "symbol": symbol,
        "interval": interval,
    }
    policy = {
        "final_oos_touch_policy": FINAL_OOS_TOUCH_POLICY,
        "final_oos_allowed_after": "candidate_locked_by_train_and_validation_evidence",
        "old_samples_allowed_for": "failure_attribution_only",
        "screening_roles": ["train", "validation"],
    }
    stable_payload = {
        "scope": frozen_scope,
        "policy": policy,
        "samples": samples,
        "notes": notes,
    }
    manifest_id = _stable_hash(stable_payload)
    return {
        "schema": SAMPLE_MANIFEST_SCHEMA,
        "schema_version": SAMPLE_MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_id": manifest_id,
        "scope": frozen_scope,
        "policy": policy,
        "samples": samples,
        "notes": notes,
        "audit": {
            "git_commit": _current_git_commit(),
            "dirty_worktree": _git_dirty_worktree(),
            "content_sha256": manifest_id,
        },
    }


def write_sample_manifest(path: str | Path, manifest: dict[str, Any]) -> Path:
    return write_evidence(path, manifest)


def sample_manifest_summary(manifest: dict[str, Any], *, output_file: str | None = None) -> dict[str, Any]:
    samples = manifest.get("samples", [])
    role_counts = Counter(sample.get("role") for sample in samples if isinstance(sample, dict))
    return {
        "status": "pass",
        "schema": manifest.get("schema"),
        "manifest_id": manifest.get("manifest_id"),
        "scope": manifest.get("scope"),
        "sample_count": len(samples) if isinstance(samples, list) else 0,
        "role_counts": dict(sorted(role_counts.items())),
        "policy": manifest.get("policy"),
        "output_file": output_file,
    }


def build_strategy_research_evidence(
    *,
    manifest_path: str,
    hypothesis_id: str,
    hypothesis: str,
    strategy: str,
    command: str,
    result_file: str,
    max_combinations: int | None = None,
    skip_combinations: int = 0,
) -> dict[str, Any]:
    manifest = _load_json_file(manifest_path)
    result = _load_json_file(result_file)
    uses_final_oos = _uses_final_oos(manifest, command, result)
    result_status = result.get("status") if isinstance(result, dict) else None
    candidate_screen_passed = result_status == "pass" and not uses_final_oos
    failure_matrix = _failure_matrix(result)
    return redact_for_evidence(
        {
            "schema": STRATEGY_RESEARCH_EVIDENCE_SCHEMA,
            "schema_version": STRATEGY_RESEARCH_EVIDENCE_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hypothesis": {
                "id": hypothesis_id,
                "text": hypothesis,
                "strategy": strategy,
            },
            "sample_manifest": {
                "path": manifest_path,
                "manifest_id": manifest.get("manifest_id"),
                "manifest_file_sha256": _file_sha256(manifest_path),
                "scope": manifest.get("scope"),
                "sample_count": len(manifest.get("samples", [])) if isinstance(manifest.get("samples"), list) else 0,
                "role_counts": _role_counts(manifest),
            },
            "research_budget": {
                "max_combinations": max_combinations,
                "skip_combinations": skip_combinations,
                "final_oos_touch_policy": FINAL_OOS_TOUCH_POLICY,
            },
            "screening": {
                "command": command,
                "result_file": result_file,
                "result_file_sha256": _file_sha256(result_file),
                "status": result_status,
                "reason": result.get("reason") if isinstance(result, dict) else None,
                "sample_count": result.get("sample_count") if isinstance(result, dict) else None,
                "failure_matrix": failure_matrix,
            },
            "decision": {
                "candidate_screen_passed": candidate_screen_passed,
                "ready_for_profile_promotion": False,
                "promotion_allowed": False,
                "reason": _research_decision_reason(result_status, uses_final_oos),
                "next_allowed_action": "select_samples_train_validation_only"
                if not candidate_screen_passed
                else "lock_candidate_then_run_final_oos_once",
            },
            "audit": {
                "git_commit": _current_git_commit(),
                "dirty_worktree": _git_dirty_worktree(),
            },
            "safety": {
                "will_submit_orders": False,
                "uses_final_oos_for_screening": uses_final_oos,
                "writes_strategy_profile": False,
                "live_ready": False,
            },
        }
    )


def write_strategy_research_evidence(path: str | Path, evidence: dict[str, Any]) -> Path:
    return write_evidence(path, evidence)


def strategy_research_evidence_summary(evidence: dict[str, Any], *, evidence_out: str | None = None) -> dict[str, Any]:
    decision = evidence.get("decision") if isinstance(evidence.get("decision"), dict) else {}
    safety = evidence.get("safety") if isinstance(evidence.get("safety"), dict) else {}
    blocked_reason = decision.get("reason") if safety.get("uses_final_oos_for_screening") is True else None
    return {
        "status": "blocked" if blocked_reason else "pass",
        "reason": blocked_reason,
        "schema": evidence.get("schema"),
        "hypothesis": evidence.get("hypothesis"),
        "sample_manifest": evidence.get("sample_manifest"),
        "screening": evidence.get("screening"),
        "decision": decision,
        "safety": safety,
        "evidence_out": evidence_out,
    }


def _sample_record(file_path: str, *, role: str, role_index: int) -> dict[str, Any]:
    path = Path(file_path)
    candles = load_klines_from_file(str(path))
    first = candles[0] if candles else None
    last = candles[-1] if candles else None
    return {
        "role": role,
        "role_index": role_index,
        "input_file": str(path),
        "sha256": _file_sha256(path),
        "byte_size": path.stat().st_size,
        "candle_count": len(candles),
        "first_open_time": first.open_time if first else None,
        "last_open_time": last.open_time if last else None,
        "first_close_time": first.close_time if first else None,
        "last_close_time": last.close_time if last else None,
        "touch_count": 0,
        "touched": False,
    }


def _load_json_file(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _role_counts(manifest: dict[str, Any]) -> dict[str, int]:
    samples = manifest.get("samples", [])
    if not isinstance(samples, list):
        return {}
    counts = Counter(sample.get("role") for sample in samples if isinstance(sample, dict))
    return dict(sorted(counts.items()))


def _uses_final_oos(manifest: dict[str, Any], command: str, result: dict[str, Any]) -> bool:
    samples = manifest.get("samples", [])
    if not isinstance(samples, list):
        return False
    if any(
        isinstance(item, dict) and str(item.get("role") or "").lower() == "final_oos"
        for item in _walk_dicts(result)
    ):
        return True
    haystack = _normalize_path_text(json.dumps({"command": command, "result": result}, ensure_ascii=False))
    for sample in samples:
        if not isinstance(sample, dict) or sample.get("role") != "final_oos":
            continue
        path_text = str(sample.get("input_file") or "")
        for token in _final_oos_path_tokens(path_text):
            if token and token in haystack:
                return True
    return False


def _final_oos_path_tokens(path_text: str) -> set[str]:
    if not path_text:
        return set()
    path = Path(path_text)
    tokens = {
        _normalize_path_text(path_text),
        _normalize_path_text(path.name),
    }
    parent = path.parent
    if str(parent) and str(parent) != ".":
        tokens.add(_normalize_path_text(str(parent)))
        if _looks_like_final_oos_dir(parent.name):
            tokens.add(_normalize_path_text(parent.name))
    return {token for token in tokens if token}


def _looks_like_final_oos_dir(name: str) -> bool:
    normalized = name.lower().replace("-", "_").replace(" ", "_")
    return "final_oos" in normalized or normalized in {"oos", "finaloos"}


def _normalize_path_text(value: str) -> str:
    return value.replace("\\", "/").lower()


def _failure_matrix(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"status_counts": {}, "reason_counts": {}}
    status_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for item in _walk_dicts(result):
        status = item.get("status")
        reason = item.get("reason")
        if isinstance(status, str) and status:
            status_counts[status] += 1
        if isinstance(reason, str) and reason:
            reason_counts[reason] += 1
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _research_decision_reason(result_status: Any, uses_final_oos: bool) -> str:
    if uses_final_oos:
        return "final_oos_used_before_candidate_lock"
    if result_status != "pass":
        return "screening_not_passed"
    return "candidate_must_be_locked_before_final_oos"


def _current_git_commit() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_dirty_worktree() -> bool | str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return bool(completed.stdout.strip())
