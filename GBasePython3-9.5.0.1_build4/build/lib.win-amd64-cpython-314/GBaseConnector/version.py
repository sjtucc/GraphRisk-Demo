"""GBase Connector/Python version information

The file version.py gets installed and is available after installation
as GBaseConnector.version.
"""

VERSION = (9, 5, 0, '', 1)

if VERSION[3] and VERSION[4]:
    VERSION_TEXT = '{0}.{1}.{2}{3}{4}'.format(*VERSION)
else:
    VERSION_TEXT = '{0}.{1}.{2}'.format(*VERSION[0:3])

VERSION_EXTRA = ''
LICENSE = 'GPLv2 with FOSS License Exception'
EDITION = ''  # Added in package names, after the version
