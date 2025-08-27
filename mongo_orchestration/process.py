#!/usr/bin/python
# coding=utf-8
# Copyright 2012-2014 MongoDB, Inc.
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

import errno
import json
import logging
import os
import platform
import shutil
import stat
import socket
import subprocess
import time
import tempfile

try:
    from subprocess import DEVNULL
except ImportError:
    DEVNULL = open(os.devnull, 'wb')

from mongo_orchestration.common import DEFAULT_BIND, LOG_FILE
from mongo_orchestration.compat import reraise, PY3
from mongo_orchestration.errors import TimeoutError, RequestError
from mongo_orchestration.singleton import Singleton

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class PortPool(Singleton):

    __ports = set()
    __closed = set()
    __id = None

    def __init__(self, min_port=1025, max_port=2000, port_sequence=None):
        """
        Args:
            min_port - min port number  (ignoring if 'port_sequence' is not None)
            max_port - max port number  (ignoring if 'port_sequence' is not None)
            port_sequence - iterate sequence which contains numbers of ports
        """
        with self._lock:
            if not self.__id:  # singleton checker
                self.__id = id(self)
                self.__init_range(min_port, max_port, port_sequence)

    def __init_range(self, min_port=1025, max_port=2000, port_sequence=None):
        if port_sequence:
            self.__ports = set(port_sequence)
        else:
            self.__ports = set(range(min_port, max_port + 1))
        self.__closed = set()
        self.refresh()

    def __check_port(self, port):
        """check port status
        return True if port is free, False else
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((DEFAULT_BIND, port))
            return True
        except socket.error:
            return False
        finally:
            s.close()

    def release_port(self, port):
        """release port"""
        if port in self.__closed:
            self.__closed.remove(port)
        self.__ports.add(port)

    def port(self, check=False):
        """return next opened port
        Args:
          check - check is port really free
        """
        with self._lock:
            if not self.__ports:  # refresh ports if sequence is empty
                self.refresh()

            try:
                while True:
                    port = self.__ports.pop()
                    self.__closed.add(port)
                    if check and not self.__check_port(port):
                        continue
                    return port
            except (IndexError, KeyError):
                raise IndexError("Could not find a free port,\nclosed ports: {closed}".format(closed=self.__closed))

    def refresh(self, only_closed=False):
        """refresh ports status
        Args:
          only_closed - check status only for closed ports
        """
        if only_closed:
            opened = filter(self.__check_port, self.__closed)
            self.__closed = self.__closed.difference(opened)
            self.__ports = self.__ports.union(opened)
        else:
            ports = self.__closed.union(self.__ports)
            self.__ports = set(filter(self.__check_port, ports))
            self.__closed = ports.difference(self.__ports)

    def change_range(self, min_port=1025, max_port=2000, port_sequence=None):
        """change Pool port range"""
        self.__init_range(min_port, max_port, port_sequence)


def connect_port(port):
    """waits while process starts.
    Args:
        proc        - Popen object
        port_num    - port number
        timeout     - specify how long, in seconds, a command can take before times out.
    return True if process started, return False if not
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((DEFAULT_BIND, port))
        s.close()
        return True
    except (IOError, socket.error):
        if s:
            s.close()
        return False


def wait_for(proc, port_num, timeout):
    """waits while process starts.
    Args:
        proc        - Popen object
        port_num    - port number
        timeout     - specify how long, in seconds, a command can take before times out.
    return True if process started, return False if not
    """
    logger.debug("wait for {port_num}".format(**locals()))
    t_start = time.time()
    sleeps = 0.1
    while time.time() - t_start < timeout:
        if proc.poll() is not None:
            logger.debug("process is not alive")
            raise OSError("Process started, but died immediately")
        if connect_port(port_num):
            return True
        time.sleep(sleeps)
    return False


