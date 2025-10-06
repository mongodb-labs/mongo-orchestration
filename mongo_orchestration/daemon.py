#!/usr/bin/env python
# coding=utf-8
# Copyright 2013-2014 MongoDB, Inc.
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

import atexit
import errno
import logging
import os
import subprocess
import sys
import time

from signal import SIGTERM, SIGKILL

DEVNULL = open(os.devnull, 'r+b')

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class Daemon(object):
    """
    A generic daemon class.

    Usage: subclass the Daemon class and override the run() method

    source: http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
    """
    def __init__(self, pidfile,
                 stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                 timeout=0):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile
        self.timeout = timeout  # sleep before exit from parent

    def daemonize(self):
        if os.name == 'nt':
            return self.daemonize_win32()
        else:
            return self.daemonize_posix()

    def daemonize_win32(self):
        logger.info('daemonize_win32: %r' % (sys.argv, ))
        DETACHED_PROCESS = 0x00000008
        pid = subprocess.Popen(sys.argv + ["--no-fork"],
                               creationflags=DETACHED_PROCESS, shell=True,
                               stderr=sys.stderr, stdout=sys.stdout).pid

        try:
            with open(self.pidfile, 'w+') as fd:
                fd.write("%s\n" % pid)
        except:
            logger.exception('write pidfile %r' % self.pidfile)
            raise

        return pid

    def daemonize_posix(self):
        """
        do the UNIX double-fork magic, see Stevens' "Advanced
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        logger.info('daemonize_posix')
        try:
            pid = os.fork()
            if pid > 0:
                logger.debug('forked first child, pid = %d' % (pid,))
                return pid
            logger.debug('in child after first fork, pid = %d' % (pid, ))
        except OSError as error:
            logger.exception('fork #1')
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (error.errno, error.strerror))
            sys.exit(1)

        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0)

        # do second fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                logger.debug('forked second child, pid = %d, exiting' % (pid,))
                sys.exit(0)
        except OSError as error:
            logger.exception('fork #2')
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (error.errno, error.strerror))
            sys.exit(1)

        # redirect standard file descriptors
        logger.info('daemonized, pid = %d' % (pid, ))
        sys.stdin.flush()
        sys.stdout.flush()
        sys.stderr.flush()

        os.dup2(self.stdin.fileno(), sys.stdin.fileno())
        os.dup2(self.stdout.fileno(), sys.stdout.fileno())
        os.dup2(self.stderr.fileno(), sys.stderr.fileno())

        # write pidfile
        atexit.register(self.delpid)
        pid = str(os.getpid())
        with open(self.pidfile, 'w+') as fd:
            fd.write("%s\n" % pid)

    def delpid(self):
        """remove pidfile"""
        os.remove(self.pidfile)

    def start(self):
        """
        Start the daemon
        """
        # Check for a pidfile to see if the daemon already runs
        logger.info('Starting daemon')
        try:
            with open(self.pidfile, 'r') as fd:
                pid = int(fd.read().strip())
        except IOError:
            pid = None

        if pid:
            message = "pidfile %s already exist. Daemon already running?\n"
            sys.stderr.write(message % self.pidfile)
            sys.exit(1)

        # Start the daemon
        pid = self.daemonize()
        if pid:
            return pid
        self.run()

    def stop(self):
        """
        Stop the daemon
        """
        # Get the pid from the pidfile
        logger.debug("reading %s" % (self.pidfile,))
        try:
            with open(self.pidfile, 'r') as fd:
                pid = int(fd.read().strip())
        except IOError:
            logger.exception("reading %s" % (self.pidfile, ))
            pid = None

        if not pid:
            message = "pidfile %s does not exist. Daemon not running?\n"
            sys.stderr.write(message % self.pidfile)
            return  # not an error in a restart

        if os.name == "nt":
            subprocess.call(["taskkill", "/f", "/t", "/pid", str(pid)])

            if os.path.exists(self.pidfile):
                os.remove(self.pidfile)
        else:
            # Try killing the daemon process
            try:
                os.kill(pid, SIGTERM)
                t0 = time.time()
                while is_unix_process_running(pid):
                    time.sleep(0.25)
                    # After 5 seconds resend a SIGTERM to the process.
                    if time.time() - t0 > 5:
                        os.kill(pid, SIGTERM)
                    # After 10 seconds send a SIGKILL to the process.
                    if time.time() - t0 > 10:
                        os.kill(pid, SIGKILL)
            except OSError as err:
                if err.errno == errno.ESRCH:
                    if os.path.exists(self.pidfile):
                        os.remove(self.pidfile)
                else:
                    raise

    def restart(self):
        """
        Restart the daemon
        """
        self.stop()
        self.start()

    def run(self):
        """
        You should override this method when you subclass Daemon. It will be called after the process has been
        daemonized by start() or restart().
        """

def is_unix_process_running(pid):
    """
    Helper function used to determine if a given pid corresponds to a running process.
    This does NOT work on Windows
    """
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            return False
        else:
            raise err
    return True
