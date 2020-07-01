import logging
import logging.handlers
import socket
from os import sys, path, name
sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

class loghelper(object):

    logger = None
    @classmethod
    def __init__(self, appname, logpath=None, syslog_server=None):

        # create formatter
        self.formatter = logging.Formatter('%(asctime)s %(name)s - %(levelname)s - %(message)s', "%b %d %H:%M:%S")

        # create logger with 'appname'
        self.logger = logging.getLogger(appname)
        self.logger.setLevel(logging.DEBUG)

        # create file handler and add to logger
        if logpath == None:
            dirsep = '/'
            if name == 'nt':
                dirsep = '\\'
            logpath = '{}{}'.format(path.dirname(path.abspath(__file__)), dirsep)
        self.fh = logging.FileHandler('{}{}.log'.format(logpath, appname))
        self.fh.setLevel(logging.DEBUG)
        self.fh.setFormatter(self.formatter)
        self.logger.addHandler(self.fh)

        # create console handler and add to logger
        self.ch = logging.StreamHandler()
        self.ch.setLevel(logging.DEBUG)
        self.ch.setFormatter(self.formatter)
        self.logger.addHandler(self.ch)

        # create syslog handler and add to logger
        if syslog_server != None:
            self.sh = logging.handlers.SysLogHandler(address=(syslog_server, 514), facility="user", socktype=socket.SOCK_DGRAM)
            self.sh.setLevel(logging.DEBUG)
            self.sh.setFormatter(self.formatter)
            self.logger.addHandler(self.sh)

    @classmethod
    def info(self, message):
        self.logger.info(message)

    @classmethod
    def error(self, message):
        self.logger.error(message)

    @classmethod
    def warning(self, message):
        self.logger.warning(message)

    @classmethod
    def debug(self, message):
        self.logger.debug(message)
