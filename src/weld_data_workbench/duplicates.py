from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps

from .config import AppConfig
from .index.database import connect_database
from .io.paths import safe_join

NEAR_DUPLICATE_SCHEMA_VERSION = 1
SIGNATURE_CACHE_SCHEMA_VERSION = 1
_IMAGE_ALGORITHM = "dhash64"
_VIDEO_ALGORITHM = "three-frame-dhash192"
_ALGORITHM_VERSION = "1"


@dataclass(frozen=True, slots=True)
class MediaSignature:
    asset_id: str
    sample_id: str
    session_id: str | None
    split: str | None
    kind: str
    ordinal: int
    relpath: str
    value: int
    bits: int


@dataclass(frozen=True, slots=True)
class SignatureFailure:
    asset_id: str
    sample_id: str
    kind: str
    relpath: str
    error: str


@dataclass(frozen=True, slots=True)
class NearDuplicateSummary:
    assets_considered: int
    signatures_computed: int
    signatures_reused: int
    signature_failures: int
    candidate_pairs: int
    strong_pairs: int
    medium_pairs: int
    weak_pairs: int
    candidate_limit_reached: bool


@dataclass(frozen=True, slots=True)
class NearDuplicateReport:
    schema_version: int
    generated_at: str
    parameters: dict[str, Any]
    summary: NearDuplicateSummary
    pairs: list[dict[str, Any]]
    failures: list[SignatureFailure]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "parameters": self.parameters,
            "summary": asdict(self.summary),
            "pairs": self.pairs,
            "failures": [asdict(item) for item in self.failures],
        }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _dhash_gray(gray: np.ndarray) -> int:
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = resized[:, 1:] > resized[:, :-1]
    packed = np.packbits(bits.reshape(-1).astype(np.uint8), bitorder="big")
    return int.from_bytes(packed.tobytes(), "big")


