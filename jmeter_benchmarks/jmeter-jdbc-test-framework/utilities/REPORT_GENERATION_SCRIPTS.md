# JMeter Report Generation Scripts

Comprehensive guide to all report generation utilities for analyzing JMeter test results.

**Last Updated**: October 31, 2025

---

## Overview

All scripts are located in `utilities/` directory and designed for analyzing JMeter JDBC performance test results.

| Script | Data Source | Comparison Type | Output Format |
|--------|-------------|-----------------|---------------|
| `compare_consecutive_runs_from_s3.py` | S3 | Same engine, 2 runs | MD (with query details) |
| `compare_multi_concurrency_from_s3.py` | S3 | 2 engines, all concurrency | CSV + MD |
| `compare_jmeter_runs_from_s3.py` | S3 | 2 engines, 1 concurrency | CSV + MD |
| `analyze_concurrency_scaling_from_s3.py` | S3 | Single engine scaling | MD |
| `analyze_aggregate_report.py` | Local | Single run analysis | Console |

---

## 1. compare_consecutive_runs_from_s3.py

**Purpose**: Compare two consecutive runs of the same engine/cluster/benchmark to detect regressions or improvements.

**Use Cases**:
- Regression testing (did new changes improve/degrade performance?)
- Cold start detection (compare warm vs cold cluster)
- Performance tracking over time
- Validate optimizations

**Features**:
✅ **Query-by-query comparison** - See which specific queries improved/degraded
✅ **Auto-detect latest 2 runs** - No need to specify run IDs
✅ **Manual run ID selection** - Compare specific runs if needed
✅ **Run IDs in filename** - Clear traceability

**Usage**:

```bash
# Automatic mode - compares 2 most recent runs
python utilities/compare_consecutive_runs_from_s3.py \
    --base-path s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Specific run IDs
python utilities/compare_consecutive_runs_from_s3.py \
    --base-path s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    --run-id1 20251030-171659 \
    --run-id2 20251031-070614
```

**Output**:
```
reports/e6data_S-2x2_ConsecutiveRuns_20251030-171659_vs_20251031-070614.md
```

**Report Contents**:
- Performance changes by concurrency level (summary table)
- Detailed metrics per concurrency (avg, median, p90, p95, p99)
- **Query-by-query comparison** showing individual query changes
- Overall verdict (improved/degraded/stable)

**Requirements**:
- At least 2 runs for each concurrency level
- Same engine, cluster, and benchmark

---

## 2. compare_multi_concurrency_from_s3.py

**Purpose**: Compare two different engines/clusters across ALL concurrency levels.

**Use Cases**:
- Engine comparison (E6Data vs Databricks)
- Cluster sizing (S-2x2 vs M vs S-4x4)
- Architecture comparison (60 cores vs 120 cores)
- Comprehensive benchmarking

**Features**:
✅ **Auto-discovers all concurrency levels** (C=2,4,8,12,16)
✅ **Cross-engine query mapping** (handles different query naming)
✅ **Multi-concurrency analysis** (see scaling behavior)
✅ **Executive summary** with recommendations

**Usage**:

```bash
# Compare E6Data vs Databricks
python utilities/compare_multi_concurrency_from_s3.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/

# Compare different cluster sizes (same engine)
python utilities/compare_multi_concurrency_from_s3.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/
```

**Output**:
```
reports/e6data_S-2x2_vs_databricks_S-4x4_MultiConcurrency_20251031.csv
reports/e6data_S-2x2_vs_databricks_S-4x4_MultiConcurrency_20251031_SUMMARY.md
```

**Report Contents**:
- **CSV**: Detailed query-by-query comparison across all concurrency levels
- **Summary MD**: Executive summary with performance by concurrency level
- Winner determination (which engine/cluster wins)
- Recommendations for production use

**Requirements**:
- At least 1 run per concurrency level for both engines
- Uses most recent run if multiple exist

---

## 3. compare_jmeter_runs_from_s3.py

**Purpose**: Deep-dive comparison of two engines at a SINGLE concurrency level.

**Use Cases**:
- Focus on specific concurrency level
- Quick spot-check comparison
- Detailed analysis of one scenario

**Features**:
✅ **Single concurrency deep-dive**
✅ **Query-by-query details**
✅ **Faster execution** (only one concurrency level)

**Usage**:

```bash
python utilities/compare_jmeter_runs_from_s3.py \
    s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/run_type=concurrency_8/ \
    s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_8/
```

**Output**:
```
reports/e6data_S-2x2_vs_databricks_S-4x4_C8_20251031.csv
reports/e6data_S-2x2_vs_databricks_S-4x4_C8_20251031_SUMMARY.md
```

**Report Contents**:
- Query-by-query comparison for single concurrency level
- Aggregate statistics
- Performance differences

**Note**: This is a **subset** of `compare_multi_concurrency_from_s3.py` but faster for single-concurrency analysis.

