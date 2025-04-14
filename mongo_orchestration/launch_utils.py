import atexit
import copy
import itertools
import time
import os

import pymongo
import requests

# Configurable hosts and ports used in the tests
DB_USER = str(os.environ.get("DB_USER", ""))
DB_PASSWORD = str(os.environ.get("DB_PASSWORD", ""))

_MO_ADDRESS = os.environ.get("MO_ADDRESS", "localhost:8889")
_MONGO_START_PORT = int(os.environ.get("MONGO_PORT", 27017))
_FREE_PORT = itertools.count(_MONGO_START_PORT)

DEFAULT_OPTIONS = {
    "logappend": True,
    "ipv6": True,
    "bind_ip": "127.0.0.1,::1",
    "setParameter": {"enableTestCommands": 1},
}

DEFAULT_CERTS = os.path.join(
    os.environ.get("MONGO_ORCHESTRATION_HOME", os.path.dirname(__file__)), "lib"
)
CERTS = os.environ.get("MONGO_ORCHESTRATION_CERTS", DEFAULT_CERTS)

SERVER_VERSION = ["3.6", "4.0", "4.2", "4.4", "5.0", "6.0", "7.0", "latest"]


# TODO: Figure out a better way to pass around template. Needs to be fixed
POST_REQUEST_TEMPLATE = {}
if DB_USER and DB_PASSWORD:
    POST_REQUEST_TEMPLATE = {"login": DB_USER, "password": DB_PASSWORD}


def _mo_url(resource, *args):
    return "http://" + "/".join([_MO_ADDRESS, resource] + list(args))


@atexit.register
def kill_all():
    try:
        clusters = requests.get(_mo_url("sharded_clusters")).json()
    except requests.ConnectionError:
        return
    repl_sets = requests.get(_mo_url("replica_sets")).json()
    servers = requests.get(_mo_url("servers")).json()
    for cluster in clusters["sharded_clusters"]:
        requests.delete(_mo_url("sharded_clusters", cluster["id"]))
    for rs in repl_sets["replica_sets"]:
        requests.delete(_mo_url("replica_sets", rs["id"]))
    for server in servers["servers"]:
        requests.delete(_mo_url("servers", server["id"]))


class MCTestObject(object):
    def proc_params(self):
        params = copy.deepcopy(DEFAULT_OPTIONS)
        params.update(self._proc_params)
        params["port"] = next(_FREE_PORT)
        return params

    def get_config(self):
        raise NotImplementedError

    def _make_post_request(self):
        config = POST_REQUEST_TEMPLATE.copy()
        config.update(self.get_config())
        import pprint

        pprint.pprint(config)
        ret = requests.post(_mo_url(self._resource), timeout=None, json=config)

        if not ret.ok:
            raise RuntimeError("Error sending POST to cluster: %s" % (ret.text,))

        ret = ret.json()
        if isinstance(ret, list):  # Will return a list if an error occurred.
            raise RuntimeError("Error sending POST to cluster: %s" % (ret,))
        pprint.pprint(ret)
        return ret

    def _make_get_request(self):
        ret = requests.get(_mo_url(self._resource, self.id), timeout=None)

        if not ret.ok:
            raise RuntimeError("Error sending GET to cluster: %s" % (ret.text,))

        ret = ret.json()
        if isinstance(ret, list):  # Will return a list if an error occurred.
            raise RuntimeError("Error sending GET to cluster: %s" % (ret,))
        return ret

    def client(self, **kwargs):
        kwargs = kwargs.copy()
        if DB_USER:
            kwargs["username"] = DB_USER
            kwargs["password"] = DB_PASSWORD
        client = pymongo.MongoClient(self.uri, **kwargs)
        return client

    def start(self):
        raise NotImplementedError

    def stop(self):
        requests.delete(_mo_url(self._resource, self.id))

    def __enter__(self):
        try:
            self.start()
        except requests.ConnectionError as e:
            raise ConnectionError(
                "Please check if mongo-orchestration is running"
            ) from e
        return self

    def __exit__(self, *args, **kwargs):
        self.stop()

    @classmethod
    def run(cls):
        with cls() as cluster:
            while True:
                data = input(cluster.cli_msg)
                if data == "q":
                    break
                if data == "r" and isinstance(cluster, ReplicaSet):
                    cluster.restart_primary()


