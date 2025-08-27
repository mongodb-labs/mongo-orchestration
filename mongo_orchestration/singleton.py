#!/usr/bin/python
# coding=utf-8
# Copyright 2012-2025 MongoDB, Inc.
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
import threading

class Singleton(object):
    _instances = {}
    _lock = threading.Lock()

    def __new__(class_, *args, **kwargs):
        with class_._lock:
            if class_ not in class_._instances:
                class_._instances[class_] = super(Singleton, class_).__new__(class_, *args, **kwargs)
            return class_._instances[class_]