def repair_mongo(name, dbpath):
    """repair mongodb after usafe shutdown"""
    log_file = os.path.join(dbpath, 'mongod.log')
    cmd = [name, "--dbpath", dbpath, "--logpath", log_file, "--logappend",
           "--repair"]
    proc = subprocess.Popen(
        cmd, universal_newlines=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    timeout = 45
    t_start = time.time()
    while time.time() - t_start < timeout:
        line = str(proc.stdout.readline())
        logger.info("repair output: %s" % (line,))
        return_code = proc.poll()
        if return_code is not None:
            if return_code:
                raise Exception("mongod --repair failed with exit code %s, "
                                "check log file: %s" % (return_code, log_file))
            # Success when poll() returns 0
            return
        time.sleep(1)
    proc.terminate()
    raise Exception("mongod --repair failed to exit after %s seconds, "
                    "check log file: %s" % (timeout, log_file))


def mprocess(name, config_path, port=None, timeout=180):
    """start 'name' process with params from config_path.
    Args:
        name - process name or path
        config_path - path to file where should be stored configuration
        port - process's port
        timeout - specify how long, in seconds, a command can take before times out.
                  if timeout <=0 - doesn't wait for complete start process
    return tuple (Popen object, host) if process started, return (None, None) if not
    """

    logger.debug(
        "mprocess(name={name!r}, config_path={config_path!r}, port={port!r}, "
                 "timeout={timeout!r})".format(**locals()))
    if not (config_path and isinstance(config_path, str) and os.path.exists(config_path)):
        raise OSError("can't find config file {config_path}".format(**locals()))

    cfg = read_config(config_path)
    cmd = [name, "--config", config_path]

    if cfg.get('port', None) is None or port:
        port = port or PortPool().port(check=True)
        cmd.extend(['--port', str(port)])
    host = "{host}:{port}".format(host=DEFAULT_BIND, port=port)
    try:
        logger.debug("execute process: %s", ' '.join(cmd))
        # Redirect server startup errors (written to stdout/stderr) to our log
        with open(LOG_FILE, 'a+') as outfile:
            proc = subprocess.Popen(
                cmd,
                stdout=outfile,
                stderr=subprocess.STDOUT)

            if proc.poll() is not None:
                logger.debug("process is not alive")
                raise OSError("Process started, but died immediately.")
    except (OSError, TypeError) as err:
        message = "exception while executing process: {err}".format(err=err)
        logger.debug(message)
        raise OSError(message)
    if timeout > 0:
        if wait_for(proc, port, timeout):
            logger.debug("process '{name}' has started: pid={proc.pid},"
                         " host={host}".format(**locals()))
            return (proc, host)
        else:
            logger.debug("hasn't connected to pid={proc.pid} with host={host}"
                         " during timeout {timeout} ".format(**locals()))
            logger.debug("terminate process with"
                         " pid={proc.pid}".format(**locals()))
            kill_mprocess(proc)
            proc_alive(proc) and time.sleep(3)  # wait while process stoped
            message = ("Could not connect to process during "
                       "{timeout} seconds".format(timeout=timeout))
            raise TimeoutError(message, errno.ETIMEDOUT)
    return (proc, host)


def wait_mprocess(process, timeout):
    """Compatibility function for waiting on a process with a timeout.

    Raises TimeoutError when the timeout is reached.
    """
    if PY3:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(str(exc))

    # On Python 2, simulate the timeout parameter and raise TimeoutError.
    start = time.time()
    while True:
        exit_code = process.poll()
        if exit_code is not None:
            return exit_code
        if time.time() - start > timeout:
            raise TimeoutError("Process %s timed out after %s seconds" %
                               (process.pid, timeout))
        time.sleep(0.05)


def kill_mprocess(process):
    """kill process
    Args:
        process - Popen object for process
    """
    if process and proc_alive(process):
        process.terminate()
        process.communicate()
    return not proc_alive(process)


def cleanup_mprocess(config_path, cfg):
    """remove all process's stuff
    Args:
       config_path - process's options file
       cfg - process's config
    """
    for key in ('keyFile', 'dbpath'):
        remove_path(cfg.get(key, None))
    isinstance(config_path, str) and os.path.exists(config_path) and remove_path(config_path)


def remove_path(path):
    """remove path from file system
    If path is None - do nothing"""
    if path is None or not os.path.exists(path):
        return
    if platform.system() == 'Windows':
        # Need to have write permission before deleting the file.
        os.chmod(path, stat.S_IWRITE)
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            shutil.os.remove(path)
    except OSError:
        logger.exception("Could not remove path: %s" % path)


def write_config(params, config_path=None):
    """write mongo*'s config file
    Args:
       params - options wich file contains
       config_path - path to the config_file, will create if None
    Return config_path
       where config_path - path to mongo*'s options file
    """
    if config_path is None:
        config_path = tempfile.mktemp(prefix="mongo-")

    cfg = params.copy()
    if 'setParameter' in cfg:
        set_parameters = cfg.pop('setParameter')
        try:
            for key, value in set_parameters.items():
                cfg['setParameter = ' + key] = value
        except AttributeError:
            reraise(RequestError,
                    'Not a valid value for setParameter: %r '
                    'Expected "setParameter": {<param name> : value, ...}'
                    % set_parameters)

    # fix boolean value
    for key, value in cfg.items():
        if isinstance(value, bool):
            cfg[key] = json.dumps(value)

    with open(config_path, 'w') as fd:
        data = '\n'.join('%s=%s' % (key, item) for key, item in cfg.items())
        fd.write(data)
    return config_path


def read_config(config_path):
    """read config_path and return options as dictionary"""
    result = {}
    with open(config_path, 'r') as fd:
        for line in fd.readlines():
            if '=' in line:
                key, value = line.split('=', 1)
                try:
                    result[key] = json.loads(value)
                except ValueError:
                    result[key] = value.rstrip('\n')
    return result


def proc_alive(process):
    """Check if process is alive. Return True or False."""
    return process.poll() is None if process else False