class Server(MCTestObject):
    _resource = "servers"
    cli_msg = 'Type "q" to quit: '

    def __init__(self, id=None, uri=None, **kwargs):
        self.id = id
        self.uri = uri
        self._proc_params = kwargs

    def get_config(self):
        return {"name": "mongod", "procParams": self.proc_params()}

    def start(self):
        if self.id is None:
            response = self._make_post_request()
            self.id = response["id"]
            self.uri = response.get("mongodb_auth_uri", response["mongodb_uri"])
        else:
            requests.post(
                _mo_url("servers", self.id), timeout=None, json={"action": "start"}
            )
        return self

    def stop(self, destroy=True):
        if destroy:
            super(Server, self).stop()
        else:
            requests.post(
                _mo_url("servers", self.id), timeout=None, json={"action": "stop"}
            )


class ReplicaSet(MCTestObject):
    _resource = "replica_sets"
    cli_msg = 'Type "q" to quit, "r" to shutdown and restart the primary": '

    def __init__(
        self, id=None, uri=None, primary=None, secondary=None, single=False, **kwargs
    ):
        self.single = single
        self.id = id
        self.uri = uri
        self.primary = primary
        self.secondary = secondary
        self._proc_params = kwargs
        self.members = []

    def proc_params(self):
        return super(ReplicaSet, self).proc_params()

    def get_config(self):
        members = [{"procParams": self.proc_params()}]
        if not self.single:
            members.extend(
                [
                    {"procParams": self.proc_params()},
                    {"procParams": self.proc_params()},
                ]
            )
        return {"members": members}

    def _init_from_response(self, response):
        self.id = response["id"]
        self.uri = response.get("mongodb_auth_uri", response["mongodb_uri"])
        for member in response["members"]:
            m = Server(member["server_id"], member["host"])
            self.members.append(m)
            if member["state"] == 1:
                self.primary = m
            elif member["state"] == 2:
                self.secondary = m
        return self

    def start(self):
        # We never need to restart a replica set, only start new ones.
        return self._init_from_response(self._make_post_request())

    def restart_primary(self):
        self.primary.stop(destroy=False)
        time.sleep(5)
        self.primary.start()
        time.sleep(1)
        self._init_from_response(self._make_get_request())
        print("New primary: %s" % self.primary.uri)


class ReplicaSetSingle(ReplicaSet):
    def __init__(self):
        super(ReplicaSetSingle, self).__init__(single=True)


class ShardedCluster(MCTestObject):
    _resource = "sharded_clusters"
    _shard_type = ReplicaSet

    def __init__(self, **kwargs):
        self.id = None
        self.uri = None
        self.shards = []
        self._proc_params = kwargs

    def get_config(self):
        return {
            "routers": [self.proc_params(), self.proc_params()],
            "shards": [
                {"id": "demo-set-0", "shardParams": self._shard_type().get_config()},
            ],
        }

    def start(self):
        # We never need to restart a sharded cluster, only start new ones.
        response = self._make_post_request()
        for shard in response["shards"]:
            shard_resp = requests.get(_mo_url("replica_sets", shard["_id"]))
            shard_json = shard_resp.json()
            self.shards.append(self._shard_type()._init_from_response(shard_json))
        self.id = response["id"]
        self.uri = response.get("mongodb_auth_uri", response["mongodb_uri"])
        return self


class ShardedClusterSingle(ShardedCluster):
    _shard_type = ReplicaSetSingle


SERVER_TYPES = {
    "single": Server,
    "replica-single": ReplicaSetSingle,
    "replica": ReplicaSet,
    "shard": ShardedCluster,
    "shard-single": ShardedClusterSingle,
}
