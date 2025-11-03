# Deprecated Scripts

This directory contains scripts that have been deprecated due to incompatibility with the new S3 structure or being superseded by better alternatives.

## Deprecated Scripts

### 1. compare_runs.sh (Deprecated: 2025-10-30)
**Issue**: Uses obsolete S3 structure and non-existent `latest.json` files

**Old S3 Structure**:
```
s3://e6-jmeter/jmeter-results/latest.json
```

**Replacement**: Use `utilities/compare_s3_runs.sh --list`
```bash
# Old way (broken):
./utilities/compare_runs.sh tpcds_29_1tb sequential

# New way:
./utilities/compare_s3_runs.sh --list \
  --engine e6data \
  --cluster-size XS \
  --benchmark tpcds_29_1tb \
  --run-type sequential
```

### 2. compare_jmeter_runs.sh (Deprecated: 2025-10-30)
**Issue**: Uses obsolete S3 path structure `run_date=$DATE/run_id=$ID`

**Old S3 Structure**:
```
s3://e6-jmeter/jmeter-results/run_date=20251029/run_id=20251029-083259/
```

**New S3 Structure** (since 2025-10-29):
```
s3://e6-jmeter/jmeter-results/engine=$ENGINE/cluster_size=$SIZE/benchmark=$BENCHMARK/run_type=$TYPE/
```

**Replacement**: Use `utilities/compare_s3_runs.sh --run-id`
```bash
# Old way (broken):
./utilities/compare_jmeter_runs.sh 20251029-083259 20251029-084324

# New way:
./utilities/compare_s3_runs.sh --run-id \
  --id1 20251029-083259 \
  --id2 20251029-084324
```

## Why These Scripts Were Deprecated

On 2025-10-29, the S3 upload structure was changed from a flat `run_date=/run_id=` hierarchy to a 4-level partitioned structure: `engine=/cluster_size=/benchmark=/run_type=`. This enables:

1. **Better organization**: Runs are grouped by their characteristics
2. **Easier filtering**: Query by engine, cluster size, benchmark, or run type
3. **Athena compatibility**: Partitioned structure works better with AWS Athena queries
4. **Performance**: Faster S3 listings and filtering

The deprecated scripts hardcode the old path structure and cannot work with the new organization.

## Current/Modern Scripts

Use these instead:

| Purpose | Script | Description |
|---------|--------|-------------|
| **S3 Comparisons** | `utilities/compare_s3_runs.sh` | Compare runs from S3 with 4 modes |
| **Detailed Analysis** | `utilities/compare_query_detailed.py` | Comprehensive query-by-query comparison |
| **Direct JSON** | `utilities/compare_jmeter_runs.py` | Compare local JSON files directly |

## Migration Examples

### Example 1: List Available Runs
```bash
# Old (broken):
./utilities/compare_runs.sh tpcds_29_1tb sequential

# New:
./utilities/compare_s3_runs.sh --list \
  --engine e6data \
  --cluster-size XS \
  --benchmark tpcds_29_1tb \
  --run-type sequential
```

### Example 2: Compare Two Specific Runs
```bash
# Old (broken):
./utilities/compare_jmeter_runs.sh 20251029-083259 20251029-084324

# New:
./utilities/compare_s3_runs.sh --run-id \
  --id1 20251029-083259 \
  --id2 20251029-084324
```

### Example 3: Compare Latest Runs
```bash
# New feature (no old equivalent):
./utilities/compare_s3_runs.sh --latest \
  --engine1 e6data \
  --engine2 databricks \
  --cluster-size XS \
  --benchmark tpcds_29_1tb \
  --run-type sequential
```

### Example 4: Compare Best Runs
```bash
# New feature (no old equivalent):
./utilities/compare_s3_runs.sh --best \
  --engine1 e6data \
  --engine2 databricks \
  --cluster-size XS \
  --benchmark tpcds_29_1tb \
  --run-type sequential \
  --tag run-1
```

## Deletion Schedule

These scripts will remain in this deprecated/ directory for reference until:
- 2025-12-31 (2 months grace period)
- After confirming no dependencies in other scripts/pipelines

If you need to use these scripts before deletion, please migrate to the new structure as soon as possible.
