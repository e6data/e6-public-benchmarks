# Shared runner settings

`system_settings.json` contains deployment defaults shared by
`run_test.sh`, the interactive launcher, and the optional Benchmark Studio UI.
Copy `system_settings.example.json` to the gitignored `system_settings.json`.

Environment variables and suite files override these defaults. The optional e6
Query History machine-client secret may be saved here through the administrator
settings page; the UI stores this file with owner-only permissions and never
returns the secret through its API. Do not commit this file or put AWS/JDBC
credentials, PATs, or connection strings in it.
