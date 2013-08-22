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
