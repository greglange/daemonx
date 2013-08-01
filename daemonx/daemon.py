# http://stackoverflow.com/questions/12676393/creating-python-2-7-daemon-with-pep-3143

from __future__ import with_statement

from ConfigParser import ConfigParser, NoSectionError, NoOptionError, \
    RawConfigParser
import logging
import logging.handlers
from logging.handlers import SysLogHandler
from optparse import OptionParser
import pwd
import os
from random import random
import signal
import sys
import time


# TODO: taken from swift
class LoggerFileObject(object):
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


# TODO: taken from swift
def drop_privileges(user):
    """
    Sets the userid/groupid of the current process, get session leader, etc.

    :param user: User name to change privileges to
    """
    user = pwd.getpwnam(user)
    if os.geteuid() == 0:
        os.setgroups([])
    os.setgid(user[3])
    os.setuid(user[2])
    os.environ['HOME'] = user[5]
    try:
        os.setsid()
    except OSError:
        pass
    os.chdir('/')   # in case you need to rmdir on where you started the daemon
    os.umask(0o22)  # ensure files are created with the correct privileges


def get_command_line(dargs_parser, args_parser):
    command_line = list(sys.argv[1:])

    command_index = None
    for i, arg in enumerate(command_line):
        if arg in Daemon.commands:
            command_index = i

    if command_index is None:
        print 'Invalid command'
        raise ValueError()

    if dargs_parser:
        dargs = dargs_parser.parse_args(command_line[0:command_index])
    else:
        dargs = None

    if args_parser:
        args = args_parser.parse_args(command_line[command_index + 1:])
    else:
        args = None

    return dargs, command_line[command_index], args


# TODO: miminum get_logger that seems to work
def get_loggerx(conf):
    logger = logging.getLogger('daemon')
    logger.setLevel(logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address='/dev/log')
    logger.addHandler(handler)
    return logger


# TODO: taken from swfit
def list_from_csv(comma_separated_str):
    """
    Splits the str given and returns a properly stripped list of the comma
    separated values.
    """
    if comma_separated_str:
        return [v.strip() for v in comma_separated_str.split(',') if v.strip()]
    return []


def parse_run_name():
    command = os.path.split(sys.argv[0])[1]
    parts = command.split('-')
    if len(parts) != 2:
        raise ValueError()
    return parts


# TODO: taken from swift
def read_config(conf_path):
    c = ConfigParser()
    if not c.read(conf_path):
         print "Unable to read config from %s" % conf_path
         sys.exit(1)
    conf = {}
    for s in c.sections():
        conf.update({s: dict(c.items(s))})
    conf['__file__'] = conf_path
    return conf


