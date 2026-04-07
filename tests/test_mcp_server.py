#!/usr/bin/python
# coding=utf-8
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

"""Tests for the MCP server tools (mongo_orchestration/mcp_server.py).

All HTTP calls and _ensure_running are mocked so no MongoDB binary or
running mongo-orchestration instance is required.
"""

import unittest
from unittest.mock import MagicMock, call, patch

import mongo_orchestration.mcp_server as mcp_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mo_up():
    """Patch _ensure_running to simulate mongo-orchestration already running."""
    return patch.object(mcp_server, "_ensure_running", return_value=None)


def _get_side_effect(**resources):
    """Return a _get side-effect that maps resource name → list of items."""
    def _get(path):
        return {path: resources.get(path, [])}
    return _get


# ---------------------------------------------------------------------------
# start_cluster
# ---------------------------------------------------------------------------

class TestStartClusterSingle(unittest.TestCase):

    def setUp(self):
        self._mo = _mo_up()
        self._mo.start()

    def tearDown(self):
        self._mo.stop()

    @patch.object(mcp_server, "_post",
                  return_value={"id": "srv1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_returns_id_and_uri(self, mock_post):
        result = mcp_server.start_cluster(cluster_type="single")
        self.assertIn("srv1", result)
        self.assertIn("mongodb://localhost:27017", result)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "srv1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_post_path_and_name(self, mock_post):
        mcp_server.start_cluster(cluster_type="single")
        path, body = mock_post.call_args[0]
        self.assertEqual(path, "servers")
        self.assertEqual(body["name"], "mongod")

    @patch.object(mcp_server, "_post",
                  return_value={"id": "srv1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_version_forwarded(self, mock_post):
        mcp_server.start_cluster(cluster_type="single", version="7.0")
        _, body = mock_post.call_args[0]
        self.assertEqual(body["version"], "7.0")

    @patch.object(mcp_server, "_post",
                  return_value={"id": "srv1",
                                "mongodb_auth_uri": "mongodb://user:password@localhost:27017",
                                "mongodb_uri": "mongodb://localhost:27017"})
    def test_auth_sets_credentials(self, mock_post):
        result = mcp_server.start_cluster(cluster_type="single", auth=True)
        _, body = mock_post.call_args[0]
        self.assertEqual(body["login"], "user")
        self.assertEqual(body["password"], "password")
        self.assertIn("auth_key", body)
        # auth URI takes precedence in the output
        self.assertIn("user:password", result)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "srv1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_no_version_key_when_empty(self, mock_post):
        mcp_server.start_cluster(cluster_type="single", version="")
        _, body = mock_post.call_args[0]
        self.assertNotIn("version", body)


class TestStartClusterRepl(unittest.TestCase):

    def setUp(self):
        self._mo = _mo_up()
        self._mo.start()

    def tearDown(self):
        self._mo.stop()

    @patch.object(mcp_server, "_post",
                  return_value={"id": "rs1", "mongodb_uri": "mongodb://localhost:27017/?replicaSet=rs1"})
    def test_default_3_members(self, mock_post):
        result = mcp_server.start_cluster(cluster_type="repl")
        _, body = mock_post.call_args[0]
        self.assertEqual(len(body["members"]), 3)
        self.assertIn("3 member", result)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "rs1", "mongodb_uri": "mongodb://localhost:27017/?replicaSet=rs1"})
    def test_single_member(self, mock_post):
        result = mcp_server.start_cluster(cluster_type="repl", single_member=True)
        _, body = mock_post.call_args[0]
        self.assertEqual(len(body["members"]), 1)
        self.assertIn("1 member", result)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "rs1", "mongodb_uri": "mongodb://localhost:27017/?replicaSet=rs1"})
    def test_post_path(self, mock_post):
        mcp_server.start_cluster(cluster_type="repl")
        path, _ = mock_post.call_args[0]
        self.assertEqual(path, "replica_sets")


