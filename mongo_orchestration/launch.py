# Copyright 2023-Present MongoDB, Inc.
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

import argparse
import os

from launch_utils import (
    SERVER_TYPES,
    SERVER_VERSION,
    POST_REQUEST_TEMPLATE,
    CERTS,
    DB_PASSWORD,
    DB_USER,
)


def main():
    parser = argparse.ArgumentParser(description="mongo-launch script")
    parser.add_argument("server_type", action="store", choices=SERVER_TYPES.keys())
    parser.add_argument(
        "-v",
        "--server-version",
        action="store",
        type=str,
        choices=SERVER_VERSION,
        default=None,
    )
    parser.add_argument("-t", "--use-tls", action="store_true")
    parser.add_argument("-a", "--auth", action="store_true")

    cli_args = parser.parse_args()

    if cli_args.server_version:
        POST_REQUEST_TEMPLATE["version"] = cli_args.server_version
    if cli_args.use_tls:
        POST_REQUEST_TEMPLATE["sslParams"] = {
            "sslOnNormalPorts": True,
            "sslPEMKeyFile": os.path.join(CERTS, "server.pem"),
            "sslCAFile": os.path.join(CERTS, "ca.pem"),
            "sslWeakCertificateValidation": True,
        }
    if cli_args.auth:
        POST_REQUEST_TEMPLATE["login"] = DB_USER or "user"
        POST_REQUEST_TEMPLATE["password"] = DB_PASSWORD or "password"
        POST_REQUEST_TEMPLATE["auth_key"] = "secret"

    SERVER_TYPES[cli_args.server_type].run()


# Requires mongo-orchestration running on port 8889.
#
# Usage:
# mongo-launch <single|repl|shard> <auth> <ssl>
#
# Examples (standalone node):
# mongo-launch single
# mongo-launch single --auth
# mongo-launch single --auth --use-tls
#
# Sharded clusters:
# mongo-launch shard
# mongo-launch shard-single --auth
# mongo-launch shard-single --auth --use-tls
#
# Replica sets:
# mongo-launch replica
# mongo-launch replica-single
# mongo-launch replica-single --auth
if __name__ == "__main__":
    main()
