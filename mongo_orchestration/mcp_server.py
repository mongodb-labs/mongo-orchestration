#!/usr/bin/env python3
# Copyright 2026-Present MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""MCP server for mongo-orchestration (stdio transport).

Claude Code launches this process on demand via the stdio MCP config.
On startup, it ensures mongo-orchestration is running (starts it if not).
Tools communicate with mongo-orchestration via its REST API (localhost:8889).
"""

import os
import socket
import subprocess
import sys
import time
from typing import Literal

from mcp.server.fastmcp import FastMCP

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

_MO_HOST = os.environ.get("MO_HOST", "localhost")
_MO_PORT = int(os.environ.get("MO_PORT", "8889"))
_MO_URL = f"http://{_MO_HOST}:{_MO_PORT}"

# Path to the mongo-orchestration binary installed in the same venv as us.
_MO_BIN = os.path.join(os.path.dirname(sys.executable), "mongo-orchestration")

mcp = FastMCP("mongo-orchestration")


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def _is_up(timeout: float = 2.0) -> bool:
    try:
        conn = socket.create_connection((_MO_HOST, _MO_PORT), timeout=timeout)
        conn.close()
        return True
    except OSError:
        return False


def _ensure_running() -> str | None:
    """Start mongo-orchestration if it is not already up.

    Returns an error message on failure, None on success.
    """
    if _is_up():
        return None

    bin_path = _MO_BIN if os.path.exists(_MO_BIN) else "mongo-orchestration"

    # Look for mo-config.json next to this package or in the project root.
    _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _config = os.path.join(_here, "mo-config.json")
    cmd = [bin_path, "start"]
    if os.path.exists(_config):
        cmd += ["-f", _config]

    try:
        subprocess.run(
            cmd,
            check=True,
            timeout=30,
            capture_output=True,
        )
    except FileNotFoundError:
        return (
            "mongo-orchestration not found. "
            f"Expected: {_MO_BIN}"
        )
    except subprocess.CalledProcessError as exc:
        return f"Failed to start mongo-orchestration: {exc.stderr}"
    except subprocess.TimeoutExpired:
        return "Timeout while starting mongo-orchestration."

    # Wait up to 10 s for the server to accept connections.
    for _ in range(10):
        if _is_up():
            return None
        time.sleep(1)

    return f"mongo-orchestration started but not reachable on {_MO_HOST}:{_MO_PORT}."


def _get(path: str) -> dict:
    import requests
    return requests.get(f"{_MO_URL}/{path}", timeout=10).json()


def _post(path: str, body: dict) -> dict:
    import requests
    r = requests.post(f"{_MO_URL}/{path}", json=body, timeout=None)
    if not r.ok:
        raise RuntimeError(r.text)
    return r.json()


def _delete(path: str) -> None:
    import requests
    requests.delete(f"{_MO_URL}/{path}", timeout=30)


# -------------------------------------------------------------------
# Tools
# -------------------------------------------------------------------

@mcp.tool()
def start_cluster(
    cluster_type: Literal["single", "repl", "shard"] = "single",
    version: str = "",
    auth: bool = False,
    ssl: bool = False,
    single_member: bool = False,
) -> str:
    """Start a MongoDB cluster via mongo-orchestration.

    Starts mongo-orchestration automatically if it is not running.

    Args:
        cluster_type: "single" (standalone mongod), "repl" (replica set),
                      or "shard" (sharded cluster with one replica-set shard).
        version: MongoDB version, e.g. "7.0" or "latest". Empty = server default.
        auth: Enable authentication (login=user / password=password).
        ssl: Enable SSL/TLS.
        single_member: For replica sets, use a 1-member set instead of 3.
    """
    err = _ensure_running()
    if err:
        return f"Error: {err}"

    base: dict = {}
    if version:
        base["version"] = version
    if auth:
        base["login"] = "user"
        base["password"] = "password"
        base["auth_key"] = "secret"

    try:
        if cluster_type == "single":
            body = {**base, "name": "mongod", "procParams": {}}
            result = _post("servers", body)
            uid = result["id"]
            uri = result.get("mongodb_auth_uri") or result.get("mongodb_uri", "")
            return f"Standalone mongod started.\n  id:  {uid}\n  uri: {uri}"

        elif cluster_type == "repl":
            n = 1 if single_member else 3
            members = [{"procParams": {}} for _ in range(n)]
            body = {**base, "members": members}
            result = _post("replica_sets", body)
            uid = result["id"]
            uri = result.get("mongodb_auth_uri") or result.get("mongodb_uri", "")
            return (
                f"Replica set started ({n} member(s)).\n"
                f"  id:  {uid}\n"
                f"  uri: {uri}"
            )

        elif cluster_type == "shard":
            n = 1 if single_member else 3
            members = [{"procParams": {}} for _ in range(n)]
            body = {
                **base,
                "configsvrs": [{}],
                "routers": [{}],
                "shards": [{"id": "shard-0", "shardParams": {"members": members}}],
            }
            result = _post("sharded_clusters", body)
            uid = result["id"]
            uri = result.get("mongodb_auth_uri") or result.get("mongodb_uri", "")
            return f"Sharded cluster started.\n  id:  {uid}\n  uri: {uri}"

        else:
            return f"Unknown cluster_type '{cluster_type}'. Use: single, repl, or shard."

    except Exception as exc:
        return f"Error starting {cluster_type}: {exc}"


@mcp.tool()
def stop_cluster(cluster_id: str) -> str:
    """Stop and remove a running cluster by its ID.

    Args:
        cluster_id: The ID returned by start_cluster or list_clusters.
    """
    err = _ensure_running()
    if err:
        return f"Error: {err}"

    for resource in ("servers", "replica_sets", "sharded_clusters"):
        try:
            ids = [item["id"] for item in _get(resource).get(resource, [])]
        except Exception:
            continue
        if cluster_id in ids:
            try:
                _delete(f"{resource}/{cluster_id}")
                return f"'{cluster_id}' stopped."
            except Exception as exc:
                return f"Error stopping '{cluster_id}': {exc}"

    return f"No cluster found with id '{cluster_id}'. Use list_clusters to see running clusters."


@mcp.tool()
def list_clusters() -> str:
    """List all clusters currently managed by mongo-orchestration."""
    err = _ensure_running()
    if err:
        return f"mongo-orchestration is not running: {err}"

    lines: list[str] = []
    labels = {
        "servers": "Standalone servers",
        "replica_sets": "Replica sets",
        "sharded_clusters": "Sharded clusters",
    }
    try:
        for resource, label in labels.items():
            items = _get(resource).get(resource, [])
            if items:
                lines.append(f"{label}:")
                for item in items:
                    uid = item.get("id", "?")
                    lines.append(f"  {uid}")
    except Exception as exc:
        return f"Error: {exc}"

    return "\n".join(lines) if lines else "No clusters running."


# -------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------

def main() -> None:
    """Start the MCP server (stdio). Ensures mongo-orchestration is running first."""
    _ensure_running()
    mcp.run()


if __name__ == "__main__":
    main()
