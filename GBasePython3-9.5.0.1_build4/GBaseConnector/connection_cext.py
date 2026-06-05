"""Connection class using the C Extension
"""

# Detection of abstract methods in pylint is not working correctly
#pylint: disable=W0223

import socket

from . import GBaseError, version
from .catch23 import INT_TYPES
from .GBaseConstants import (
    CharacterSet, FieldFlag, ServerFlag, ShutdownType, ClientFlag
)
from .abstracts import GBaseConnectionAbstract, GBaseCursorAbstract
from .protocol import GBaseProtocol

HAVE_CGBASE = False
# pylint: disable=F0401,C0413
try:
    import _gbase_connector
    from .cursor_cext import (
        CGBaseCursor, CGBaseCursorRaw,
        CGBaseCursorBuffered, CGBaseCursorBufferedRaw, CGBaseCursorPrepared,
        CGBaseCursorDict, CGBaseCursorBufferedDict, CGBaseCursorNamedTuple,
        CGBaseCursorBufferedNamedTuple)
    from _gbase_connector import GBaseInterfaceError  # pylint: disable=F0401
except ImportError as exc:
    raise ImportError(
        "GBase Connector/Python C Extension not available ({0})".format(
            str(exc)
        ))
else:
    HAVE_CGBASE = True
# pylint: enable=F0401,C0413


