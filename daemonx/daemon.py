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

# This file includes code taken from or based on code from:
# https://github.com/openstack/swift
# and
# http://stackoverflow.com/questions/12676393/creating-python-2-7-daemon-with-pep-3143
#
# When the code was taken from swift (and then possibly modified), it's marked
# by the comment "from swift".

from __future__ import with_statement

from ConfigParser import ConfigParser
from eventlet import Timeout
import errno
import grp
import logging
import logging.handlers
from optparse import OptionParser
import pwd
import os
from random import random
import signal
import socket
import sys
import time


# from swift
class LoggerFileObject(object):
    """
    Used to capture stderr/stdout.
    """

    def __init__(self, logger):
        self.logger = logger

    def write(self, value):
        value = value.strip()
        if value:
            if 'Connection reset by peer' in value:
                self.logger.error('STDOUT: Connection reset by peer')
            else:
                self.logger.error('STDOUT: %s', value)

    def writelines(self, values):
        self.logger.error('STDOUT: %s', '#012'.join(values))

    def close(self):
        pass

    def flush(self):
        pass

    def __iter__(self):
        return self

    def next(self):
        raise IOError(errno.EBADF, 'Bad file descriptor')

    def read(self, size=-1):
        raise IOError(errno.EBADF, 'Bad file descriptor')

    def readline(self, size=-1):
        raise IOError(errno.EBADF, 'Bad file descriptor')

    def tell(self):
        return 0

    def xreadlines(self):
        return self


# from swift
def drop_privileges(user):
    """
    Sets the userid/groupid of the current process, get session leader, etc.

    :param user: User name to change privileges to
    """
    if os.geteuid() == 0:
        groups = [g.gr_gid for g in grp.getgrall() if user in g.gr_mem]
        os.setgroups(groups)
    user = pwd.getpwnam(user)
    os.setgid(user[3])
    os.setuid(user[2])
    os.environ['HOME'] = user[5]
    try:
        os.setsid()
    except OSError:
        pass
    os.chdir('/')   # in case you need to rmdir on where you started the daemon
    os.umask(0o22)  # ensure files are created with the correct privileges


def get_check_progress_time(conf):
    interval = get_interval(conf)
    check_progress_time = int(conf.get('check_progress_time', 0))
    if check_progress_time:
        return max(interval * 1.1, check_progress_time)
    return 0

def get_command_line(command_line, dargs_parser, args_parser):
    """
    Parses the command line.

    Command line should be of the form:
    [common daemon args] command [unique daemon args].

    Returns common daemon args, command, and unique daemon args.
    """
    dargs = dargs_parser.parse_args(command_line)
    command = dargs[1][0]
    if command not in Daemon.commands:
        raise ValueError('Invalid daemon command')
    args = args_parser.parse_args(dargs[1][1:])
    return dargs, command, args


def get_daemon(env):
    return env['daemon_class'](
        env['global_conf'], env['conf_section'], env['pid_file_path'],
        env['dargs'], env['args'])


def get_interval(conf):
    return int(conf.get('interval', 300))


def kill_child_process(pid):
    start_time = time.time()
    while time.time() - start_time < 5:
        try:
            ret = os.waitpid(pid, os.WNOHANG)
        except OSError, e:
            if str(e).find('No such process') == 0:
                raise
            else:
                return
        if ret != (0, 0):
            break
        time.sleep(1)

    if ret == (0, 0):
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError, e:
            if str(e).find('No such process') == 0:
                raise


def kill_children(*args):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    os.killpg(0, signal.SIGTERM)
    sys.exit()


def kill_process(pid):
    try:
        start_time = time.time()
        while time.time() - start_time < 5:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
    except OSError, e:
        if str(e).find('No such process') > 0:
            return

    try:
        start_time = time.time()
        while time.time() - start_time < 5:
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
    except OSError, e:
        if str(e).find('No such process') > 0:
            return

    raise RuntimeError('Unable to kill process %d' % pid)


def get_pid(env):
    """
    Reads and returns the daemon's pid from pid file on disk>

    Returns None on failure.
    """
    try:
        with open(env['pid_file_path'], 'r') as fd:
            pid = int(fd.read().strip())
    except IOError:
        pid = None
    return pid


def get_project_from_conf_path(conf_path):
    if not os.path.isfile(conf_path):
        raise ValueError('File path expected')

    conf_file = os.path.basename(conf_path)

    if not conf_file.endswith('.conf'):
        raise ValueError('Conf file should end with .conf')

    return conf_file[:-len('.conf')]


# from swift
def list_from_csv(comma_separated_str):
    """
    Splits the str given and returns a properly stripped list of the comma
    separated values.
    """
    if comma_separated_str:
        return [v.strip() for v in comma_separated_str.split(',') if v.strip()]
    return []


def parse_run_name():
    """
    Returns the parts of the run name of the daemon.

    The run name should be of the form: project-daemon

    This is used to determine the config location/section name.
    """
    command = os.path.split(sys.argv[0])[1]
    parts = command.split('-')
    if len(parts) != 2:
        raise ValueError()
    return parts


