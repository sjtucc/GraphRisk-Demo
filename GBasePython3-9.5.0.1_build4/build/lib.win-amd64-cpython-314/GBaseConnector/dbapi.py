"""
This module implements some constructors and singletons as required by the
DB API v2.0 (PEP-249).
"""

# Python Db API v2
apilevel = '2.0'
threadsafety = 1
paramstyle = 'pyformat'

import time
import datetime

from . import GBaseConstants

class _DBAPITypeObject(object):

    def __init__(self, *values):
        self.values = values

    def __eq__(self, other):
        if other in self.values:
            return True
        else:
            return False

    def __ne__(self, other):
        if other in self.values:
            return False
        else:
            return True

Date = datetime.date
Time = datetime.time
Timestamp = datetime.datetime

def DateFromTicks(ticks):
    return Date(*time.localtime(ticks)[:3])

def TimeFromTicks(ticks):
    return Time(*time.localtime(ticks)[3:6])

def TimestampFromTicks(ticks):
    return Timestamp(*time.localtime(ticks)[:6])

Binary = bytes

STRING = _DBAPITypeObject(*GBaseConstants.FieldType.get_string_types())
BINARY = _DBAPITypeObject(*GBaseConstants.FieldType.get_binary_types())
NUMBER = _DBAPITypeObject(*GBaseConstants.FieldType.get_number_types())
DATETIME = _DBAPITypeObject(*GBaseConstants.FieldType.get_timestamp_types())
ROWID = _DBAPITypeObject()
