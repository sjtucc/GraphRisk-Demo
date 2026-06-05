
"""Django database Backend using GBase Connector/Python.

This Django database backend is heavily based on the GBase backend from Django.

Changes include:
* Support for microseconds (GBase 5.6.3 and later)
* Using INFORMATION_SCHEMA where possible
* Using new defaults for, for example SQL_AUTO_IS_NULL

Requires and comes with GBase Connector/Python v8.0.22 and later:
    http://dev.gbase.com/downloads/connector/python/
"""

import warnings
import sys

from datetime import datetime

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db import utils
from django.utils.functional import cached_property
from django.utils import dateparse, timezone

try:
    import GBaseConnector
    from GBaseConnector.conversion import GBaseConverter, GBaseConverterBase
except ImportError as err:
    raise ImproperlyConfigured(
        "Error loading GBaseConnector module: {0}".format(err))

try:
    from _gbase_connector import datetime_to_gbase, time_to_gbase
except ImportError:
    HAVE_CEXT = False
else:
    HAVE_CEXT = True

from .client import DatabaseClient
from .creation import DatabaseCreation
from .introspection import DatabaseIntrospection
from .validation import DatabaseValidation
from .features import DatabaseFeatures
from .operations import DatabaseOperations
from .schema import DatabaseSchemaEditor


Error = GBaseConnector.Error
DatabaseError = GBaseConnector.DatabaseError
NotSupportedError = GBaseConnector.NotSupportedError
OperationalError = GBaseConnector.OperationalError
ProgrammingError = GBaseConnector.ProgrammingError


def adapt_datetime_with_timezone_support(value):
    # Equivalent to DateTimeField.get_db_prep_value. Used only by raw SQL.
    if settings.USE_TZ:
        if timezone.is_naive(value):
            warnings.warn("GBase received a naive datetime (%s)"
                          " while time zone support is active." % value,
                          RuntimeWarning)
            default_timezone = timezone.get_default_timezone()
            value = timezone.make_aware(value, default_timezone)
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if HAVE_CEXT:
        return datetime_to_gbase(value)
    else:
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")


class CursorWrapper:
    """Wrapper around GBase Connector/Python's cursor class.

    The cursor class is defined by the options passed to GBase
    Connector/Python. If buffered option is True in those options,
    GBaseCursorBuffered will be used.
    """
    codes_for_integrityerror = (
        1048,  # Column cannot be null
        1690,  # BIGINT UNSIGNED value is out of range
        3819,  # CHECK constraint is violated
        4025,  # CHECK constraint failed
    )

    def __init__(self, cursor):
        self.cursor = cursor

    def _adapt_execute_args_dict(self, args):
        if not args:
            return args
        new_args = dict(args)
        for key, value in args.items():
            if isinstance(value, datetime):
                new_args[key] = adapt_datetime_with_timezone_support(value)

        return new_args

    def _adapt_execute_args(self, args):
        if not args:
            return args
        new_args = list(args)
        for i, arg in enumerate(args):
            if isinstance(arg, datetime):
                new_args[i] = adapt_datetime_with_timezone_support(arg)

        return tuple(new_args)

    def execute(self, query, args=None):
        """Executes the given operation

        This wrapper method around the execute()-method of the cursor is
        mainly needed to re-raise using different exceptions.
        """
        if isinstance(args, dict):
            new_args = self._adapt_execute_args_dict(args)
        else:
            new_args = self._adapt_execute_args(args)
        try:
            return self.cursor.execute(query, new_args)
        except GBaseConnector.OperationalError as e:
            if e.args[0] in self.codes_for_integrityerror:
                raise IntegrityError(*tuple(e.args))
            raise

    def executemany(self, query, args):
        """Executes the given operation

        This wrapper method around the executemany()-method of the cursor is
        mainly needed to re-raise using different exceptions.
        """
        try:
            return self.cursor.executemany(query, args)
        except GBaseConnector.OperationalError as e:
            if e.args[0] in self.codes_for_integrityerror:
                raise IntegrityError(*tuple(e.args))
            raise

    def __getattr__(self, attr):
        """Return attribute of wrapped cursor"""
        return getattr(self.cursor, attr)

    def __iter__(self):
        """Returns iterator over wrapped cursor"""
        return iter(self.cursor)


