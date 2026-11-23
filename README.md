# Automated API Health-Checker

A scheduled checker that tests REST endpoints from the outside: status code, response time, body content and JSON schema. It measures availability against an SLA target and only alerts on confirmed failures. It works with Postman collections in both directions (import and export, then run with Newman) and also runs as a step in an Azure DevOps pipeline.

## Desktop app

The dark-themed desktop app has six pages:

| Page | What it shows |
|---|---|
| **Overview** | KPI cards with sparklines, response-time chart, recent events, and per-service uptime bars |
| **Endpoints** | expectations, a response-time trend with the limit line, the last 100 checks, and recent failures for each endpoint |
| **SLA Report** | 30-day availability against the target, error budget left, and CSV export |
| **Events** | the alert, escalation and recovery log, with filters |
| **Postman** | collection export and import, and a Newman run with live output |
| **Configuration** | a YAML editor with highlighting; it validates before saving and keeps a `.bak` backup |

Confirmed alerts pop up as toasts in the bottom-right corner and play a sound. Monitoring runs on a background thread, and you can pause it with the sidebar switch.

## Quick start (Windows)

| File | What it does |
|---|---|
| `setup.bat` | creates the virtual environment and installs dependencies (run once) |
| `start_gui.bat` | **desktop app**, with the built-in demo API started on port 8000 |
| `start_demo_api.bat` | demo REST API only, at `http://127.0.0.1:8000` |
| `start_watch.bat` | scheduled checks in the terminal |

To check your own API, edit `endpoints.yaml` (or import a Postman collection) and remove `--demo` from `start_gui.bat`.

## Commands

```
python -m healthcheck run [--junit out.xml] [--fail-on-error] [--no-alerts]   # one run (CI)
python -m healthcheck watch [--interval 30]                                   # scheduled runs
python -m healthcheck report [--json] [--fail-on-breach]                       # SLA report (24h / 7d / 30d)
python -m healthcheck page --open                                             # status page (site/index.html)
python -m healthcheck gui [--demo]                                            # desktop app
python -m healthcheck postman-import coll.json [-e env.json] -o endpoints.yaml
python -m healthcheck postman-export [-o postman/health-check.postman_collection.json]
python -m healthcheck newman [collection] [--junit out.xml] [--env-var BASE_URL=...]
```

Use `-c other.yaml` to pick a different config file.

## Configuration: `endpoints.yaml`

Each endpoint can set:

- `url`
- `method`
- `headers`
- `body`
- `expected_status`: a number or a list
- `max_response_ms`
- `sla_target` (%)
- `contains`: text that must appear in the response body
- `schema`: an inline JSON schema, or `schema_file`: a path to a JSON schema file

Environment variables use `${VAR:-default}` syntax (for example `BASE_URL` and `API_TOKEN`).

## Avoiding false alarms, and escalation

1. **Retries (`retries`):** transient errors are retried immediately within a run. A run only fails if every attempt fails.
2. **Confirmation (`confirm_failures`):** an `ALERT` goes out only after N consecutive failed runs.
3. **Escalation (`escalate_after`):** if the failure continues, an `ESCALATION` goes out on every Kth further failed run, optionally to a separate webhook.
4. **Recovery:** when the endpoint is healthy again, a `RECOVERY` notice goes out with the length of the outage.

Notifications go to the console, the desktop app, and Teams/Slack webhooks (`ALERT_WEBHOOK_URL`, `ESCALATION_WEBHOOK_URL`).

## Postman

- **Export:** `endpoints.yaml` becomes a Postman v2.1 collection with `pm.test` checks for status, response time, body content and `jsonSchema`. `${BASE_URL}` becomes the `{{BASE_URL}}` collection variable.
- **Import:** an existing collection (including folders and an environment) becomes YAML. `pm.response.to.have.status(...)` and `responseTime ... below(...)` tests become expectations.
- **Newman:** runs in CI next to the Python checker. To run it locally, install it with `npm install -g newman`.

## Azure DevOps

`azure-pipelines.yml` starts in two ways:

- after every deploy, so a bad release is caught right away;
- on a schedule, every 15 minutes.

Each run:

- publishes JUnit test results;
- attaches the status page as an artifact;
- keeps the check history in the pipeline cache, which confirmation and SLA numbers depend on;
- runs the Newman tests in a separate job.

Set `BASE_URL`, `API_TOKEN` and the webhook URLs as secret pipeline variables.

## Tests

```
.venv\Scripts\python -m pytest -q tests
```
