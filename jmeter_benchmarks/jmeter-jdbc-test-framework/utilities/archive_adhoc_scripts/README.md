# Archived Ad-hoc Comparison Scripts

**Date Archived**: October 31, 2025  
**Reason**: Replaced by standardized comparison framework

## What's in This Archive

These are ad-hoc scripts that were created for one-time comparisons between JMeter test results. They have been **replaced by the new standardized framework**.

### Archived Scripts

| Script | Original Purpose | Replaced By |
|--------|------------------|-------------|
| `compare_query_by_query.py` | Query-by-query comparison | `compare_jmeter_runs.py` |
| `compare_query_detailed.py` | Detailed query comparison | `compare_jmeter_runs.py` |
| `generate_query_comparison_different_clusters.py` | Cluster comparison | `compare_multi_concurrency.py` |
| `generate_query_latency_comparison_csv.py` | Latency comparison CSV | `compare_jmeter_runs.py` |
| `summarize_concurrency_runs.py` | Concurrency summary | `compare_multi_concurrency.py` |

## Why Were They Replaced?

The old scripts had several issues:
- **Inconsistent output formats** - Each script generated reports differently
- **Hard-coded paths** - Required editing scripts for each comparison
- **No standardization** - No naming conventions
- **Limited reusability** - One-time use scripts
- **Duplicate functionality** - Multiple scripts doing similar things

## New Framework (What to Use Instead)

Use the new standardized comparison framework located in `utilities/`:

### For Single Concurrency Comparison:
```bash
python utilities/compare_jmeter_runs.py S3_PATH_1 S3_PATH_2
```

### For Multi-Concurrency Comparison (Recommended):
```bash
python utilities/compare_multi_concurrency.py S3_BASE_PATH_1 S3_BASE_PATH_2
```

### Documentation:
- **Quick Reference**: `utilities/QUICK_REFERENCE.md`
- **Full Guide**: `utilities/COMPARISON_TOOL_README.md`
- **Framework Summary**: `COMPARISON_FRAMEWORK_SUMMARY.md`

## Can I Delete These?

Yes, you can safely delete this archive directory once you're confident the new framework covers all your needs. We kept them as reference in case:
- You need to understand how old comparisons were done
- There's a specific feature from an old script you want to replicate
- You need to cross-reference historical reports

## Historical Reference

These scripts were used for various JPMC comparisons during October 2025, including:
- E6Data M vs Databricks S-4x4 comparisons
- Multi-concurrency analysis (C=2, 4, 8, 12, 16)
- Query-level latency comparisons

All of this functionality is now available in the standardized framework with better output formats and consistent naming.

---

**If you haven't used these in 6 months, feel free to delete this entire archive directory.**
