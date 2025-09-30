#!/usr/bin/python
# coding=utf-8
# Copyright 2023 MongoDB, Inc.
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
import os
import shlex
import pexpect
import subprocess
import unittest

def run(cmd, **kwargs):
    proc = subprocess.run(shlex.split(cmd), **kwargs)
    if proc.returncode != 0:
        raise RuntimeError('Process failed!')


class TestLaunch(unittest.TestCase):

    def test_launch_single(self):
        if os.name != 'posix':
            raise unittest.SkipTest('Only works on posix!')
        run('mongo-orchestration start')
        proc = pexpect.spawn('mongo-launch', ['single'])
        proc.expect('Type "q" to quit:')
        proc.send('q\n')
        proc.wait()
        self.assertEqual(proc.exitstatus, 0)
        run('mongo-orchestration stop')

    def test_launch_replica_set(self):
        if os.name != 'posix':
            raise unittest.SkipTest('Only works on posix!')
        run('mongo-orchestration start')
        proc = pexpect.spawn('mongo-launch', ['replicaset', 'ssl'])
        proc.expect('"r" to shutdown and restart the primary')
        proc.send('q\n')
        proc.wait()
        self.assertEqual(proc.exitstatus, 0)
        run('mongo-orchestration stop')

    def test_launch_sharded(self):
        if os.name != 'posix':
            raise unittest.SkipTest('Only works on posix!')
        run('mongo-orchestration start')
        proc = pexpect.spawn('mongo-launch', ['shard', 'auth'])
        proc.expect('Type "q" to quit:')
        proc.send('q\n')
        proc.wait()
        self.assertEqual(proc.exitstatus, 0)
        run('mongo-orchestration stop')