def _image_signature(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("L")
        gray = np.asarray(image, dtype=np.uint8)
    return _dhash_gray(gray), 64


def _video_signature(path: Path) -> tuple[int, int]:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("OpenCV could not open video")
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if frame_count < 3:
            raise ValueError("video has too few indexed frames for signature")
        positions = (
            max(0, round((frame_count - 1) * 0.25)),
            max(0, round((frame_count - 1) * 0.50)),
            max(0, round((frame_count - 1) * 0.75)),
        )
        values: list[int] = []
        for frame_index in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError(f"could not decode signature frame {frame_index}")
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            values.append(_dhash_gray(gray))
        value = (values[0] << 128) | (values[1] << 64) | values[2]
        return value, 192
    finally:
        capture.release()


def _signature_algorithm(kind: str) -> str:
    if kind == "image":
        return _IMAGE_ALGORITHM
    if kind == "video":
        return _VIDEO_ALGORITHM
    raise ValueError(f"Unsupported perceptual-signature kind: {kind}")


def _compute_signature(path: Path, kind: str) -> tuple[int, int]:
    if kind == "image":
        return _image_signature(path)
    if kind == "video":
        return _video_signature(path)
    raise ValueError(f"Unsupported perceptual-signature kind: {kind}")


class SignatureCache:
    """Workspace-local cache for bounded perceptual media signatures."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signatures (
                    asset_id TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    algorithm_version TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    bits INTEGER,
                    value_hex TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(asset_id, algorithm, algorithm_version)
                );
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SIGNATURE_CACHE_SCHEMA_VERSION),),
            )

    def get(
        self,
        *,
        asset_id: str,
        algorithm: str,
        size_bytes: int,
        mtime_ns: int,
    ) -> tuple[str, int | None, int | None, str | None] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status,bits,value_hex,error,size_bytes,mtime_ns
                FROM signatures
                WHERE asset_id=? AND algorithm=? AND algorithm_version=?
                """,
                (asset_id, algorithm, _ALGORITHM_VERSION),
            ).fetchone()
        if row is None:
            return None
        if int(row["size_bytes"]) != size_bytes or int(row["mtime_ns"]) != mtime_ns:
            return None
        value = int(str(row["value_hex"]), 16) if row["value_hex"] else None
        bits = int(row["bits"]) if row["bits"] is not None else None
        error = str(row["error"]) if row["error"] is not None else None
        return str(row["status"]), value, bits, error

    def put_success(
        self,
        *,
        asset_id: str,
        algorithm: str,
        size_bytes: int,
        mtime_ns: int,
        value: int,
        bits: int,
    ) -> None:
        width = (bits + 3) // 4
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO signatures(
                    asset_id,algorithm,algorithm_version,size_bytes,mtime_ns,
                    bits,value_hex,status,error,updated_at
                ) VALUES(?,?,?,?,?,?,?,'success',NULL,?)
                ON CONFLICT(asset_id,algorithm,algorithm_version) DO UPDATE SET
                    size_bytes=excluded.size_bytes,
                    mtime_ns=excluded.mtime_ns,
                    bits=excluded.bits,
                    value_hex=excluded.value_hex,
                    status='success',
                    error=NULL,
                    updated_at=excluded.updated_at
                """,
                (
                    asset_id,
                    algorithm,
                    _ALGORITHM_VERSION,
                    size_bytes,
                    mtime_ns,
                    f"{value:0{width}x}",
                    _utc_now(),
                ),
            )

    def put_failure(
        self,
        *,
        asset_id: str,
        algorithm: str,
        size_bytes: int,
        mtime_ns: int,
        error: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO signatures(
                    asset_id,algorithm,algorithm_version,size_bytes,mtime_ns,
                    bits,value_hex,status,error,updated_at
                ) VALUES(?,?,?,?,?,NULL,NULL,'failed',?,?)
                ON CONFLICT(asset_id,algorithm,algorithm_version) DO UPDATE SET
                    size_bytes=excluded.size_bytes,
                    mtime_ns=excluded.mtime_ns,
                    bits=NULL,
                    value_hex=NULL,
                    status='failed',
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    asset_id,
                    algorithm,
                    _ALGORITHM_VERSION,
                    size_bytes,
                    mtime_ns,
                    error,
                    _utc_now(),
                ),
            )


@dataclass(slots=True)
class _BKNode:
    value: int
    members: list[MediaSignature]
    children: dict[int, _BKNode]


class _BKTree:
    def __init__(self) -> None:
        self.root: _BKNode | None = None

    def add(self, signature: MediaSignature) -> None:
        if self.root is None:
            self.root = _BKNode(signature.value, [signature], {})
            return
        node = self.root
        while True:
            distance = (signature.value ^ node.value).bit_count()
            if distance == 0:
                node.members.append(signature)
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BKNode(signature.value, [signature], {})
                return
            node = child

    def query(self, value: int, max_distance: int) -> list[tuple[int, MediaSignature]]:
        if self.root is None:
            return []
        result: list[tuple[int, MediaSignature]] = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            distance = (value ^ node.value).bit_count()
            if distance <= max_distance:
                result.extend((distance, member) for member in node.members)
            low = distance - max_distance
            high = distance + max_distance
            stack.extend(child for edge, child in node.children.items() if low <= edge <= high)
        return result


def _indexed_media_rows(config: AppConfig, kinds: tuple[str, ...]) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in kinds)
    sql = f"""
        SELECT
            a.asset_id,a.sample_id,a.kind,a.ordinal,a.relpath,a.size_bytes,a.mtime_ns,
            s.session_id,s.split
        FROM assets a
        JOIN samples s ON s.sample_id=a.sample_id
        WHERE a.kind IN ({placeholders}) AND a.status != 'error'
        ORDER BY a.kind,a.ordinal,a.sample_id,a.relpath
    """
    with connect_database(config.index_path, read_only=True) as connection:
        return connection.execute(sql, kinds).fetchall()


def _load_signatures(
    config: AppConfig,
    *,
    kinds: tuple[str, ...],
    cache: SignatureCache,
) -> tuple[list[MediaSignature], list[SignatureFailure], int, int, int]:
    rows = _indexed_media_rows(config, kinds)
    signatures: list[MediaSignature] = []
    failures: list[SignatureFailure] = []
    computed = 0
    reused = 0
    for row in rows:
        asset_id = str(row["asset_id"])
        sample_id = str(row["sample_id"])
        kind = str(row["kind"])
        relpath = str(row["relpath"])
        algorithm = _signature_algorithm(kind)
        try:
            path = safe_join(config.dataset_root, relpath)
            stat = path.stat()
            size_bytes = int(stat.st_size)
            mtime_ns = int(stat.st_mtime_ns)
        except (OSError, ValueError) as exc:
            failures.append(
                SignatureFailure(asset_id, sample_id, kind, relpath, f"{type(exc).__name__}: {exc}")
            )
            continue

        cached = cache.get(
            asset_id=asset_id,
            algorithm=algorithm,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
        )
        if cached is not None:
            status, value, bits, error = cached
            reused += 1
            if status == "success" and value is not None and bits is not None:
                signatures.append(
                    MediaSignature(
                        asset_id=asset_id,
                        sample_id=sample_id,
                        session_id=str(row["session_id"])
                        if row["session_id"] is not None
                        else None,
                        split=str(row["split"]) if row["split"] is not None else None,
                        kind=kind,
                        ordinal=int(row["ordinal"]),
                        relpath=relpath,
                        value=value,
                        bits=bits,
                    )
                )
            else:
                failures.append(
                    SignatureFailure(asset_id, sample_id, kind, relpath, error or "cached failure")
                )
            continue

        try:
            value, bits = _compute_signature(path, kind)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            cache.put_failure(
                asset_id=asset_id,
                algorithm=algorithm,
                size_bytes=size_bytes,
                mtime_ns=mtime_ns,
                error=error,
            )
            failures.append(SignatureFailure(asset_id, sample_id, kind, relpath, error))
            computed += 1
            continue

        cache.put_success(
            asset_id=asset_id,
            algorithm=algorithm,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            value=value,
            bits=bits,
        )
        computed += 1
        signatures.append(
            MediaSignature(
                asset_id=asset_id,
                sample_id=sample_id,
                session_id=str(row["session_id"]) if row["session_id"] is not None else None,
                split=str(row["split"]) if row["split"] is not None else None,
                kind=kind,
                ordinal=int(row["ordinal"]),
                relpath=relpath,
                value=value,
                bits=bits,
            )
        )
    return signatures, failures, len(rows), computed, reused


def _pair_quality(evidence: list[dict[str, Any]]) -> str:
    image_matches = sum(item["kind"] == "image" for item in evidence)
    video_matches = sum(item["kind"] == "video" for item in evidence)
    if image_matches >= 3 or (image_matches >= 1 and video_matches >= 1):
        return "strong"
    if image_matches >= 2 or video_matches >= 1:
        return "medium"
    return "weak"


def scan_near_duplicates(
    config: AppConfig,
    *,
    kinds: tuple[str, ...] = ("image", "video"),
    image_distance: int = 4,
    video_distance: int = 12,
    cross_split_only: bool = True,
    max_pairs: int = 10_000,
    max_matches_per_asset: int = 100,
) -> NearDuplicateReport:
    """Find bounded perceptual near-duplicate candidates without an O(N²) scan.

    The report is deliberately phrased as *candidate* pairs. Perceptual hashes are
    useful for leakage triage but are not physical-weld identity proof. Images are
    compared only against the same ordinal; video signatures use three bounded
    frames. BK trees provide Hamming-radius lookup and the workspace cache avoids
    repeatedly decoding unchanged media on subsequent audits.
    """

    normalized_kinds = tuple(dict.fromkeys(kind.casefold() for kind in kinds))
    if not normalized_kinds or any(kind not in {"image", "video"} for kind in normalized_kinds):
        raise ValueError("kinds must contain image and/or video")
    if image_distance < 0 or image_distance > 64:
        raise ValueError("image_distance must be between 0 and 64")
    if video_distance < 0 or video_distance > 192:
        raise ValueError("video_distance must be between 0 and 192")
    if max_pairs < 1 or max_matches_per_asset < 1:
        raise ValueError("candidate limits must be positive")

    cache = SignatureCache(config.features_dir / "near_duplicate_signatures.sqlite3")
    signatures, failures, considered, computed, reused = _load_signatures(
        config,
        kinds=normalized_kinds,
        cache=cache,
    )

    trees: dict[tuple[str, int], _BKTree] = defaultdict(_BKTree)
    pair_evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    pair_meta: dict[tuple[str, str], dict[str, Any]] = {}
    limit_reached = False

    for signature in signatures:
        bucket = (signature.kind, signature.ordinal if signature.kind == "image" else 0)
        tree = trees[bucket]
        radius = image_distance if signature.kind == "image" else video_distance
        matches = tree.query(signature.value, radius)
        if len(matches) > max_matches_per_asset:
            matches = sorted(matches, key=lambda item: item[0])[:max_matches_per_asset]
        for distance, other in matches:
            if signature.sample_id == other.sample_id:
                continue
            if cross_split_only and (
                signature.split is None or other.split is None or signature.split == other.split
            ):
                continue
            sample_a, sample_b = sorted((signature.sample_id, other.sample_id))
            key = (sample_a, sample_b)
            if key not in pair_evidence and len(pair_evidence) >= max_pairs:
                limit_reached = True
                continue

            if sample_a == signature.sample_id:
                left, right = signature, other
            else:
                left, right = other, signature
            pair_meta[key] = {
                "sample_a": sample_a,
                "sample_b": sample_b,
                "session_a": left.session_id,
                "session_b": right.session_id,
                "split_a": left.split,
                "split_b": right.split,
            }
            pair_evidence[key].append(
                {
                    "kind": signature.kind,
                    "ordinal": signature.ordinal,
                    "asset_a": left.asset_id,
                    "asset_b": right.asset_id,
                    "relpath_a": left.relpath,
                    "relpath_b": right.relpath,
                    "hamming_distance": distance,
                    "signature_bits": signature.bits,
                    "normalized_distance": float(distance / signature.bits),
                }
            )
        tree.add(signature)

    pairs: list[dict[str, Any]] = []
    quality_counts = {"strong": 0, "medium": 0, "weak": 0}
    for key, evidence in pair_evidence.items():
        evidence.sort(key=lambda item: (item["kind"], item["ordinal"], item["hamming_distance"]))
        quality = _pair_quality(evidence)
        quality_counts[quality] += 1
        row = dict(pair_meta[key])
        row.update(
            {
                "quality": quality,
                "image_matches": sum(item["kind"] == "image" for item in evidence),
                "video_matches": sum(item["kind"] == "video" for item in evidence),
                "best_normalized_distance": min(item["normalized_distance"] for item in evidence),
                "evidence": evidence,
            }
        )
        pairs.append(row)
    quality_rank = {"strong": 0, "medium": 1, "weak": 2}
    pairs.sort(
        key=lambda row: (
            quality_rank[str(row["quality"])],
            float(row["best_normalized_distance"]),
            str(row["sample_a"]),
            str(row["sample_b"]),
        )
    )

    return NearDuplicateReport(
        schema_version=NEAR_DUPLICATE_SCHEMA_VERSION,
        generated_at=_utc_now(),
        parameters={
            "kinds": list(normalized_kinds),
            "image_distance": image_distance,
            "video_distance": video_distance,
            "cross_split_only": cross_split_only,
            "max_pairs": max_pairs,
            "max_matches_per_asset": max_matches_per_asset,
            "signature_cache": str(cache.path),
        },
        summary=NearDuplicateSummary(
            assets_considered=considered,
            signatures_computed=computed,
            signatures_reused=reused,
            signature_failures=len(failures),
            candidate_pairs=len(pairs),
            strong_pairs=quality_counts["strong"],
            medium_pairs=quality_counts["medium"],
            weak_pairs=quality_counts["weak"],
            candidate_limit_reached=limit_reached,
        ),
        pairs=pairs,
        failures=failures,
    )


def write_near_duplicate_report(report: NearDuplicateReport, output: Path) -> Path:
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
