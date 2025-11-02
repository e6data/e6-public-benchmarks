# JMeter S3 Comparison - Quick Reference

## 🚀 Most Common Command (Recommended)

Compare all concurrency runs between two engines:

```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/
```

**This automatically finds ALL matching concurrency runs and generates comprehensive comparison!**

---

## 📋 Quick Command Templates

### Template 1: Multi-Concurrency Comparison (Recommended)

```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=ENGINE1/cluster_size=CLUSTER1/benchmark=BENCHMARK/ \
  s3://e6-jmeter/jmeter-results/engine=ENGINE2/cluster_size=CLUSTER2/benchmark=BENCHMARK/
```

**Replace:**
- `ENGINE1` / `ENGINE2`: `e6data` or `databricks`
- `CLUSTER1` / `CLUSTER2`: `XS`, `S-2x2`, `M`, `S-4x4`, etc.
- `BENCHMARK`: `tpcds_29_1tb`, etc.

**Output:** CSV + Markdown summary in `reports/` directory

---

### Template 2: Single Concurrency Comparison

```bash
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=ENGINE1/cluster_size=CLUSTER1/benchmark=BENCHMARK/run_type=concurrency_X/ \
  s3://e6-jmeter/jmeter-results/engine=ENGINE2/cluster_size=CLUSTER2/benchmark=BENCHMARK/run_type=concurrency_X/
```

**Replace:**
- `ENGINE1` / `ENGINE2`: `e6data` or `databricks`
- `CLUSTER1` / `CLUSTER2`: `XS`, `S-2x2`, `M`, `S-4x4`, etc.
- `BENCHMARK`: `tpcds_29_1tb`, etc.
- `X`: Concurrency level (2, 4, 8, 12, 16, etc.)

**Output:** CSV + Markdown summary in `reports/` directory

---

## 🔍 Find Your S3 Paths

List available engines:
```bash
aws s3 ls s3://e6-jmeter/jmeter-results/
```

List available cluster sizes for an engine:
```bash
aws s3 ls s3://e6-jmeter/jmeter-results/engine=e6data/
```

List available benchmarks:
```bash
aws s3 ls s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/
```

List available run types (concurrency levels):
```bash
aws s3 ls s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/
```

---

## 📊 Real-World Examples

### Example 1: Compare E6Data M vs Databricks S-4x4 (120 cores each)

```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/
```

### Example 2: Compare E6Data S-2x2 vs Databricks S-2x2 (60 cores each)

```bash
python utilities/compare_multi_concurrency.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=S-2x2/benchmark=tpcds_29_1tb/ \
  s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-2x2/benchmark=tpcds_29_1tb/
```

### Example 3: Compare Sequential Runs (XS clusters, 30 cores)

```bash
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=XS/benchmark=tpcds_29_1tb/run_type=sequential/ \
  s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=XS/benchmark=tpcds_29_1tb/run_type=sequential/
```

### Example 4: Compare Only Concurrency=4

```bash
python utilities/compare_jmeter_runs.py \
  s3://e6-jmeter/jmeter-results/engine=e6data/cluster_size=M/benchmark=tpcds_29_1tb/run_type=concurrency_4/ \
  s3://e6-jmeter/jmeter-results/engine=databricks/cluster_size=S-4x4/benchmark=tpcds_29_1tb/run_type=concurrency_4/
```

---

## 📁 Output Files

After running comparisons, check `reports/` directory:

**Multi-Concurrency:**
- `engine1_cluster1_vs_engine2_cluster2_MultiConcurrency_YYYYMMDD.csv`
- `engine1_cluster1_vs_engine2_cluster2_MultiConcurrency_YYYYMMDD_SUMMARY.md`

**Single Concurrency:**
- `ENG_CLU_vs_ENG_CLU_concurrencyX_YYYYMMDD.csv`
- `ENG_CLU_vs_ENG_CLU_concurrencyX_YYYYMMDD_SUMMARY.md`

---

## 🎯 Understanding Percentage Differences

In the CSV and reports:

- **Positive % (e.g., +50.5%)**: First engine (Engine 1) is FASTER
- **Negative % (e.g., -35.2%)**: Second engine (Engine 2) is FASTER
- **~0%**: Both engines are comparable

Example: If comparing E6Data vs Databricks and you see `+51.5%` for average:
→ **E6Data is 51.5% faster than Databricks**

---

## ⚙️ Optional Flags

### Change Output Directory

```bash
python utilities/compare_multi_concurrency.py path1 path2 --output-dir /custom/path
```

### Get Help

```bash
python utilities/compare_jmeter_runs.py --help
python utilities/compare_multi_concurrency.py --help
```

---

## ✅ Pre-Flight Checklist

Before running comparisons:

1. ✅ AWS credentials configured: `aws s3 ls s3://e6-jmeter/`
2. ✅ Both S3 paths exist and contain statistics.json files
3. ✅ Python 3.7+ installed: `python3 --version`
4. ✅ In correct directory: `cd jmeter-jdbc-test-framework`

---

## 🔧 Troubleshooting

**Error: "Invalid S3 path format"**
→ Check path follows: `s3://bucket/.../engine=X/cluster_size=Y/benchmark=Z/run_type=W/`

**Error: "Could not find statistics.json"**
→ Verify file exists: `aws s3 ls s3://path/to/run/`

**Error: "No matching concurrency levels found"**
→ Ensure both engines have at least one matching concurrency run

**AWS credentials issue**
→ Run: `aws configure` or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`

---

## 📖 Full Documentation

For complete details, see: `utilities/COMPARISON_TOOL_README.md`

---

**Quick Start:** Just copy-paste Template 1, replace the paths, and run!