class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'gbase'
    # This dictionary maps Field objects to their associated GBase column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    data_types = {
        'AutoField': 'integer AUTO_INCREMENT',
        'BigAutoField': 'bigint AUTO_INCREMENT',
        'BinaryField': 'longblob',
        'BooleanField': 'bool',
        'CharField': 'varchar(%(max_length)s)',
        'DateField': 'date',
        'DateTimeField': 'datetime',
        'DecimalField': 'numeric(%(max_digits)s, %(decimal_places)s)',
        'DurationField': 'bigint',
        'FileField': 'varchar(%(max_length)s)',
        'FilePathField': 'varchar(%(max_length)s)',
        'FloatField': 'double precision',
        'IntegerField': 'integer',
        'BigIntegerField': 'bigint',
        'IPAddressField': 'char(15)',
        'GenericIPAddressField': 'char(39)',
        'JSONField': 'json',
        'NullBooleanField': 'bool',
        'OneToOneField': 'integer',
        'PositiveBigIntegerField': 'int',
        'PositiveIntegerField': 'int',
        'PositiveSmallIntegerField': 'int',
        'SlugField': 'varchar(%(max_length)s)',
        'SmallAutoField': 'int AUTO_INCREMENT',
        'SmallIntegerField': 'int',
        'TextField': 'longtext',
        'TimeField': 'time',
        'UUIDField': 'char(32)',
    }

    # For these data types:
    # - GBase < 8.0.13 doesn't accept default values and
    #   implicitly treat them as nullable
    # - all versions of GBase doesn't support full width database
    #   indexes
    _limited_data_types = (
        'tinyblob', 'blob', 'mediumblob', 'longblob', 'tinytext', 'text',
        'mediumtext', 'longtext', 'json',
    )

    operators = {
        'exact': '= %s',
        'iexact': 'LIKE %s',
        'contains': 'LIKE BINARY %s',
        'icontains': 'LIKE %s',
        'regex': 'REGEXP BINARY %s',
        'iregex': 'REGEXP %s',
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': 'LIKE BINARY %s',
        'endswith': 'LIKE BINARY %s',
        'istartswith': 'LIKE %s',
        'iendswith': 'LIKE %s',
    }

    # The patterns below are used to generate SQL pattern lookup clauses when
    # the right-hand side of the lookup isn't a raw string (it might be an expression
    # or the result of a bilateral transformation).
    # In those cases, special characters for LIKE operators (e.g. \, *, _) should be
    # escaped on database side.
    #
    # Note: we use str.format() here for readability as '%' is used as a wildcard for
    # the LIKE operator.
    pattern_esc = r"REPLACE(REPLACE(REPLACE({}, '\\', '\\\\'), '%%', '\%%'), '_', '\_')"
    pattern_ops = {
        'contains': "LIKE BINARY CONCAT('%%', {}, '%%')",
        'icontains': "LIKE CONCAT('%%', {}, '%%')",
        'startswith': "LIKE BINARY CONCAT({}, '%%')",
        'istartswith': "LIKE CONCAT({}, '%%')",
        'endswith': "LIKE BINARY CONCAT('%%', {})",
        'iendswith': "LIKE CONCAT('%%', {})",
    }

    isolation_levels = {
        'read uncommitted',
        'read committed',
        'repeatable read',
        'serializable',
    }

    Database = GBaseConnector
    SchemaEditorClass = DatabaseSchemaEditor
    # Classes instantiated in __init__().
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations
    validation_class = DatabaseValidation

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)

        try:
            self._use_pure = self.settings_dict['OPTIONS']['use_pure']
        except KeyError:
            self._use_pure = not HAVE_CEXT

        self.converter = DjangoGBaseConverter() \
            if self.use_pure else DjangoCGBaseConverter()

    def __getattr__(self, attr):
        if attr.startswith("gbase_is"):
            return False
        raise AttributeError

    def get_connection_params(self):
        kwargs = {
            'charset': 'utf8',
            'use_unicode': True,
            'buffered': False,
            'consume_results': True,
        }

        settings_dict = self.settings_dict

        if settings_dict['USER']:
            kwargs['user'] = settings_dict['USER']
        if settings_dict['NAME']:
            kwargs['database'] = settings_dict['NAME']
        if settings_dict['PASSWORD']:
            kwargs['passwd'] = settings_dict['PASSWORD']
        if settings_dict['HOST'].startswith('/'):
            kwargs['unix_socket'] = settings_dict['HOST']
        elif settings_dict['HOST']:
            kwargs['host'] = settings_dict['HOST']
        if settings_dict['PORT']:
            kwargs['port'] = int(settings_dict['PORT'])

        # Raise exceptions for database warnings if DEBUG is on
        kwargs['raise_on_warnings'] = settings.DEBUG

        kwargs['client_flags'] = [
            # Need potentially affected rows on UPDATE
            GBaseConnector.GBaseConstants.ClientFlag.FOUND_ROWS,
        ]
        try:
            kwargs.update(settings_dict['OPTIONS'])
        except KeyError:
            # OPTIONS missing is OK
            pass

        return kwargs

    def get_new_connection(self, conn_params):
        if not self.use_pure:
            conn_params['converter_class'] = DjangoCGBaseConverter
        else:
            conn_params['converter_class'] = DjangoGBaseConverter
        cnx = GBaseConnector.connect(**conn_params)

        return cnx

    def init_connection_state(self):
        assignments = []
        if self.features.is_sql_auto_is_null_enabled:
            # SQL_AUTO_IS_NULL controls whether an AUTO_INCREMENT column on
            # a recently inserted row will return when the field is tested
            # for NULL. Disabling this brings this aspect of GBase in line
            # with SQL standards.
            assignments.append('SET SQL_AUTO_IS_NULL = 0')

        if assignments:
            with self.cursor() as cursor:
                cursor.execute('; '.join(assignments))

        if 'AUTOCOMMIT' in self.settings_dict:
            try:
                self.set_autocommit(self.settings_dict['AUTOCOMMIT'])
            except AttributeError:
                self._set_autocommit(self.settings_dict['AUTOCOMMIT'])

    def create_cursor(self, name=None):
        cursor = self.connection.cursor()
        return CursorWrapper(cursor)

    def _rollback(self):
        try:
            BaseDatabaseWrapper._rollback(self)
        except NotSupportedError:
            pass

    def _set_autocommit(self, autocommit):
        with self.wrap_database_errors:
            self.connection.autocommit = autocommit

    def disable_constraint_checking(self):
        """
        Disable foreign key checks, primarily for use in adding rows with
        forward references. Always return True to indicate constraint checks
        need to be re-enabled.
        """
        with self.cursor() as cursor:
            cursor.execute('SET foreign_key_checks=0')
        return True

    def enable_constraint_checking(self):
        """
        Re-enable foreign key checks after they have been disabled.
        """
        # Override needs_rollback in case constraint_checks_disabled is
        # nested inside transaction.atomic.
        self.needs_rollback, needs_rollback = False, self.needs_rollback
        try:
            with self.cursor() as cursor:
                cursor.execute('SET foreign_key_checks=1')
        finally:
            self.needs_rollback = needs_rollback

    def check_constraints(self, table_names=None):
        """
        Check each table name in `table_names` for rows with invalid foreign
        key references. This method is intended to be used in conjunction with
        `disable_constraint_checking()` and `enable_constraint_checking()`, to
        determine if rows with invalid references were entered while constraint
        checks were off.
        """
        with self.cursor() as cursor:
            if table_names is None:
                table_names = self.introspection.table_names(cursor)
            for table_name in table_names:
                primary_key_column_name = self.introspection.get_primary_key_column(cursor, table_name)
                if not primary_key_column_name:
                    continue
                key_columns = self.introspection.get_key_columns(cursor, table_name)
                for column_name, referenced_table_name, referenced_column_name in key_columns:
                    cursor.execute(
                        """
                        SELECT REFERRING.`%s`, REFERRING.`%s` FROM `%s` as REFERRING
                        LEFT JOIN `%s` as REFERRED
                        ON (REFERRING.`%s` = REFERRED.`%s`)
                        WHERE REFERRING.`%s` IS NOT NULL AND REFERRED.`%s` IS NULL
                        """ % (
                            primary_key_column_name, column_name, table_name,
                            referenced_table_name, column_name, referenced_column_name,
                            column_name, referenced_column_name,
                        )
                    )
                    for bad_row in cursor.fetchall():
                        raise IntegrityError(
                            "The row in table '%s' with primary key '%s' has an invalid "
                            "foreign key: %s.%s contains a value '%s' that does not "
                            "have a corresponding value in %s.%s."
                            % (
                                table_name, bad_row[0], table_name, column_name,
                                bad_row[1], referenced_table_name, referenced_column_name,
                            )
                        )

    def is_usable(self):
        try:
            self.connection.ping()
        except Error:
            return False
        else:
            return True

    @cached_property
    def display_name(self):
        return 'GBase'

    @cached_property
    def data_type_check_constraints(self):
        if self.features.supports_column_check_constraints:
            check_constraints = {
                'PositiveBigIntegerField': '`%(column)s` >= 0',
                'PositiveIntegerField': '`%(column)s` >= 0',
                'PositiveSmallIntegerField': '`%(column)s` >= 0',
            }
            return check_constraints
        return {}

    @cached_property
    def gbase_server_info(self):
        with self.temporary_connection() as cursor:
            cursor.execute('SELECT VERSION()')
            return cursor.fetchone()[0]

    @cached_property
    def gbase_version(self):
        config = self.get_connection_params()
        with GBaseConnector.connect(**config) as conn:
            server_version = conn.get_server_version()
        return server_version

    @cached_property
    def sql_mode(self):
        with self.cursor() as cursor:
            cursor.execute('SELECT @@sql_mode')
            sql_mode = cursor.fetchone()
        return set(sql_mode[0].split(',') if sql_mode else ())

    @property
    def use_pure(self):
        return self._use_pure
        # return not HAVE_CEXT or self._use_pure


