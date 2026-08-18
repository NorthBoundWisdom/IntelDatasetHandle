from __future__ import annotations

SCHEMA_VERSION = 1
CONFIG_FILENAME = "workbench.yaml"
DEFAULT_INDEX_FILENAME = "index.sqlite3"

EXPECTED_MANIFEST_COLUMNS = {
    "CATEGORY",
    "WELD_TYPE",
    "THICKNESS_MM",
    "STEEL_TYPE",
    "SAMPLES",
    "CURRENT_A",
    "VOLTAGE_V",
    "GAS_BAR",
    "ROBOT_SPEED_CPM",
    "DIRECTORY",
    "SUBDIRS",
    "SPLIT",
}

KNOWN_SPLITS = {"train", "training", "val", "valid", "validation", "test", "testing"}

VIDEO_EXTENSIONS = {".avi", ".mp4", ".mov", ".mkv", ".m4v"}
AUDIO_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif", ".ogg"}
SENSOR_EXTENSIONS = {".csv", ".tsv", ".txt"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

DEFAULT_MANIFEST_PREFERRED_NAMES = (
    "manifest.csv",
    "dataset_manifest.csv",
    "annotations.csv",
    "metadata.csv",
)