# from swift
def read_config(conf_path):
    """
    Reads a config and returns its sections/values.
    """
    c = ConfigParser()
    if not c.read(conf_path):
        print "Unable to read config from %s" % conf_path
        sys.exit(1)
    conf = {}
    for s in c.sections():
        conf.update({s: dict(c.items(s))})
    conf['__file__'] = conf_path
    return conf


def run_worker(env, run_once=False):
    daemon = get_daemon(env)
    daemon.daemonize()
    if run_once:
        try:
            daemon.run_once()
        finally:
            env['cls'].delete_pid_file(env)
    else:
        daemon.run()
    sys.exit()


class Daemon(object):
    """
    A class for building daemons.

    It takes care of things common to all daemons.
    """

    commands = 'restart run_once start status stop'.split()
    handler4logger = {}

    def __init__(self, global_conf, conf_section, pid_file_path, dargs, args):
        self.global_conf = global_conf
        self.conf_section = conf_section
        self.pid_file_path = pid_file_path
        self.conf = self.global_conf[conf_section]
        self.dargs = dargs
        self.args = args
        self.logger = self.get_logger(self.conf)
        self.interval = get_interval(self.conf)
        self.check_progress_time = get_check_progress_time(self.conf)
        self.last_progress = None

    # from swift
    def capture_stdio(self):
        """
        Log unhandled exceptions, close stdio, capture stdout and stderr.
        """
        # log uncaught exceptions
        sys.excepthook = lambda * exc_info: \
            self.logger.critical('UNCAUGHT EXCEPTION', exc_info=exc_info)

        # FUTURE: make the capture optional?
        sys.stdout = LoggerFileObject(self.logger)
        sys.stderr = LoggerFileObject(self.logger)

    def daemonize(self):
        """
        Daemonizes the current process.
        """
        self.capture_stdio()

    @classmethod
    def delete_pid_file(cls, env):
        if os.path.exists(env['pid_file_path']):
            os.remove(env['pid_file_path'])

    @classmethod
    def get_args_parser(cls):
        """
        Override to parse options unique to your daemon.

        Returns an OptionParser.
        """
        return OptionParser()

    @classmethod
    def get_dargs_parser(cls):
        """
        Returns an OptionParse for options common to all daemons.

        Returns an OptionParser.
        """
        # FUTURE: add things that can be overridden on command line
        parser = OptionParser()
        parser.add_option(
            "--eventlet_patch", action="store_false", dest="eventlet_patch",
            default=False, help="add eventlet patch")
        parser.disable_interspersed_args()
        return parser

    # from swift
    @classmethod
    def get_logger(cls, conf):
        """
        Returns a logger configured from the conf.
        """
        if not conf:
            conf = {}
        name = conf.get('log_name', 'daemonx')
        log_route = conf.get('log_route', name)
        logger = logging.getLogger(log_route)
        logger.propagate = False

        # get_logger will only ever add one SysLog Handler to a logger
        if logger in cls.handler4logger:
            logger.removeHandler(cls.handler4logger[logger])

        # facility for this logger will be set by last call wins
        facility = getattr(
            logging.handlers.SysLogHandler,
            conf.get('log_facility', 'LOG_LOCAL0'),
            logging.handlers.SysLogHandler.LOG_LOCAL0)
        udp_host = conf.get('log_udp_host')
        if udp_host:
            udp_port = int(
                conf.get('log_udp_port',
                logging.handlers.SYSLOG_UDP_PORT))
            handler = logging.handlers.SysLogHandler(
                address=(udp_host, udp_port), facility=facility)
        else:
            log_address = conf.get('log_address', '/dev/log')
            try:
                handler = logging.handlers.SysLogHandler(
                    address=log_address, facility=facility)
            except socket.error, e:
                # Either /dev/log isn't a UNIX socket or it does not exist
                # at all
                if e.errno not in [errno.ENOTSOCK, errno.ENOENT]:
                    raise e
                handler = logging.handlers.SysLogHandler(facility=facility)
        logger.addHandler(handler)
        cls.handler4logger[logger] = handler

        # set the level for the logger
        logger.setLevel(
            getattr(
                logging, conf.get('log_level', 'INFO').upper(), logging.INFO))

        return logger

    @classmethod
    def made_progress(cls, env):
        if not env['check_progress_time']:
            return True

        try:
            stat = os.stat(env['pid_file_path'])
            return time.time() - stat.st_mtime < env['check_progress_time']
        except OSError:
            return True

    @classmethod
    def restart(cls, env):
        """
        Restarts the daemon.
        """
        if env['pid']:
            cls.stop(env)
            env['pid'] = None
        cls.start(env)

    def run(self):
        """
        Runs the daemon.

        It calls run_forever().
        """
        self.run_forever()

    @classmethod
    def run_command(
            cls, conf_path, conf_section, command_line, project=None,
            daemon_name=None):
        """
        Sends the command specified on the command line to the daemon.
        """
        env = {
            'cls': cls,
            'conf_path': conf_path,
            'conf_section': conf_section,
        }

        # read config
        env['global_conf'] = read_config(conf_path)
        env['conf'] = env['global_conf'][conf_section]

        # get project/daemon name
        if not (project and daemon_name):
            project = get_project_from_conf_path(env['conf_path'])
            daemon_name = env['conf_section']

        env['project'] = project
        env['daemon_name'] = daemon_name

        # get/import class from config
        import_target, class_name = \
            env['conf']['class'].rsplit('.', 1)
        module = __import__(import_target, fromlist=[import_target])
        env['daemon_class'] = getattr(module, class_name)

        # parse command line, get command to run on daemon
        dargs_parser = cls.get_dargs_parser()
        args_parser = cls.get_args_parser()
        env['dargs'], env['command'], env['args'] = get_command_line(
            command_line, dargs_parser, args_parser)

        # check command
        if env['command'] not in cls.commands:
            raise ValueError('Invalid command')

        # get user
        env['user'] = env['conf']['user']

        # get pid file path, pid
        env['pid_file_path'] = '/var/run/%s/%s.pid' % \
            (env['project'], env['daemon_name'])

        # create /var/run/project directory if it doesn't exist
        run_dir = '/var/run/%s' % env['project']
        if not os.path.exists(run_dir):
            os.mkdir(run_dir, 0755)
            user = pwd.getpwnam(env['user'])
            os.chown(run_dir, user[2], user[3])

        env['pid'] = get_pid(env)

        # get progress check related values
        env['interval'] = get_interval(env['conf'])
        env['check_progress_time'] = get_check_progress_time(env['conf'])

        if env['check_progress_time']:
            env['progress_sleep_time'] = \
                max(1, .1 * env['check_progress_time'])
        else:
            if env['command'] == 'run_once':
                env['progress_sleep_time'] = 5
            else:
                env['progress_sleep_time'] = .1 * env['interval']

        # drop privs
        drop_privileges(env['user'])

        # run command
        if env['command'] == 'run_once':
            method = getattr(env['daemon_class'], 'start')
            method(env, run_once=True)
        else:
            method = getattr(env['daemon_class'], env['command'])
            method(env)

    @classmethod
    def run_command_from_script(cls):
        """
        Runs the command on the daemon.

        Project and daemon name are determined from the script run.
        """
        project, daemon_name = parse_run_name()
        conf_path = '/etc/%s/%s.conf' % (project, project)
        cls.run_command(
            conf_path, daemon_name, list(sys.argv[1:]), project, daemon_name)

    def run_forever(self):
        """
        Run the daemon forever.

        Sleeps as need be to not run more than once in each interval.

        Calls run_once().
        """
        time.sleep(random() * self.interval)
        while True:
            try:
                self.run_once()
            except Exception:
                self.logger.exception('run_once()')
            time.sleep(self.interval)

    def run_once(self):
        """
        Override this to define what the daemon does.
        """
        raise NotImplementedError('run_once not implemented')

    @classmethod
    def start(cls, env, run_once=False):
        """
        Starts the daemon.
        """
        # check to see if daemon is already running
        if env['pid']:
            print 'Daemon appears to be already running'
            sys.exit()

        # really close stdin, stdout, stderr
        for fd in [0, 1, 2]:
            os.close(fd)

        # daemonize things
        if os.fork() > 0:
            return

        # write pid
        cls.write_pid_file(env)

        class State(object):
            pass

        state = State()

        # fork to watcher and worker processes
        state.pid = os.fork()
        if state.pid > 0:
            # watcher process
            signal.signal(signal.SIGTERM, kill_children)

            while True:
                if not cls.made_progress(env):
                    # kill worker process
                    kill_child_process(state.pid)
                    state.pid = os.fork()
                    if state.pid == 0:
                        # worker process
                        os.utime(env['pid_file_path'], None)
                        run_worker(env, run_once)
                if run_once:
                    try:
                        with Timeout(env['progress_sleep_time']):
                            os.waitpid(state.pid, 0)

                        if not os.path.exists(env['pid_file_path']):
                            sys.exit()
                    except OSError:
                        sys.exit()
                    except Timeout:
                        pass
                else:
                    time.sleep(env['progress_sleep_time'])
        else:
            # worker process
            run_worker(env, run_once)

    @classmethod
    def status(cls, env):
        """
        Prints the status of the daemon.
        """
        if env['pid']:
            print 'Daemon is running with pid: %d' % env['pid']
        else:
            print 'Daemon is not running'

    @classmethod
    def stop(cls, env):
        """
        Stops the daemon.
        """
        if not env['pid']:
            print 'Daemon does not seem to be running'
            return

        kill_process(env['pid'])
        cls.delete_pid_file(env)

    def update_progress_marker(self, force=False):
        if not self.check_progress_time:
            return
        update = False
        if force:
            update = True
        elif not self.last_progress:
            update = True
        elif .1 * self.check_progress_time < time.time() - self.last_progress:
            update = True

        if update:
            try:
                os.utime(self.pid_file_path, None)
            except OSError:
                pass
            self.last_progress = time.time()

    @classmethod
    def write_pid_file(cls, env):
        with open(env['pid_file_path'], 'w+') as fd:
            pid = os.getpid()
            fd.write('%d\n' % pid)
