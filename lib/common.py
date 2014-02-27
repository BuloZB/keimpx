#!/usr/bin/env python
# -*- coding: iso-8859-15 -*-
# -*- Mode: python -*-

import binascii
import cmd
import ConfigParser
import glob
import hashlib
import inspect
import logging
import os
import ntpath
import random
import re
import rlcompleter
import shlex
import socket
import string
import sys
import tempfile
import threading
import time
import traceback
import warnings

from optparse import OptionError
from optparse import OptionGroup
from optparse import OptionParser
from struct import pack
from struct import unpack
from subprocess import mswindows
from subprocess import PIPE
from subprocess import Popen
from subprocess import STDOUT
from telnetlib import Telnet
from threading import Lock
from threading import Thread

try:
    import pyreadline as readline
    have_readline = True
except ImportError:
    try:
        import readline
        have_readline = True
    except ImportError:
        have_readline = False

try:
    from impacket import ImpactPacket
    from impacket import nt_errors
    from impacket import ntlm
    from impacket import smbserver
    from impacket import uuid
    from impacket import winregistry
    from impacket.nmb import NetBIOSTimeout
    from impacket.dcerpc import atsvc
    from impacket.dcerpc import dcerpc
    from impacket.dcerpc import ndrutils
    from impacket.dcerpc import srvsvc
    from impacket.dcerpc.samr import *
    from impacket.dcerpc.v5 import epm
    from impacket.dcerpc.v5 import rpcrt
    from impacket.dcerpc.v5 import rrp
    from impacket.dcerpc.v5 import scmr
    from impacket.dcerpc.v5 import srvs
    from impacket.dcerpc.v5 import transport
    from impacket.dcerpc.v5.dtypes import NULL
    from impacket.ese import ESENT_DB
    from impacket.examples import remcomsvc, serviceinstall
    from impacket.smb3structs import SMB2_DIALECT_002
    from impacket.smb3structs import SMB2_DIALECT_21
    from impacket.smbconnection import *
    from impacket.winregistry import hexdump
except ImportError:
    sys.stderr.write('You need to install Python Impacket library first.\nGet it from Core Security\'s Google Code repository:\nsudo apt-get -y remove python-impacket # to remove the system-installed outdated version of the library\ncd /tmp\nsvn checkout http://impacket.googlecode.com/svn/trunk/ impacket\ncd impacket\npython setup.py build\nsudo python setup.py install\n')
    sys.exit(255)

try:
    from Crypto.Cipher import DES, ARC4, AES
    from Crypto.Hash import HMAC, MD4
except ImportError:
    sys.stderr.write('You do not have any crypto installed. You need PyCrypto.\nGet it from http://www.pycrypto.org')
    sys.exit(255)

from lib.exceptions import *
from lib.logger import logger

keimpx_path = ''

class DataStore(object):
    cmd_stdout = ''
    default_reg_key = 'HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProductName'
    server_os = None
    server_name = None
    server_domain = None
    share_path = None
    user_path = 'C:\\'
    version_major = None
    version_minor = None
    writable_share = 'ADMIN$'

def check_dialect(dialect):
    if dialect == SMB_DIALECT:
        return 'SMBv1'
    elif dialect == SMB2_DIALECT_002:
        return 'SMBv2.0'
    elif dialect == SMB2_DIALECT_21:
        return 'SMBv2.1'
    else:
        return 'SMBv3.0'

def read_input(msg, counter):
    while True:
        choice = raw_input(msg)

        if choice == '':
            choice = 1
            break
        elif choice.isdigit() and int(choice) >= 1 and int(choice) <= counter:
            choice = int(choice)
            break
        else:
            logger.warn('The choice must be a digit between 1 and %d' % counter)

    return choice

def remove_comments(lines):
    cleaned_lines = []

    for line in lines:
        # Ignore comment lines and blank ones
        if line.find('#') == 0 or line.isspace() or len(line) == 0:
            continue

        cleaned_lines.append(line)

    return cleaned_lines

def set_verbosity(level=0):
    if isinstance(level, basestring) and level.isdigit():
        level = int(level)

    if level == 0:
        logger.setLevel(logging.WARNING)
    elif level == 1:
        logger.setLevel(logging.INFO)
    elif level > 1:
        logger.setLevel(logging.DEBUG)

class RemoteFile():
    def __init__(self, smb_connection, filename, share='ADMIN$'):
        self.smb = smb_connection
        self.__filename = filename
        self.__share = share
        self.__tid = self.smb.connectTree(self.__share)
        self.__fid = None
        self.__currentOffset = 0

    def open(self):
        self.__fid = self.smb.openFile(self.__tid, self.__filename)

    def seek(self, offset, whence):
        # Implement whence, for now it is always from the beginning of the file
        if whence == 0:
            self.__currentOffset = offset

    def read(self, bytesToRead):
        if bytesToRead > 0:
            data =  self.smb.readFile(self.__tid, self.__fid, self.__currentOffset, bytesToRead)
            self.__currentOffset += len(data)

            return data

        return ''

    def close(self):
        if self.__fid is not None:
            self.smb.closeFile(self.__tid, self.__fid)
            self.smb.deleteFile(self.__share, self.__filename)
            self.__fid = None

    def tell(self):
        return self.__currentOffset

    def __str__(self):
        return '%s\\%s' % (self.__share, self.__filename)

def MD5(data):
    md5 = hashlib.new('md5')
    md5.update(data)

    return md5.digest()
