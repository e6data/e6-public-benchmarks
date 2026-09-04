# Shared runner settings

`system_settings.json` contains deployment defaults shared by
`run_test.sh`, the interactive launcher, and the optional Benchmark Studio UI.
Copy `system_settings.example.json` to the gitignored `system_settings.json`.

Environment variables and suite files override these defaults. The optional e6
Query History machine-client secret may be saved here through the administrator
settings page; the UI stores this file with owner-only permissions and never
returns the secret through its API. Do not commit this file or put AWS/JDBC
credentials, PATs, or connection strings in it.

For eventually consistent Query History, set
`e6_query_history_wait_seconds` (or `E6_QUERY_HISTORY_WAIT_SECONDS`) high enough
for the provider to publish completed queries; 300 seconds is a reasonable lab
default when immediate history is not guaranteed. This wait happens after each
e6 warm-up/measured JMeter phase and therefore also delays the next leg of a
sequential paired comparison.

`COPY_TO_S3=true` uploads the measured result directory after optional Query
History capture. The directory includes exact non-secret snapshots under
`inputs/` for the measured query CSV, warm-up CSV, and applicable load profile.
Connection profiles and test-property files are never included.