---

## 4. analyze_concurrency_scaling_from_s3.py

**Purpose**: Analyze how a SINGLE engine scales as concurrency increases.

**Use Cases**:
- Identify safe concurrency limits
- Understand scaling behavior
- Detect bottlenecks
- Capacity planning

**Features**:
✅ **Scaling efficiency metrics** (how well engine handles increased load)
✅ **Degradation analysis** (performance loss at each level)
✅ **Trend detection** (improving/degrading/stable)
✅ **Production readiness assessment**

**Usage**:

```bash
# Analyze E6Data scaling behavior
python utilities/analyze_concurrency_scaling_from_s3.py \
    --base-path s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Analyze Databricks scaling behavior
python utilities/analyze_concurrency_scaling_from_s3.py \
    --base-path s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

**Output**:
```
reports/e6data_S-2x2_ConcurrencyScaling_20251031_ANALYSIS.md
```

**Report Contents**:
- Performance by concurrency level table
- Overall scaling analysis (baseline to max concurrency)
- Performance trend (showing degradation at each step)
- **Scaling efficiency** calculations
- Recommendations (safe production limits)

**Scaling Metrics Explained**:
- **Degradation**: How much slower compared to baseline (C=2)
- **Scaling Efficiency**: Ratio of concurrency increase to latency increase
  - 100% = baseline
  - >100% = super-linear (getting better!)
  - <100% = sub-linear (degrading)

---

## 5. analyze_aggregate_report.py

**Purpose**: Analyze a single local JMeter aggregate report CSV file.

**Use Cases**:
- Quick analysis of just-completed test
- Local testing without S3
- Generate percentiles from aggregate report
- Used by `run_jmeter_tests_interactive.sh` automatically

**Features**:
✅ **Local file analysis** (no S3 needed)
✅ **Percentile calculations** (p50, p90, p95, p99)
✅ **Console output** (quick results)
✅ **Auto-invoked** by interactive test script

**Usage**:

```bash
python utilities/analyze_aggregate_report.py reports/AggregateReport_20251031_123456.csv
```

**Output**:
- Console output with percentiles
- Query-by-query statistics
- Overall metrics

**Note**: This script works with **local files only**, not S3. The interactive test script (`run_jmeter_tests_interactive.sh`) calls this automatically after each test run.

---

## Decision Tree: Which Script to Use?

### Comparing Two Runs

```
Do you want to compare the same engine at different times?
├─ YES → Use compare_consecutive_runs_from_s3.py
│         - Regression testing
│         - Performance tracking
│         - Query-by-query changes
│
└─ NO → Are you comparing different engines/clusters?
    ├─ YES → Do you want all concurrency levels?
    │   ├─ YES → Use compare_multi_concurrency_from_s3.py
    │   │         - Comprehensive comparison
    │   │         - Multiple concurrency levels
    │   │
    │   └─ NO → Use compare_jmeter_runs_from_s3.py
    │            - Single concurrency level
    │            - Quick comparison
    │
    └─ NO → You want to analyze single engine behavior
        └─ Use analyze_concurrency_scaling_from_s3.py
           - Understand scaling
           - Find safe limits
```

### Analyzing Results

```
Where is your data?
├─ S3 → What do you want to know?
│   ├─ "How does this engine scale?" → analyze_concurrency_scaling_from_s3.py
│   ├─ "Did performance improve/regress?" → compare_consecutive_runs_from_s3.py
│   └─ "Which engine is better?" → compare_multi_concurrency_from_s3.py
│
└─ Local files → Use analyze_aggregate_report.py
```

---

## Common Workflows

### 1. Regression Testing After Code Changes

**Goal**: Did the new query optimization improve performance?

```bash
# Run new test with optimized queries
./run_jmeter_tests_interactive.sh

# Compare with previous run
python utilities/compare_consecutive_runs_from_s3.py \
    --base-path s3://e6-jmeter/.../engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

# Check query-by-query to see which queries improved
```

**What to look for**:
- Did BOOTSTRAP queries degrade? (might be cold start)
- Did all queries improve uniformly? (good optimization)
- Did some queries regress? (investigate those)

---

### 2. Cluster Sizing Decision

**Goal**: Is the M cluster worth the extra cost compared to S-2x2?

```bash
# Compare S-2x2 vs M cluster
python utilities/compare_multi_concurrency_from_s3.py \
    s3://e6-jmeter/.../engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    s3://e6-jmeter/.../engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/

# Analyze scaling for each cluster
python utilities/analyze_concurrency_scaling_from_s3.py \
    --base-path s3://e6-jmeter/.../engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

python utilities/analyze_concurrency_scaling_from_s3.py \
    --base-path s3://e6-jmeter/.../engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/
