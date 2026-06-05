"""Custom Python types used by GBase Connector/Python"""


import sys


class HexLiteral(str):

    """Class holding GBase hex literals"""

    def __new__(cls, str_, charset='utf8'):
        if sys.version_info[0] == 2:
            hexed = ["%02x" % ord(i) for i in str_.encode(charset)]
        else:
            hexed = ["%02x" % i for i in str_.encode(charset)]
        obj = str.__new__(cls, ''.join(hexed))
        obj.charset = charset
        obj.original = str_
        return obj

    def __str__(self):
        return '0x' + self
