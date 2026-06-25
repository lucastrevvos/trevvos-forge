# Local API and Dashboard

Trevvos Forge includes a local HTTP server that exposes a read-only REST API and a browser dashboard for inspecting sessions and artifacts.

---

## Starting the Server

```bash
trevvos api start
```

The server binds to `127.0.0.1:8765` by default. Output:

```
API: http://127.0.0.1:8765
Dashboard: http://127.0.0.1:8765/
```

**Open the dashboard automatically:**

```bash
trevvos api start --open
```

**Custom port:**

```bash
trevvos api start --port 9000
```

Stop the server with `Ctrl+C`.

---

## Dashboard

Open `http://127.0.0.1:8765/` in a browser.

The dashboard has three panels:

- **Sessions panel** (left): list of sessions with IDs and statuses. Click a session to select it.
- **Session panel** (center): session metadata, timing, artifacts list. Click an artifact to view it.
- **Artifact panel** (right): raw artifact content (JSON, diff, text).

**Refresh:** Click the Refresh button or reload the page. The dashboard does not auto-refresh.

**Export:** The dashboard shows the export command for the selected session at the bottom of the session panel.

---

## REST API Reference

The API is read-only. All endpoints return JSON. The server binds to `127.0.0.1` (loopback) by default â€” it is not accessible from other machines unless you override the host.

### `GET /health`

Health check.

```json
{"status": "ok", "version": "..."}
```

### `GET /sessions`

List all local sessions.

```json
[
  {"id": "...", "status": "succeeded", "created_at": "...", "command": "..."},
  ...
]
```

### `GET /sessions/{id}`

Session metadata.

```json
{
  "id": "...",
  "status": "succeeded",
  "command": "tests add",
  "created_at": "...",
  "duration_seconds": 12.4,
  "provider": "ollama",
  "model": "qwen2.5-coder:7b"
}
```

### `GET /sessions/{id}/artifacts`

List artifacts for a session.

```json
["metadata.json", "test_patch.diff", "sandbox_result.json", "system_prompt.txt"]
```

### `GET /sessions/{id}/artifacts/{name}`

Raw artifact content.

Response: `application/json` for `.json` files, `text/plain` for everything else.

Secrets in JSON artifacts are masked automatically (keys matching `api_key`, `token`, `secret`, `password`, `authorization`, `auth` are replaced with `"present"`).

### `GET /`

Serves the HTML dashboard (`dashboard.html`).

### `GET /static/{file}`

Serves static dashboard assets (`dashboard.css`, `dashboard.js`).

---

## Security Notes

- The API server binds to `127.0.0.1` (loopback) by default. It is not exposed to the network.
- The API is read-only: no endpoints modify sessions or configuration.
- JSON artifacts have secrets masked before serving. Never expose the API on a public network.
- Path traversal for static files is blocked.
- The server is intended for local development use only.

---

## Scripting with the API

The API is useful for scripting and CI inspection:

```bash
# List sessions
curl -s http://127.0.0.1:8765/sessions | python -m json.tool

# Get latest session status
curl -s http://127.0.0.1:8765/sessions/<id> | python -c "import json,sys; d=json.load(sys.stdin); print(d['status'])"

# List artifacts for a session
curl -s http://127.0.0.1:8765/sessions/<id>/artifacts | python -m json.tool

# Read an artifact
curl -s http://127.0.0.1:8765/sessions/<id>/artifacts/sandbox_result.json
```


