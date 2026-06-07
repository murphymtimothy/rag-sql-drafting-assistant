import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ingest.build_index import build_index, SCHEMA_DOCS, CHROMA_PATH

STATE_FILE = Path(__file__).parent.parent / "logs" / "refresh_state.json"
REFRESH_LOG = Path(__file__).parent.parent / "logs" / "refresh_log.jsonl"


def _hash_docs(schema_docs: Path) -> str:
    """SHA-256 over sorted filenames + file contents."""
    h = hashlib.sha256()
    for f in sorted(schema_docs.glob("*.md")):
        h.update(f.name.encode("utf-8"))
        h.update(f.read_bytes())
    return h.hexdigest()


def _load_state(state_file: Path) -> str:
    """Return the last-known hash, or empty string if no state file."""
    if not state_file.exists():
        return ""
    return json.loads(state_file.read_text(encoding="utf-8")).get("hash", "")


def _save_state(state_file: Path, hash_val: str) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps({"hash": hash_val, "updated": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )


def _log_refresh(
    refresh_log: Path,
    action: str,
    tables_found: int,
    duration_ms: int,
) -> None:
    refresh_log.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "tables_found": tables_found,
        "duration_ms": duration_ms,
    }
    with refresh_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_refresh_cycle(
    schema_docs: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
    state_file: Path = STATE_FILE,
    refresh_log: Path = REFRESH_LOG,
) -> str:
    """
    Check whether schema docs have changed since the last cycle.
    If changed: rebuild the Chroma index and update stored hash.
    Returns 'reindexed' or 'skipped'.
    """
    t0 = time.monotonic()
    current_hash = _hash_docs(schema_docs)
    last_hash = _load_state(state_file)
    tables_found = len(list(schema_docs.glob("*.md")))

    if current_hash == last_hash:
        duration_ms = int((time.monotonic() - t0) * 1000)
        _log_refresh(refresh_log, "skipped", tables_found, duration_ms)
        return "skipped"

    build_index(schema_docs_path=schema_docs, chroma_path=chroma_path)
    _save_state(state_file, current_hash)
    duration_ms = int((time.monotonic() - t0) * 1000)
    _log_refresh(refresh_log, "reindexed", tables_found, duration_ms)
    return "reindexed"


def run_scheduler(
    interval_seconds: int = 120,
    schema_docs: Path = SCHEMA_DOCS,
    chroma_path: Path = CHROMA_PATH,
) -> None:
    """Loop forever, running a refresh cycle every interval_seconds. Ctrl-C to stop."""
    print(f"Refresh scheduler started — interval={interval_seconds}s. Ctrl-C to stop.")
    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        action = run_refresh_cycle(schema_docs, chroma_path)
        print(f"[{ts}] {action}")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Schema doc refresh scheduler")
    parser.add_argument(
        "--interval", type=int, default=120,
        help="Seconds between refresh cycles (demo mode). Default: 120.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Run exactly one refresh cycle and exit (for Windows Task Scheduler).",
    )
    args = parser.parse_args()

    if args.once:
        action = run_refresh_cycle()
        print(f"Refresh cycle complete: {action}")
    else:
        run_scheduler(interval_seconds=args.interval)
