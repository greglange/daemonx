# Copyright (c) 2013 Greg Lange
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing
# permissions and limitations under the License.

from daemonx.daemon import Daemon


class Daemon2(Daemon):
    def __init__(self, *args, **kwargs):
        super(Daemon2, self).__init__(*args, **kwargs)
        self.string1 = self.conf['string1']
        self.string2 = self.conf['string2']
        self.string3 = self.global_conf['common1']['string3']

    def run_once(self):
        self.logger.info('%s %s %s' %
            (self.string1, self.string2, self.string3))
