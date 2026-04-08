#!/usr/bin/python
import argparse
import json
import logging
import os.path
import signal
import socket
import sys
import time
import traceback
    
from bson import SON

from mongo_orchestration import __version__
from mongo_orchestration.common import (
    BaseModel,
    DEFAULT_BIND, DEFAULT_PORT, DEFAULT_SERVER, DEFAULT_SOCKET_TIMEOUT,
    PID_FILE, LOG_FILE, LOGGING_FORMAT)
from mongo_orchestration.daemon import Daemon
from mongo_orchestration.servers import Server

# How many times to attempt connecting to mongo-orchestration server.
CONNECT_ATTEMPTS = 5
# How many seconds to wait before timing out a connection attempt to the
# mongo-orchestration server.
CONNECT_TIMEOUT = 5


def read_env(argv=None):
    """return command-line arguments"""
    parser = argparse.ArgumentParser(description='mongo-orchestration server')
    parser.add_argument('-f', '--config',
                        action='store', default=None, type=str, dest='config')
    parser.add_argument('-e', '--env',
                        action='store', type=str, dest='env', default=None)
    parser.add_argument(action='store', type=str, dest='command',
                        default='start', choices=('start', 'stop', 'restart'))
    parser.add_argument('--no-fork',
                        action='store_true', dest='no_fork', default=False)
    parser.add_argument('-b', '--bind',
                        action='store', dest='bind', type=str,
                        default=DEFAULT_BIND)
    parser.add_argument('-p', '--port',
                        action='store', dest='port', type=int,
                        default=DEFAULT_PORT)
    parser.add_argument('--enable-majority-read-concern', action='store_true',
                        default=False)
    parser.add_argument('-s', '--server',
                        action='store', dest='server', type=str,
                        default=DEFAULT_SERVER, choices=('auto', 'cheroot', 'wsgiref'))
    parser.add_argument('--version', action='version',
                        version='Mongo Orchestration v' + __version__)
    parser.add_argument('--socket-timeout-ms', action='store',
                        dest='socket_timeout',
                        type=int, default=DEFAULT_SOCKET_TIMEOUT)
    parser.add_argument('--pidfile', action='store', type=str, dest='pidfile',
                        default=PID_FILE)

    cli_args = parser.parse_args(argv)

    if cli_args.env and not cli_args.config:
        print("Specified release '%s' without a config file" % cli_args.env)
        sys.exit(1)
    if cli_args.command == 'stop' or not cli_args.config:
        return cli_args
    try:
        # read config
        with open(cli_args.config, 'r') as fd:
            config = json.loads(fd.read(), object_pairs_hook=SON)
        if not 'releases' in config:
            print("No releases defined in %s" % cli_args.config)
            sys.exit(1)
        releases = config['releases']
        if cli_args.env is not None and cli_args.env not in releases:
            print("Release '%s' is not defined in %s"
                  % (cli_args.env, cli_args.config))
            sys.exit(1)
        cli_args.releases = releases
        return cli_args
    except (IOError):
        print("config file not found")
        sys.exit(1)
    except (ValueError):
        print("config file is corrupted")
        sys.exit(1)


def setup(releases, default_release):
    """setup storages"""
    from mongo_orchestration import set_releases, cleanup_storage
    set_releases(releases, default_release)
    signal.signal(signal.SIGTERM, cleanup_storage)
    signal.signal(signal.SIGINT, cleanup_storage)


def get_app():
    """return bottle app that includes all sub-apps"""
    from bottle import default_app
    default_app.push()
    for module in ("mongo_orchestration.apps.home",
                   "mongo_orchestration.apps.servers",
                   "mongo_orchestration.apps.replica_sets",
                   "mongo_orchestration.apps.sharded_clusters"):
        __import__(module)
    app = default_app.pop()
    return app


class MyDaemon(Daemon):
    """class uses to run server as daemon"""

    def __init__(self, *args, **kwd):
        super(MyDaemon, self).__init__(*args, **kwd)

    def run(self):
        log = logging.getLogger(__name__)

        from bottle import run
        setup(getattr(self.args, 'releases', {}), self.args.env)
        BaseModel.socket_timeout = self.args.socket_timeout
        if self.args.command in ('start', 'restart'):
            print("Starting Mongo Orchestration on port %d..." % self.args.port)
            try:
                log.debug('Starting HTTP server on host: %s; port: %d',
                          self.args.bind, self.args.port)
                run(get_app(), host=self.args.bind, port=self.args.port,
                    debug=False, reloader=False, quiet=not self.args.no_fork,
                    server=self.args.server)
            except Exception:
                traceback.print_exc(file=sys.stdout)
                log.exception('Could not start a new server.')
                raise

    def set_args(self, args):
        self.args = args


def await_connection(host, port):
    """Wait for the mongo-orchestration server to accept connections."""
    for i in range(CONNECT_ATTEMPTS):
        try:
            conn = socket.create_connection((host, port), CONNECT_TIMEOUT)
            conn.close()
            return True
        except (IOError, socket.error):
            time.sleep(1)
    return False


def main(argv=None):
    args = read_env(argv)
    Server.enable_majority_read_concern = args.enable_majority_read_concern
    # Log both to STDOUT and the log file.
    logging.basicConfig(level=logging.DEBUG, filename=LOG_FILE,
                        format=LOGGING_FORMAT)
    log = logging.getLogger(__name__)

    daemon = MyDaemon(os.path.abspath(args.pidfile), timeout=5,
                      stdout=sys.stdout)
    daemon.set_args(args)
    # Set default bind ip for mongo processes using argument from --bind.
    Server.mongod_default['bind_ip'] = args.bind
    if args.command == 'stop':
        daemon.stop()
    if args.command == 'start' and not args.no_fork:
        print('Preparing to start mongo-orchestration daemon')
        pid = daemon.start()
        print('Daemon process started with pid: %d' % pid)
        if not await_connection(host=args.bind, port=args.port):
            print(
                'Could not connect to daemon running on %s:%d (pid: %d) '
                'within %d attempts.'
                % (args.bind, args.port, pid, CONNECT_ATTEMPTS))
            daemon.stop()
    if args.command == 'start' and args.no_fork:
        log.debug('Starting mongo-orchestration in the foreground')
        daemon.run()
    if args.command == 'restart':
        daemon.restart()


if __name__ == "__main__":
    main()