class Daemon(object):
    conf_section = 'daemonx'
    commands = 'restart run_once start stop'.split()
    handler4logger = {}

    def __init__(self, global_conf, conf_section, pid_file_path, dargs, args):
        # TODO
        # handle all these things can be overridden on command line

        # TODO
        self.global_conf = global_conf
        self.conf = self.global_conf[conf_section]
        self.pid_file_path = pid_file_path
        self.dargs = dargs
        self.args = args
        # TODO: pass in logger?
        self.logger = self.get_logger(self.conf)
        self.user = self.conf['user']
        self.interval = int(self.conf.get('interval', 5))

    # TODO: taken from swift
    @classmethod
    def capture_stdio(cls):
        """
        Log unhandled exceptions, close stdio, capture stdout and stderr.

        param logger: Logger object to use
        """
        # log uncaught exceptions
        sys.excepthook = lambda * exc_info: \
            self.logger.critical(_('UNCAUGHT EXCEPTION'), exc_info=exc_info)

        # collect stdio file desc not in use for logging
        stdio_files = [sys.stdin, sys.stdout, sys.stderr]

        with open(os.devnull, 'r+b') as nullfile:
            # close stdio (excludes fds open for logging)
            for f in stdio_files:
                # some platforms throw an error when attempting an stdin flush
                try:
                    f.flush()
                except IOError:
                    pass

                try:
                    os.dup2(nullfile.fileno(), f.fileno())
                except OSError:
                    pass

        # TODO: make the capture optional?
        sys.stdout = LoggerFileObject(self.logger)
        sys.stderr = LoggerFileObject(self.logger)

    def daemonize(self):
        try:
            pid = os.fork()
            if pid > 0:
                return False
        except Exception:
            raise RuntimeError('Fork failed')

        drop_privileges(self.user)

        def kill_children(*args):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.killpg(0, signal.SIGTERM)
            sys.exit()

        signal.signal(signal.SIGTERM, kill_children)

        # TODO: something that logs when the daemon is killed?

        self.capture_stdio()

        with open(self.pid_file_path, 'w+') as fd:
            pid = os.getpid()
            fd.write('%d\n' % pid)

        return True

    @classmethod
    def get_args_parser(cls):
        return OptionParser()

    @classmethod
    def get_dargs_parser(cls):
        # TODO: add things that can be overridden on command line
        return OptionParser()

    # TODO: taken from swift
    @classmethod
    def get_logger(cls, conf):
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
            SysLogHandler, conf.get('log_facility', 'LOG_LOCAL0'),
            SysLogHandler.LOG_LOCAL0)
        udp_host = conf.get('log_udp_host')
        if udp_host:
            udp_port = int(conf.get('log_udp_port',
                                    logging.handlers.SYSLOG_UDP_PORT))
            handler = SysLogHandler(address=(udp_host, udp_port),
                                    facility=facility)
        else:
            log_address = conf.get('log_address', '/dev/log')
            try:
                handler = SysLogHandler(address=log_address, facility=facility)
            except socket.error, e:
                # Either /dev/log isn't a UNIX socket or it does not exist
                # at all
                if e.errno not in [errno.ENOTSOCK, errno.ENOENT]:
                    raise e
                handler = SysLogHandler(facility=facility)
        logger.addHandler(handler)
        cls.handler4logger[logger] = handler

        # set the level for the logger
        logger.setLevel(
            getattr(
                logging, conf.get('log_level', 'INFO').upper(), logging.INFO))

        # Setup logger with a StatsD client if so configured
        statsd_host = conf.get('log_statsd_host')
        if statsd_host:
            statsd_port = int(conf.get('log_statsd_port', 8125))
            base_prefix = conf.get('log_statsd_metric_prefix', '')
            default_sample_rate = float(conf.get(
                'log_statsd_default_sample_rate', 1))
            sample_rate_factor = float(conf.get(
                'log_statsd_sample_rate_factor', 1))
            statsd_client = StatsdClient(statsd_host, statsd_port, base_prefix,
                                        name, default_sample_rate,
                                        sample_rate_factor)
            logger.statsd_client = statsd_client
        else:
            logger.statsd_client = None

        return logger

    def get_pid(self):
        try:
            with open(self.pid_file_path, 'r') as fd:
                pid = int(fd.read().strip())
        except IOError:
            pid = None
        return pid

    def run(self):
        # TODO: log when the daemon starts?
        # TODO: be able to specify run_once
        if False:
            self.run_once()
        else:
            self.run_forever()

    @classmethod
    def run_command(cls):
        dargs_parser = Daemon.get_dargs_parser()
        args_parser = Daemon.get_args_parser()

        dargs, command, args = get_command_line(dargs_parser, args_parser)

        project, daemon_name = parse_run_name()
        conf_path = '/etc/%s/%s.conf' % (project, daemon_name)
        global_conf = read_config(conf_path)

        if Daemon.conf_section in global_conf:
            conf = global_conf[Daemon.conf_section]

            print 'a bunch of daemons'
            # spawn a bunch of daemons
            for conf_section in list_from_csv(conf['conf_sections']):
                pid_file_path = '/var/run/%s/%s.pid' % (project, conf_section)
                daemon = Daemon(
                    global_conf, conf_section, pid_file_path, dargs, args)
                method = getattr(daemon, command)
                try:
                    method()
                except Exception, e:
                    print e
        else:
            print 'a single daemon'
            conf_section = daemon_name
            pid_file_path = '/var/run/%s/%s.pid' % (project, daemon_name)
            daemon = Daemon(
                global_conf, conf_section, pid_file_path, dargs, args)

            method = getattr(daemon, command)
            try:
                method()
            except Exception, e:
                print e

    def run_forever(self):
        time.sleep(random() * self.interval)
        while True:
            try:
                self.run_once()
            except Exception:
                # TODO: do something
                pass
            time.sleep(self.interval)

    def restart(self):
        self.stop()
        self.start()

    def run_once(self):
        self.logger.info('pid %d zaxx %d' % (os.getpid(), time.time()))
        print 'pid: %d fez %d' % (os.getpid(), time.time())
        # TODO: override this to define what your daemon does
        # raise NotImplementedError('run_once not implemented')
        pass

    def start(self):
        pid = self.get_pid()
        if pid:
            # TODO
            raise RuntimeError('Daemon alredy running')

        if self.daemonize():
            self.run()

    def stop(self):
        pid = self.get_pid()

        if not pid:
            # TODO: do something
            return

        # TODO
        try:
            # TODO: Timeout?
            while 1:
                os.kill(pid, signal.SIGTERM)
                time.sleep(.1)
        except OSError, e:
            if str(e).find('No such process') > 0:
                if os.path.exists(self.pid_file_path):
                    os.remove(self.pid_file_path)
                else:
                    raise
