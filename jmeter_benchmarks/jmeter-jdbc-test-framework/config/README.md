# Shared runner settings

`system_settings.json` contains non-secret deployment defaults shared by
`run_test.sh`, the interactive launcher, and the optional Benchmark Studio UI.
Copy `system_settings.example.json` to the gitignored `system_settings.json`.

Environment variables and suite files override these defaults. Do not place
AWS credentials, JDBC passwords, PATs, or connection strings in this file.