class TestStartClusterShard(unittest.TestCase):

    def setUp(self):
        self._mo = _mo_up()
        self._mo.start()

    def tearDown(self):
        self._mo.stop()

    @patch.object(mcp_server, "_post",
                  return_value={"id": "sh1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_body_has_required_keys(self, mock_post):
        mcp_server.start_cluster(cluster_type="shard")
        _, body = mock_post.call_args[0]
        self.assertIn("configsvrs", body)
        self.assertIn("routers", body)
        self.assertIn("shards", body)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "sh1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_routers_have_no_procparams(self, mock_post):
        # routers must be [{}], not [{"procParams": {}}] — the latter would
        # write "procParams={}" literally into the mongos config file.
        mcp_server.start_cluster(cluster_type="shard")
        _, body = mock_post.call_args[0]
        for router in body["routers"]:
            self.assertNotIn("procParams", router)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "sh1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_post_path(self, mock_post):
        mcp_server.start_cluster(cluster_type="shard")
        path, _ = mock_post.call_args[0]
        self.assertEqual(path, "sharded_clusters")

    @patch.object(mcp_server, "_post",
                  return_value={"id": "sh1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_shard_member_count(self, mock_post):
        mcp_server.start_cluster(cluster_type="shard")
        _, body = mock_post.call_args[0]
        members = body["shards"][0]["shardParams"]["members"]
        self.assertEqual(len(members), 3)

    @patch.object(mcp_server, "_post",
                  return_value={"id": "sh1", "mongodb_uri": "mongodb://localhost:27017"})
    def test_single_member_shard(self, mock_post):
        mcp_server.start_cluster(cluster_type="shard", single_member=True)
        _, body = mock_post.call_args[0]
        members = body["shards"][0]["shardParams"]["members"]
        self.assertEqual(len(members), 1)


class TestStartClusterErrors(unittest.TestCase):

    def setUp(self):
        self._mo = _mo_up()
        self._mo.start()

    def tearDown(self):
        self._mo.stop()

    def test_unknown_cluster_type(self):
        result = mcp_server.start_cluster(cluster_type="unknown")
        self.assertIn("Unknown cluster_type", result)

    def test_mo_not_running(self):
        with patch.object(mcp_server, "_ensure_running", return_value="connection refused"):
            result = mcp_server.start_cluster()
        self.assertIn("Error", result)

    @patch.object(mcp_server, "_post", side_effect=RuntimeError("timeout"))
    def test_post_exception_returns_error(self, _):
        result = mcp_server.start_cluster(cluster_type="single")
        self.assertIn("Error", result)


# ---------------------------------------------------------------------------
# stop_cluster
# ---------------------------------------------------------------------------

class TestStopCluster(unittest.TestCase):

    def setUp(self):
        self._mo = _mo_up()
        self._mo.start()

    def tearDown(self):
        self._mo.stop()

    @patch.object(mcp_server, "_delete")
    @patch.object(mcp_server, "_get",
                  side_effect=_get_side_effect(servers=[{"id": "srv1"}]))
    def test_stop_standalone(self, _get, mock_delete):
        result = mcp_server.stop_cluster("srv1")
        self.assertIn("stopped", result)
        mock_delete.assert_called_once_with("servers/srv1")

    @patch.object(mcp_server, "_delete")
    @patch.object(mcp_server, "_get",
                  side_effect=_get_side_effect(replica_sets=[{"id": "rs1"}]))
    def test_stop_replica_set(self, _get, mock_delete):
        result = mcp_server.stop_cluster("rs1")
        self.assertIn("stopped", result)
        mock_delete.assert_called_once_with("replica_sets/rs1")

    @patch.object(mcp_server, "_delete")
    @patch.object(mcp_server, "_get",
                  side_effect=_get_side_effect(sharded_clusters=[{"id": "sh1"}]))
    def test_stop_sharded_cluster(self, _get, mock_delete):
        result = mcp_server.stop_cluster("sh1")
        self.assertIn("stopped", result)
        mock_delete.assert_called_once_with("sharded_clusters/sh1")

    @patch.object(mcp_server, "_get", side_effect=_get_side_effect())
    def test_stop_not_found(self, _):
        result = mcp_server.stop_cluster("nonexistent")
        self.assertIn("No cluster found", result)

    def test_stop_mo_not_running(self):
        with patch.object(mcp_server, "_ensure_running", return_value="connection refused"):
            result = mcp_server.stop_cluster("srv1")
        self.assertIn("Error", result)


# ---------------------------------------------------------------------------
# list_clusters
# ---------------------------------------------------------------------------

class TestListClusters(unittest.TestCase):

    def setUp(self):
        self._mo = _mo_up()
        self._mo.start()

    def tearDown(self):
        self._mo.stop()

    @patch.object(mcp_server, "_get", side_effect=_get_side_effect())
    def test_empty(self, _):
        result = mcp_server.list_clusters()
        self.assertEqual(result, "No clusters running.")

    @patch.object(mcp_server, "_get",
                  side_effect=_get_side_effect(servers=[{"id": "srv1"}]))
    def test_lists_standalone(self, _):
        result = mcp_server.list_clusters()
        self.assertIn("srv1", result)
        self.assertIn("Standalone", result)

    @patch.object(mcp_server, "_get",
                  side_effect=_get_side_effect(replica_sets=[{"id": "rs1"}, {"id": "rs2"}]))
    def test_lists_multiple_replica_sets(self, _):
        result = mcp_server.list_clusters()
        self.assertIn("rs1", result)
        self.assertIn("rs2", result)
        self.assertIn("Replica", result)

    @patch.object(mcp_server, "_get",
                  side_effect=_get_side_effect(
                      servers=[{"id": "srv1"}],
                      sharded_clusters=[{"id": "sh1"}]))
    def test_lists_mixed(self, _):
        result = mcp_server.list_clusters()
        self.assertIn("srv1", result)
        self.assertIn("sh1", result)

    def test_mo_not_running(self):
        with patch.object(mcp_server, "_ensure_running", return_value="connection refused"):
            result = mcp_server.list_clusters()
        self.assertIn("not running", result)


# ---------------------------------------------------------------------------
# _ensure_running
# ---------------------------------------------------------------------------

class TestEnsureRunning(unittest.TestCase):

    @patch.object(mcp_server, "_is_up", return_value=True)
    def test_already_up(self, _):
        self.assertIsNone(mcp_server._ensure_running())

    @patch("time.sleep")
    @patch("subprocess.run")
    @patch.object(mcp_server, "_is_up", side_effect=[False] + [True])
    def test_starts_mo_when_down(self, _is_up, mock_run, _sleep):
        mock_run.return_value = MagicMock(returncode=0)
        result = mcp_server._ensure_running()
        self.assertIsNone(result)
        mock_run.assert_called_once()

    @patch("time.sleep")
    @patch("subprocess.run", side_effect=FileNotFoundError)
    @patch.object(mcp_server, "_is_up", return_value=False)
    def test_binary_not_found(self, _is_up, _run, _sleep):
        result = mcp_server._ensure_running()
        self.assertIsNotNone(result)
        self.assertIn("not found", result)

    @patch("time.sleep")
    @patch("subprocess.run")
    @patch.object(mcp_server, "_is_up", return_value=False)
    def test_never_becomes_reachable(self, _is_up, mock_run, _sleep):
        mock_run.return_value = MagicMock(returncode=0)
        result = mcp_server._ensure_running()
        self.assertIsNotNone(result)
        self.assertIn("not reachable", result)

    @patch("time.sleep")
    @patch("subprocess.run", side_effect=__import__('subprocess').TimeoutExpired(cmd=[], timeout=30))
    @patch.object(mcp_server, "_is_up", return_value=False)
    def test_timeout(self, _is_up, _run, _sleep):
        result = mcp_server._ensure_running()
        self.assertIsNotNone(result)
        self.assertIn("Timeout", result)


if __name__ == "__main__":
    unittest.main()