class DjangoGBaseConverter(GBaseConverter):
    """Custom converter for Django for GBaseConnection"""
    def _TIME_to_python(self, value, dsc=None):
        """Return GBase TIME data type as datetime.time()

        Returns datetime.time()
        """
        return dateparse.parse_time(value.decode('utf-8'))

    def __DATETIME_to_python(self, value, dsc=None):
        """Connector/Python always returns naive datetime.datetime

        Connector/Python always returns naive timestamps since GBase has
        no time zone support. Since Django needs non-naive, we need to add
        the UTC time zone.

        Returns datetime.datetime()
        """
        if not value:
            return None
        dt = GBaseConverter._DATETIME_to_python(self, value)
        if dt is None:
            return None
        if settings.USE_TZ and timezone.is_naive(dt):
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _safestring_to_gbase(self, value):
        return self._str_to_gbase(value)

    def _safetext_to_gbase(self, value):
        return self._str_to_gbase(value)

    def _safebytes_to_gbase(self, value):
        return self._bytes_to_gbase(value)


class DjangoCGBaseConverter(GBaseConverterBase):
    """Custom converter for Django for CGBaseConnection"""
    def _TIME_to_python(self, value, dsc=None):
        """Return GBase TIME data type as datetime.time()

        Returns datetime.time()
        """
        return dateparse.parse_time(str(value))

    def __DATETIME_to_python(self, value, dsc=None):
        """Connector/Python always returns naive datetime.datetime

        Connector/Python always returns naive timestamps since GBase has
        no time zone support. Since Django needs non-naive, we need to add
        the UTC time zone.

        Returns datetime.datetime()
        """
        if not value:
            return None
        if settings.USE_TZ and timezone.is_naive(value):
            value = value.replace(tzinfo=timezone.utc)
        return value
