from distutils.core import Extension
import os
import sys

from cpy_distutils import (
    Install, InstallLib, BuildExtDynamic, BuildExtStatic
)

# Development Status Trove Classifiers significant for Connector/Python
DEVELOPMENT_STATUSES = {
    'a': '3 - Alpha',
    'b': '4 - Beta',
    'rc': '4 - Beta',  # There is no Classifier for Release Candidates
    '': '5 - Production/Stable'
}

if not (((2, 6) <= sys.version_info < (3, 0)) or sys.version_info >= (3, 3)):
    raise RuntimeError("Python v{major}.{minor} is not supported".format(
        major=sys.version_info[0], minor=sys.version_info[1]
    ))

# Load version information
#VERSION = [999, 0, 0, 'a', 0]  # Set correct after version.py is loaded
#version_py = os.path.join('lib', 'gbase', 'connector', 'version.py')
#with open(version_py, 'rb') as fp:
    #exec(compile(fp.read(), version_py, 'exec'))

BuildExtDynamic.min_connector_c_version = (5, 5, 8)
command_classes = {
    'build_ext': BuildExtDynamic,
    'build_ext_static': BuildExtStatic,
    'install_lib': InstallLib,
    'install': Install,
}

package_dir = {'1': '2'}
name = 'gbase-connector-python'
#version = '{0}.{1}.{2}'.format(*VERSION[0:3])
version = '9.5.0'
gbasexpb_macros = [("PY3", 1,)] if sys.version_info[0] == 3 else []
extensions = [
    Extension("_gbase_connector",
              sources=[
                  "src/exceptions.c",
                  "src/gbase_capi.c",
                  "src/gbase_capi_conversion.c",
                  "src/gbase_connector.c",
                  "src/force_cpp_linkage.cc",
              ],
              include_dirs=['src/include']),
    Extension(name="_gbasexpb",
              define_macros=gbasexpb_macros,
              sources=[
                  "src/gbasexpb/gbasex/gbasex.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_connection.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_crud.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_cursor.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_datatypes.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_expect.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_expr.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_notice.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_prepare.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_resultset.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_session.pb.cc",
                  "src/gbasexpb/gbasex/gbasex_sql.pb.cc",
                  "src/gbasexpb/gbasexpb.cc"
              ])
]

packages = [
    'GBaseConnector',
    'GBaseConnector.locales',
    'GBaseConnector.locales.eng',
]

description = "GBase driver written in Python"
long_description = """
GBase driver written in Python which does not depend on GBase C client
libraries and implements the DB API v2.0 specification (PEP-249).
"""
author = ''
author_email = ''
maintainer = ''
maintainer_email = ''
cpy_gpl_license = "GNU GPLv2 (with FOSS License Exception)"
keywords = "gbase db"
url = 'http://dev.gbase.com/doc/connector-python/en/index.html'
download_url = 'http://dev.gbase.com/downloads/connector/python/'
classifiers = [
    'Development Status :: %s',
    'Environment :: Other Environment',
    'Intended Audience :: Developers',
    'Intended Audience :: Education',
    'Intended Audience :: Information Technology',
    'Intended Audience :: System Administrators',
    'License :: OSI Approved :: GNU General Public License (GPL)',
    'Operating System :: OS Independent',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
    'Programming Language :: Python :: 3.7',
    'Programming Language :: Python :: 3.8',
    'Topic :: Database',
    'Topic :: Software Development',
    'Topic :: Software Development :: Libraries :: Application Frameworks',
    'Topic :: Software Development :: Libraries :: Python Modules'
]
install_requires = ["protobuf>=3.0.0"],
extras_require = {"dns-srv": ["dnspython>=1.16.0"]}
