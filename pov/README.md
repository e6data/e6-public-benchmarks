# Benchmark POV Tool

The Benchmark POV Tool is a browser UI for comparing e6data and Databricks query workloads. This directory contains only its deployment wrapper: Docker Compose starts prebuilt frontend and backend images plus MySQL; the application source is not part of this repository.

## Prerequisites

- Docker Engine with Docker Compose support
- An active e6data cluster, catalog, user, and personal access token
- An active Databricks compute resource, server hostname, HTTP path, and personal access token
- Network allowlisting that lets the containers reach both engines

Use comparable datasets and compute sizes on both engines if the results will be used for a performance comparison.

## Configure

Create the untracked runtime configuration and replace both password values:

```bash
cp .env.example .env
```

The repository intentionally tracks only `.env.example`. Never commit the
generated `.env`, and do not expose the service publicly with demonstration
credentials.

For a remote host, set `REACT_APP_API_DOMAIN` to the externally reachable backend URL, including `/api/`:

```dotenv
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<strong-password>
DJANGO_SUPERUSER_EMAIL=admin@example.com
MYSQL_ROOT_PASSWORD=<strong-password>
PERSISTENCE_VOLUME=pov_tool_data
REACT_APP_API_DOMAIN=https://benchmark.example.com/api/
```

The named Docker volume in `PERSISTENCE_VOLUME` retains MySQL data across container recreation.

## Start

Run from this directory:

```bash
docker compose up -d
docker compose ps
```

On a local deployment:

- Frontend: `http://localhost:3000/login/`
- Django administration: `http://localhost:3001/api/`

The images are pinned in [docker-compose.yaml](docker-compose.yaml). The first start requires access to their Google Artifact Registry location and may take time while Docker pulls them.

## Configure the application

1. Sign in to the Django administration page with the `DJANGO_SUPERUSER_*` values.
2. Create a normal application user under `Home > User > Users`; use this account for the frontend.
3. Under `Benchmarks > Benchmark_ips`, add the e6data and Databricks connection details. Use the same logical database/dataset for both sides.
4. Sign in to the frontend and select **Create Benchmark**.
5. Enter the benchmark name, engine pair, hourly costs, and sequential/concurrent settings.
6. Upload the query CSV using the sample offered by the UI, then run the benchmark.
7. Review per-query time and estimated cost, and download the detailed report if needed.

Treat downloaded reports as sensitive: they can contain SQL text, connection-related errors, and workload metadata.

## Operate and stop

Inspect logs with:

```bash
docker compose logs -f backend frontend dbserver
```

Stop containers while preserving the named MySQL volume:

```bash
docker compose down
```

Delete containers **and the persisted benchmark/configuration data**:

```bash
docker compose down -v
```

The `-v` operation is destructive. Export anything you need before running it.

## Known constraints

- The Compose file pins `linux/amd64`; ARM hosts may use emulation and run more slowly.
- Ports `3000`, `3001`, and `3306` are published on the host. Restrict them with host firewall or network controls when not running solely on localhost.
- This is a lab tool backed by prebuilt images. Image internals, application upgrades, and security patches are outside this repository.