```

**What to look for**:
- Performance gap at your target concurrency
- Scaling efficiency at high concurrency
- Cost vs performance trade-off

---

### 3. Engine Evaluation (E6Data vs Databricks)

**Goal**: Which engine should we use for production?

```bash
# Compare across all concurrency levels
python utilities/compare_multi_concurrency_from_s3.py \
    s3://e6-jmeter/.../engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
    s3://e6-jmeter/.../engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/

# Analyze scaling for both engines
python utilities/analyze_concurrency_scaling_from_s3.py \
    --base-path s3://e6-jmeter/.../engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/

python utilities/analyze_concurrency_scaling_from_s3.py \
    --base-path s3://e6-jmeter/.../engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/
```

**What to look for**:
- Winner across different concurrency levels
- Scaling quality (which handles load better?)
- Query-by-query performance (any query types favor one engine?)

---

## Report Naming Conventions

All S3-based scripts follow consistent naming:

### Compare Scripts:
```
{engine1}_{cluster1}_vs_{engine2}_{cluster2}_{type}_{date}.{ext}

Examples:
- e6data_S-2x2_vs_databricks_S-4x4_MultiConcurrency_20251031.csv
- e6data_S-2x2_vs_databricks_S-4x4_C8_20251031.csv
```

### Consecutive Runs (NEW):
```
{engine}_{cluster}_ConsecutiveRuns_{run_id1}_vs_{run_id2}.md

Example:
- e6data_S-2x2_ConsecutiveRuns_20251030-171659_vs_20251031-070614.md
```

### Scaling Analysis:
```
{engine}_{cluster}_ConcurrencyScaling_{date}_ANALYSIS.md

Example:
- e6data_S-2x2_ConcurrencyScaling_20251031_ANALYSIS.md
```

---

## Tips and Best Practices

### 1. **Always check for cold starts** when seeing regressions
```bash
# Look at BOOTSTRAP queries in consecutive run comparison
# If BOOTSTRAP queries show massive degradation, it's likely cold start
```

### 2. **Use query-by-query analysis** to identify problematic queries
```bash
# Check the detailed comparison tables
# Look for queries with >100% degradation
# Investigate those queries specifically
```

### 3. **Compare scaling before choosing cluster size**
```bash
# Don't just look at raw performance
# Check scaling efficiency at your target concurrency
# A cluster that scales better may be worth the cost
```

### 4. **Track performance over time**
```bash
# Run compare_consecutive_runs_from_s3.py regularly
# Build a history of performance trends
# Catch regressions early
```

### 5. **List available run IDs before specific comparisons**
```bash
# See what run IDs exist
aws s3 ls s3://e6-jmeter/.../run_type=concurrency_2/ | grep statistics

# Then use those IDs in compare_consecutive_runs_from_s3.py
```

---

## Supporting Library

### jmeter_s3_utils.py

Core utility library providing:
- S3 path parsing and validation
- File listing and downloading
- Statistics loading from S3
- Query name normalization (E6Data ↔ Databricks format mapping)
- Metrics extraction

**Used by**: All S3-based comparison scripts

---

## Summary Table

| Script | Answers | S3 Data | Query Details | Multiple Concurrency | Run ID Selection |
|--------|---------|---------|---------------|---------------------|------------------|
| `compare_consecutive_runs_from_s3.py` | "Did performance change?" | ✅ | ✅ Yes | ✅ Auto | ✅ Yes (auto or manual) |
| `compare_multi_concurrency_from_s3.py` | "Which is better?" | ✅ | ✅ Yes | ✅ Auto | ❌ (uses latest) |
| `compare_jmeter_runs_from_s3.py` | "Which is better at C=X?" | ✅ | ✅ Yes | ❌ (single) | ❌ (uses latest) |
| `analyze_concurrency_scaling_from_s3.py` | "How does it scale?" | ✅ | ❌ No | ✅ Auto | ❌ (uses latest) |
| `analyze_aggregate_report.py` | "What are the results?" | ❌ | ✅ Yes | ❌ (single) | ❌ (local file) |

---

## Recent Enhancements (Oct 31, 2025)

### compare_consecutive_runs_from_s3.py (Enhanced)

**What's New**:
1. ✅ **Run IDs in filename** - Clear traceability of which runs are compared
2. ✅ **Query-by-query comparison** - See exactly which queries improved/degraded
3. ✅ **Manual run ID selection** - Compare specific runs, not just latest 2
4. ✅ **Cold start detection** - BOOTSTRAP query analysis helps identify cold clusters

**Breaking Changes**: None - backward compatible

**Migration**: No action needed - works same as before by default

---

## Getting Help

```bash
# All scripts support --help
python utilities/compare_consecutive_runs_from_s3.py --help
python utilities/compare_multi_concurrency_from_s3.py --help
python utilities/analyze_concurrency_scaling_from_s3.py --help
```

For issues or questions:
- Check this documentation
- Review example reports in `reports/` directory
- Examine the script source code (well-commented)
