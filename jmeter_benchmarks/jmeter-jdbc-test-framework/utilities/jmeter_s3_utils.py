#!/usr/bin/env python3
"""
Utility functions for JMeter S3 operations and metadata parsing.

This module provides reusable functions for:
- Parsing S3 paths to extract metadata
- Downloading JMeter result files from S3
- Loading and parsing statistics.json files
- Extracting run information
"""

import re
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime


class JMeterS3Path:
    """Parse and validate JMeter S3 result paths."""

    # Support two formats:
    # 1. s3://bucket/.../engine=X/cluster_size=Y/benchmark=Z/run_type=W/
    # 2. s3://bucket/.../engine=X/cluster_size=Y/benchmark=Z/concurrency_N/
    PATH_PATTERN_WITH_RUN_TYPE = re.compile(
        r's3://(?P<bucket>[^/]+)/(?P<prefix>.*?)/engine=(?P<engine>[^/]+)/'
        r'cluster_size=(?P<cluster_size>[^/]+)/benchmark=(?P<benchmark>[^/]+)/'
        r'run_type=(?P<run_type>[^/]+)/?'
    )
    PATH_PATTERN_DIRECT = re.compile(
        r's3://(?P<bucket>[^/]+)/(?P<prefix>.*?)/engine=(?P<engine>[^/]+)/'
        r'cluster_size=(?P<cluster_size>[^/]+)/benchmark=(?P<benchmark>[^/]+)/'
        r'(?P<run_type>(?:concurrency_\d+|sequential))/?'
    )

    def __init__(self, s3_path: str):
        """Initialize and parse S3 path."""
        self.raw_path = s3_path.rstrip('/')
        self.metadata = self._parse_path()

    def _parse_path(self) -> Dict[str, str]:
        """Parse S3 path and extract metadata."""
        # Try run_type= format first
        match = self.PATH_PATTERN_WITH_RUN_TYPE.match(self.raw_path)
        if not match:
            # Try direct concurrency_X format
            match = self.PATH_PATTERN_DIRECT.match(self.raw_path)

        if not match:
            raise ValueError(f"Invalid S3 path format: {self.raw_path}")

        metadata = match.groupdict()

        # Parse run_type to extract concurrency or sequential info
        run_type = metadata['run_type']
        if run_type.startswith('concurrency_'):
            metadata['concurrency'] = int(run_type.split('_')[1])
            metadata['is_sequential'] = False
        elif run_type == 'sequential':
            metadata['concurrency'] = 1
            metadata['is_sequential'] = True
        else:
            metadata['concurrency'] = None
            metadata['is_sequential'] = None

        return metadata

    @property
    def engine(self) -> str:
        """Get engine name (e6data, databricks, etc.)."""
        return self.metadata['engine']

    @property
    def cluster_size(self) -> str:
        """Get cluster size (XS, S-2x2, M, S-4x4, etc.)."""
        return self.metadata['cluster_size']

    @property
    def benchmark(self) -> str:
        """Get benchmark name (tpcds_29_1tb, etc.)."""
        return self.metadata['benchmark']

    @property
    def run_type(self) -> str:
        """Get run type (concurrency_2, sequential, etc.)."""
        return self.metadata['run_type']

    @property
    def concurrency(self) -> Optional[int]:
        """Get concurrency level (None if not applicable)."""
        return self.metadata.get('concurrency')

    @property
    def is_sequential(self) -> Optional[bool]:
        """Check if this is a sequential run."""
        return self.metadata.get('is_sequential')

    def get_cores(self) -> int:
        """Calculate total cores based on cluster size."""
        cluster_map = {
            'XS': 30,
            'S-2x2': 60,
            'M': 120,
            'S-4x4': 120,
            'L': 240,
        }
        return cluster_map.get(self.cluster_size, 0)

    def __str__(self) -> str:
        """String representation."""
        return f"{self.engine} {self.cluster_size} ({self.run_type})"


def list_s3_files(s3_path: str, pattern: str = "") -> list:
    """List files in S3 path matching optional pattern."""
    s3_path = s3_path.rstrip('/') + '/'
    cmd = ['aws', 's3', 'ls', s3_path, '--recursive']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split(None, 3)
                if len(parts) == 4:
                    filename = parts[3]
                    if pattern in filename:
                        files.append(filename)
        return files
    except subprocess.CalledProcessError as e:
        print(f"Error listing S3 files: {e.stderr}")
        return []


def download_s3_file(s3_path: str, filename: str, local_dir: Path) -> Optional[Path]:
    """Download a specific file from S3 path."""
    s3_path = s3_path.rstrip('/') + '/'

    # Handle both full S3 URIs and just the path component
    if not s3_path.startswith('s3://'):
        s3_path = 's3://' + s3_path

    s3_file = f"{s3_path}{filename}"
    local_file = local_dir / filename

    cmd = ['aws', 's3', 'cp', s3_file, str(local_file)]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return local_file
    except subprocess.CalledProcessError as e:
        print(f"Warning: Could not download {s3_file}: {e.stderr}")
        return None


def find_latest_file(s3_path: str, pattern: str) -> Optional[str]:
    """Find the latest file matching pattern in S3 path."""
    files = list_s3_files(s3_path, pattern)
    if not files:
        return None

    # Sort by filename (assumes timestamp in filename)
    files.sort(reverse=True)
    return files[0]