class CGBaseConnection(GBaseConnectionAbstract):

    """Class initiating a GBase Connection using Connector/C"""

    def __init__(self, **kwargs):
        """Initialization"""
        if not HAVE_CGBASE:
            raise RuntimeError(
                "GBase Connector/Python C Extension not available")
        self._cgbase = None
        self._columns = []
        self.converter = None
        super(CGBaseConnection, self).__init__(**kwargs)

        if kwargs:
            self.connect(**kwargs)

    def _add_default_conn_attrs(self):
        """Add default connection attributes"""
        license_chunks = version.LICENSE.split(" ")
        if license_chunks[0] == "GPLv2":
            client_license = "GPL-2.0"
        else:
            client_license = "Commercial"

        self._conn_attrs.update({
            "_connector_name": "gbase-connector-python",
            "_connector_license": client_license,
            "_connector_version": ".".join(
                [str(x) for x in version.VERSION[0:3]]),
            "_source_host": socket.gethostname()
            })

    def _do_handshake(self):
        """Gather information of the GBase server before authentication"""
        self._handshake = {
            'protocol': self._cgbase.get_proto_info(),
            'server_version_original': self._cgbase.get_server_info(),
            'server_threadid': self._cgbase.thread_id(),
            'charset': None,
            'server_status': None,
            'auth_plugin': None,
            'auth_data': None,
            'capabilities': self._cgbase.st_server_capabilities(),
        }

        self._server_version = self._check_server_version(
            self._handshake['server_version_original']
        )

    @property
    def _server_status(self):
        """Returns the server status attribute of GBASE structure"""
        return self._cgbase.st_server_status()

    def set_unicode(self, value=True):
        """Toggle unicode mode

        Set whether we return string fields as unicode or not.
        Default is True.
        """
        self._use_unicode = value
        if self._cgbase:
            self._cgbase.use_unicode(value)
        if self.converter:
            self.converter.set_unicode(value)

    @property
    def autocommit(self):
        """Get whether autocommit is on or off"""
        value = self.info_query("SELECT @@session.autocommit")[0]
        return True if value == 1 else False

    @autocommit.setter
    def autocommit(self, value):  # pylint: disable=W0221
        """Toggle autocommit"""
        try:
            self._cgbase.autocommit(value)
            self._autocommit = value
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)

    @property
    def database(self):
        """Get the current database"""
        return self.info_query("SELECT DATABASE()")[0]

    @database.setter
    def database(self, value):  # pylint: disable=W0221
        """Set the current database"""
        self._cgbase.select_db(value)

    @property
    def in_transaction(self):
        """GBase session has started a transaction"""
        return self._server_status & ServerFlag.STATUS_IN_TRANS

    def _open_connection(self):
        charset_name = CharacterSet.get_info(self._charset_id)[0]
        self._cgbase = _gbase_connector.GBase(  # pylint: disable=E1101,I1101
            buffered=self._buffered,
            raw=self._raw,
            charset_name=charset_name,
            connection_timeout=(self._connection_timeout or 0),
            use_unicode=self._use_unicode,
            auth_plugin=self._auth_plugin)

        if not self.isset_client_flag(ClientFlag.CONNECT_ARGS):
            self._conn_attrs = {}
        cnx_kwargs = {
            'host': self._host,
            'user': self._user,
            'password': self._password,
            'database': self._database,
            'port': self._port,
            'client_flags': self._client_flags,
            'unix_socket': self._unix_socket,
            'compress': self.isset_client_flag(ClientFlag.COMPRESS),
            'ssl_disabled': True,
            "conn_attrs": self._conn_attrs
        }

        tls_versions = self._ssl.get('tls_versions')
        if tls_versions is not None:
            tls_versions.sort(reverse=True)
            tls_versions = ",".join(tls_versions)
        if self._ssl.get('tls_ciphersuites') is not None:
            ssl_ciphersuites = self._ssl.get('tls_ciphersuites')[0]
            tls_ciphersuites = self._ssl.get('tls_ciphersuites')[1]
        else:
            ssl_ciphersuites = None
            tls_ciphersuites = None
        if tls_versions is not None and "TLSv1.3" in tls_versions and \
           not tls_ciphersuites:
            tls_ciphersuites = "TLS_AES_256_GCM_SHA384"
        if not self._ssl_disabled:
            cnx_kwargs.update({
                'ssl_ca': self._ssl.get('ca'),
                'ssl_cert': self._ssl.get('cert'),
                'ssl_key': self._ssl.get('key'),
                'ssl_cipher_suites': ssl_ciphersuites,
                'tls_versions': tls_versions,
                'tls_cipher_suites': tls_ciphersuites,
                'ssl_verify_cert': self._ssl.get('verify_cert') or False,
                'ssl_verify_identity':
                    self._ssl.get('verify_identity') or False,
                'ssl_disabled': self._ssl_disabled
            })

        try:
            self._cgbase.connect(**cnx_kwargs)
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)

        self._do_handshake()

    def close(self):
        """Disconnect from the GBase server"""
        if self._cgbase:
            try:
                self.free_result()
                self._cgbase.close()
            except GBaseInterfaceError as exc:
                raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                     sqlstate=exc.sqlstate)
            self._cgbase = None
    disconnect = close

    def is_connected(self):
        """Reports whether the connection to GBase Server is available"""
        if self._cgbase:
            return self._cgbase.ping()

        return False

    def ping(self, reconnect=False, attempts=1, delay=0):
        """Check availability of the GBase server

        When reconnect is set to True, one or more attempts are made to try
        to reconnect to the GBase server using the reconnect()-method.

        delay is the number of seconds to wait between each retry.

        When the connection is not available, an InterfaceError is raised. Use
        the is_connected()-method if you just want to check the connection
        without raising an error.

        Raises InterfaceError on errors.
        """
        errmsg = "Connection to GBase is not available"

        try:
            connected = self._cgbase.ping()
        except AttributeError:
            pass  # Raise or reconnect later
        else:
            if connected:
                return

        if reconnect:
            self.reconnect(attempts=attempts, delay=delay)
        else:
            raise GBaseError.InterfaceError(errmsg)

    def set_character_set_name(self, charset):
        """Sets the default character set name for current connection.
        """
        self._cgbase.set_character_set(charset)

    def info_query(self, query):
        """Send a query which only returns 1 row"""
        self._cgbase.query(query)
        first_row = ()
        if self._cgbase.have_result_set:
            first_row = self._cgbase.fetch_row()
            if self._cgbase.fetch_row():
                self._cgbase.free_result()
                raise GBaseError.InterfaceError(
                    "Query should not return more than 1 row")
        self._cgbase.free_result()

        return first_row

    @property
    def connection_id(self):
        """GBase connection ID"""
        try:
            return self._cgbase.thread_id()
        except GBaseInterfaceError:
            pass  # Just return None

        return None

    def get_rows(self, count=None, binary=False, columns=None, raw=None,
                 prep_stmt=None):
        """Get all or a subset of rows returned by the GBase server"""
        unread_result = prep_stmt.have_result_set if prep_stmt \
            else self.unread_result
        if not (self._cgbase and unread_result):
            raise GBaseError.InternalError("No result set available")

        if raw is None:
            raw = self._raw

        rows = []
        if count is not None and count <= 0:
            raise AttributeError("count should be 1 or higher, or None")

        counter = 0
        try:
            row = prep_stmt.fetch_row() if prep_stmt \
                else self._cgbase.fetch_row()
            while row:
                if not self._raw and self.converter:
                    row = list(row)
                    for i, _ in enumerate(row):
                        if not raw:
                            row[i] = self.converter.to_python(self._columns[i],
                                                              row[i])
                    row = tuple(row)
                rows.append(row)
                counter += 1
                if count and counter == count:
                    break
                row = prep_stmt.fetch_row() if prep_stmt \
                        else self._cgbase.fetch_row()
            if not row:
                _eof = self.fetch_eof_columns(prep_stmt)['eof']
                if prep_stmt:
                    prep_stmt.free_result()
                    self._unread_result = False
                else:
                    self.free_result()
            else:
                _eof = None
        except GBaseInterfaceError as exc:
            if prep_stmt:
                prep_stmt.free_result()
                raise GBaseError.InterfaceError(str(exc))
            else:
                self.free_result()
                raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                     sqlstate=exc.sqlstate)

        return rows, _eof

    def get_row(self, binary=False, columns=None, raw=None, prep_stmt=None):
        """Get the next rows returned by the GBase server"""
        try:
            rows, eof = self.get_rows(count=1, binary=binary, columns=columns,
                                      raw=raw, prep_stmt=prep_stmt)
            if rows:
                return (rows[0], eof)
            return (None, eof)
        except IndexError:
            # No row available
            return (None, None)

    def next_result(self):
        """Reads the next result"""
        if self._cgbase:
            self._cgbase.consume_result()
            return self._cgbase.next_result()
        return None

    def free_result(self):
        """Frees the result"""
        if self._cgbase:
            self._cgbase.free_result()

    def commit(self):
        """Commit current transaction"""
        if self._cgbase:
            self._cgbase.commit()

    def rollback(self):
        """Rollback current transaction"""
        if self._cgbase:
            self._cgbase.consume_result()
            self._cgbase.rollback()

    def cmd_init_db(self, database):
        """Change the current database"""
        try:
            self._cgbase.select_db(database)
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)

    def fetch_eof_columns(self, prep_stmt=None):
        """Fetch EOF and column information"""
        have_result_set = prep_stmt.have_result_set if prep_stmt \
            else self._cgbase.have_result_set
        if not have_result_set:
            raise GBaseError.InterfaceError("No result set")

        fields = prep_stmt.fetch_fields() if prep_stmt \
            else self._cgbase.fetch_fields()
        self._columns = []
        for col in fields:
            self._columns.append((
                col[4],
                int(col[8]),
                None,
                None,
                None,
                None,
                ~int(col[9]) & FieldFlag.NOT_NULL,
                int(col[9])
            ))

        return {
            'eof': {
                'status_flag': self._server_status,
                'warning_count': self._cgbase.st_warning_count(),
            },
            'columns': self._columns,
        }

    def fetch_eof_status(self):
        """Fetch EOF and status information"""
        if self._cgbase:
            return {
                'warning_count': self._cgbase.st_warning_count(),
                'field_count': self._cgbase.st_field_count(),
                'insert_id': self._cgbase.insert_id(),
                'affected_rows': self._cgbase.affected_rows(),
                'server_status': self._server_status,
            }

        return None

    def cmd_stmt_prepare(self, statement):
        """Prepares the SQL statement"""
        if not self._cgbase:
            raise GBaseError.OperationalError("GBase Connection not available")

        try:
            return self._cgbase.stmt_prepare(statement)
        except GBaseInterfaceError as err:
            raise GBaseError.InterfaceError(str(err))

    # pylint: disable=W0221
    def cmd_stmt_execute(self, prep_stmt, *args):
        """Executes the prepared statement"""
        try:
            prep_stmt.stmt_execute(*args)
        except GBaseInterfaceError as err:
            raise GBaseError.InterfaceError(str(err))

        self._columns = []
        if not prep_stmt.have_result_set:
            # No result
            self._unread_result = False
            return self.fetch_eof_status()

        self._unread_result = True
        return self.fetch_eof_columns(prep_stmt)

    def cmd_stmt_close(self, prep_stmt):
        """Closes the prepared statement"""
        if self._unread_result:
            raise GBaseError.InternalError("Unread result found")
        prep_stmt.stmt_close()

    def cmd_stmt_reset(self, prep_stmt):
        """Resets the prepared statement"""
        if self._unread_result:
            raise GBaseError.InternalError("Unread result found")
        prep_stmt.stmt_reset()
    # pylint: enable=W0221

    def cmd_query(self, query, raw=None, buffered=False, raw_as_string=False):
        """Send a query to the GBase server"""
        self.handle_unread_result()
        if raw is None:
            raw = self._raw
        try:
            if not isinstance(query, bytes):
                query = query.encode('utf-8')
            self._cgbase.query(query,
                               raw=raw, buffered=buffered,
                               raw_as_string=raw_as_string)
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(exc.errno, msg=exc.msg,
                                                 sqlstate=exc.sqlstate)
        except AttributeError:
            if self._unix_socket:
                addr = self._unix_socket
            else:
                addr = self._host + ':' + str(self._port)
            raise GBaseError.OperationalError(
                errno=2055, values=(addr, 'Connection not available.'))

        self._columns = []
        if not self._cgbase.have_result_set:
            # No result
            return self.fetch_eof_status()

        return self.fetch_eof_columns()
    _execute_query = cmd_query

    def cursor(self, buffered=None, raw=None, prepared=None, cursor_class=None,
               dictionary=None, named_tuple=None):
        """Instantiates and returns a cursor using C Extension

        By default, CGBaseCursor is returned. Depending on the options
        while connecting, a buffered and/or raw cursor is instantiated
        instead. Also depending upon the cursor options, rows can be
        returned as dictionary or named tuple.

        Dictionary and namedtuple based cursors are available with buffered
        output but not raw.

        It is possible to also give a custom cursor through the
        cursor_class parameter, but it needs to be a subclass of
        GBaseConnector.cursor_cext.CGBaseCursor.

        Raises ProgrammingError when cursor_class is not a subclass of
        CursorBase. Raises ValueError when cursor is not available.

        Returns instance of CGBaseCursor or subclass.

        :param buffered: Return a buffering cursor
        :param raw: Return a raw cursor
        :param prepared: Return a cursor which uses prepared statements
        :param cursor_class: Use a custom cursor class
        :param dictionary: Rows are returned as dictionary
        :param named_tuple: Rows are returned as named tuple
        :return: Subclass of CGBaseCursor
        :rtype: CGBaseCursor or subclass
        """
        self.handle_unread_result(prepared)
        if not self.is_connected():
            raise GBaseError.OperationalError("GBase Connection not available.")
        if cursor_class is not None:
            if not issubclass(cursor_class, GBaseCursorAbstract):
                raise GBaseError.ProgrammingError(
                    "Cursor class needs be to subclass"
                    " of cursor_cext.CGBaseCursor")
            return (cursor_class)(self)

        buffered = buffered or self._buffered
        raw = raw or self._raw

        cursor_type = 0
        if buffered is True:
            cursor_type |= 1
        if raw is True:
            cursor_type |= 2
        if dictionary is True:
            cursor_type |= 4
        if named_tuple is True:
            cursor_type |= 8
        if prepared is True:
            cursor_type |= 16

        types = {
            0: CGBaseCursor,  # 0
            1: CGBaseCursorBuffered,
            2: CGBaseCursorRaw,
            3: CGBaseCursorBufferedRaw,
            4: CGBaseCursorDict,
            5: CGBaseCursorBufferedDict,
            8: CGBaseCursorNamedTuple,
            9: CGBaseCursorBufferedNamedTuple,
            16: CGBaseCursorPrepared
        }
        try:
            return (types[cursor_type])(self)
        except KeyError:
            args = ('buffered', 'raw', 'dictionary', 'named_tuple', 'prepared')
            raise ValueError('Cursor not available with given criteria: ' +
                             ', '.join([args[i] for i in range(5)
                                        if cursor_type & (1 << i) != 0]))

    @property
    def num_rows(self):
        """Returns number of rows of current result set"""
        if not self._cgbase.have_result_set:
            raise GBaseError.InterfaceError("No result set")

        return self._cgbase.num_rows()

    @property
    def warning_count(self):
        """Returns number of warnings"""
        if not self._cgbase:
            return 0

        return self._cgbase.warning_count()

    @property
    def result_set_available(self):
        """Check if a result set is available"""
        if not self._cgbase:
            return False

        return self._cgbase.have_result_set

    @property
    def unread_result(self):
        """Check if there are unread results or rows"""
        return self.result_set_available

    @property
    def more_results(self):
        """Check if there are more results"""
        return self._cgbase.more_results()

    def prepare_for_gbase(self, params):
        """Prepare parameters for statements

        This method is use by cursors to prepared parameters found in the
        list (or tuple) params.

        Returns dict.
        """
        if isinstance(params, (list, tuple)):
            result = self._cgbase.convert_to_gbase(*params)
        elif isinstance(params, dict):
            result = {}
            for key, value in params.items():
                result[key] = self._cgbase.convert_to_gbase(value)[0]
        else:
            raise ValueError("Could not process parameters")

        return result

    def consume_results(self):
        """Consume the current result

        This method consume the result by reading (consuming) all rows.
        """
        self._cgbase.consume_result()

    def cmd_change_user(self, username='', password='', database='',
                        charset=45):
        """Change the current logged in user"""
        try:
            self._cgbase.change_user(username, password, database)
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)

        self._charset_id = charset
        self._post_connection()

    def cmd_refresh(self, options):
        """Send the Refresh command to the GBase server"""
        try:
            self._cgbase.refresh(options)
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)

        return self.fetch_eof_status()

    def cmd_quit(self):
        """Close the current connection with the server"""
        self.close()

    def cmd_shutdown(self, shutdown_type=None):
        """Shut down the GBase Server"""
        if not self._cgbase:
            raise GBaseError.OperationalError("GBase Connection not available")

        if shutdown_type:
            if not ShutdownType.get_info(shutdown_type):
                raise GBaseError.InterfaceError("Invalid shutdown type")
            level = shutdown_type
        else:
            level = ShutdownType.SHUTDOWN_DEFAULT

        try:
            self._cgbase.shutdown(level)
        except GBaseInterfaceError as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)
        self.close()

    def cmd_statistics(self):
        """Return statistics from the GBase server"""
        self.handle_unread_result()

        try:
            stat = self._cgbase.stat()
            return GBaseProtocol().parse_statistics(stat, with_header=False)
        except (GBaseInterfaceError, GBaseError.InterfaceError) as exc:
            raise GBaseError.get_gbase_exception(msg=exc.msg, errno=exc.errno,
                                                 sqlstate=exc.sqlstate)

    def cmd_process_kill(self, gbase_pid):
        """Kill a GBase process"""
        if not isinstance(gbase_pid, INT_TYPES):
            raise ValueError("GBase PID must be int")
        self.info_query("KILL {0}".format(gbase_pid))

    def handle_unread_result(self, prepared=False):
        """Check whether there is an unread result"""
        unread_result = self._unread_result if prepared is True \
            else self.unread_result
        if self.can_consume_results:
            self.consume_results()
        elif unread_result:
            raise GBaseError.InternalError("Unread result found")