def download_jmeter_statistics(s3_path: str, local_dir: Path) -> Optional[Path]:
    """
    Download statistics.json file from S3 path.

    Returns path to downloaded file, or None if not found.
    """
    local_dir.mkdir(parents=True, exist_ok=True)

    # Find latest statistics file
    latest_stats = find_latest_file(s3_path, 'statistics')

    if latest_stats:
        # Extract just the filename
        filename = latest_stats.split('/')[-1]
        return download_s3_file(s3_path, filename, local_dir)

    return None


def load_jmeter_statistics(stats_file: Path) -> Dict:
    """Load and parse JMeter statistics.json file."""
    with open(stats_file, 'r') as f:
        return json.load(f)


def load_statistics_from_s3(s3_file_path: str) -> Optional[Dict]:
    """
    Load statistics.json directly from S3 without downloading to disk.

    Args:
        s3_file_path: Full S3 path to statistics file (e.g., s3://bucket/path/to/statistics_*.json)
                      or just the path component (bucket/path/to/statistics_*.json)

    Returns:
        Dictionary with statistics data, or None if error
    """
    # Ensure s3:// prefix
    if not s3_file_path.startswith('s3://'):
        s3_file_path = 's3://' + s3_file_path

    cmd = ['aws', 's3', 'cp', s3_file_path, '-']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error loading {s3_file_path}: {e.stderr}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from {s3_file_path}: {e}")
        return None


def extract_query_metrics(stats: Dict, query_name: str) -> Optional[Dict]:
    """
    Extract metrics for a specific query from statistics.json.

    Returns dict with: avg, median, p90, p95, p99, min, max (all in seconds)
    """
    if query_name not in stats:
        return None

    metrics = stats[query_name]

    return {
        'avg': metrics['meanResTime'] / 1000.0,
        'median': metrics['medianResTime'] / 1000.0,
        'p90': metrics['pct1ResTime'] / 1000.0,
        'p95': metrics['pct2ResTime'] / 1000.0,
        'p99': metrics['pct3ResTime'] / 1000.0,
        'min': metrics['minResTime'] / 1000.0,
        'max': metrics['maxResTime'] / 1000.0,
        'error_pct': metrics['errorPct'],
        'samples': metrics['sampleCount'],
    }


def get_all_query_names(stats1: Dict, stats2: Dict) -> set:
    """Get union of all query names from two statistics dicts."""
    queries1 = {k for k in stats1.keys() if k != 'Total'}
    queries2 = {k for k in stats2.keys() if k != 'Total'}
    return queries1.union(queries2)


def calculate_percentage_diff(val1: float, val2: float) -> float:
    """
    Calculate percentage difference.

    Positive value means val1 is faster (val2 is slower).
    """
    if val2 == 0:
        return 0.0
    return ((val2 - val1) / val2) * 100.0


def format_percentage(pct: float, show_sign: bool = True) -> str:
    """Format percentage with appropriate sign and color indicators."""
    if show_sign:
        sign = '+' if pct > 0 else ''
        return f"{sign}{pct:.1f}%"
    return f"{pct:.1f}%"


def get_timestamp() -> str:
    """Get current timestamp for report filenames."""
    return datetime.now().strftime('%Y%m%d')


def normalize_query_name(query_name: str, source_engine: str) -> str:
    """
    Normalize query names between different engines.

    E6Data format: query-2-TPCDS-2
    Databricks format: TPCDS-2
    """
    # If already in TPCDS-X format, return as-is
    if query_name.startswith('TPCDS-'):
        return query_name

    # If in E6Data format (query-X-TPCDS-Y), extract TPCDS-Y
    if source_engine == 'e6data' and query_name.startswith('query-'):
        parts = query_name.split('-')
        # Find TPCDS part
        for i, part in enumerate(parts):
            if part == 'TPCDS' and i + 1 < len(parts):
                return f"TPCDS-{parts[i+1]}"

    return query_name


def create_query_mapping(stats1: Dict, stats2: Dict, engine1: str, engine2: str) -> Dict[str, Tuple[str, str]]:
    """
    Create mapping between query names in two different engines.

    Returns dict: normalized_name -> (query_name_in_stats1, query_name_in_stats2)
    """
    mapping = {}

    # Get all queries from both stats
    queries1 = {k for k in stats1.keys() if k != 'Total'}
    queries2 = {k for k in stats2.keys() if k != 'Total'}

    # Normalize and map
    for q1 in queries1:
        normalized = normalize_query_name(q1, engine1)
        if normalized not in mapping:
            mapping[normalized] = [None, None]
        mapping[normalized][0] = q1

    for q2 in queries2:
        normalized = normalize_query_name(q2, engine2)
        if normalized not in mapping:
            mapping[normalized] = [None, None]
        mapping[normalized][1] = q2

    # Convert lists to tuples and filter out incomplete mappings
    return {k: tuple(v) for k, v in mapping.items() if all(v)}


if __name__ == '__main__':
    # Test S3 path parsing
    test_path = "s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_2/"

    try:
        parsed = JMeterS3Path(test_path)
        print(f"Path: {test_path}")
        print(f"Engine: {parsed.engine}")
        print(f"Cluster: {parsed.cluster_size}")
        print(f"Benchmark: {parsed.benchmark}")
        print(f"Run Type: {parsed.run_type}")
        print(f"Concurrency: {parsed.concurrency}")
        print(f"Cores: {parsed.get_cores()}")
        print(f"String: {parsed}")
    except ValueError as e:
        print(f"Error: {e}")
