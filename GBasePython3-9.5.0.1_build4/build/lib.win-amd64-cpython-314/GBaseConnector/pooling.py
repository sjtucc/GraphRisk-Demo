"""Implementing pooling of connections to GBase servers.
"""

import re
from uuid import uuid4
# pylint: disable=F0401
try:
    import queue
except ImportError:
    # Python v2
    import Queue as queue
# pylint: enable=F0401
import threading

from . import GBaseError
from .connection import GBaseConnection

CONNECTION_POOL_LOCK = threading.RLock()
CNX_POOL_MAXSIZE = 32
CNX_POOL_MAXNAMESIZE = 64
CNX_POOL_NAMEREGEX = re.compile(r'[^a-zA-Z0-9._:\-*$#]')


def generate_pool_name(**kwargs):
    """Generate a pool name

    This function takes keyword arguments, usually the connection
    arguments for GBaseConnection, and tries to generate a name for
    a pool.

    Raises PoolError when no name can be generated.

    Returns a string.
    """
    parts = []
    for key in ('host', 'port', 'user', 'database'):
        try:
            parts.append(str(kwargs[key]))
        except KeyError:
            pass

    if not parts:
        raise GBaseError.PoolError(
            "Failed generating pool name; specify pool_name")

    return '_'.join(parts)


class PooledGBaseConnection(object):
    """Class holding a GBase Connection in a pool

    PooledGBaseConnection is used by GBaseConnectionPool to return an
    instance holding a GBase connection. It works like a GBaseConnection
    except for methods like close() and config().

    The close()-method will add the connection back to the pool rather
    than disconnecting from the GBase server.

    Configuring the connection have to be done through the GBaseConnectionPool
    method set_config(). Using config() on pooled connection will raise a
    PoolError.
    """
    def __init__(self, pool, cnx):
        """Initialize

        The pool argument must be an instance of GBaseConnectionPoll. cnx
        if an instance of GBaseConnection.
        """
        if not isinstance(pool, GBaseConnectionPool):
            raise AttributeError(
                "pool should be a GBaseConnectionPool")
        if not isinstance(cnx, GBaseConnection):
            raise AttributeError(
                "cnx should be a GBaseConnection")
        self._cnx_pool = pool
        self._cnx = cnx

    def __getattr__(self, attr):
        """Calls attributes of the GBaseConnection instance"""
        return getattr(self._cnx, attr)

    def close(self):
        """Do not close, but add connection back to pool

        The close() method does not close the connection with the
        GBase server. The connection is added back to the pool so it
        can be reused.

        When the pool is configured to reset the session, the session
        state will be cleared by re-authenticating the user.
        """
        try:
            cnx = self._cnx
            if self._cnx_pool.reset_session:
                cnx.reset_session()
        finally:
            self._cnx_pool.add_connection(cnx)
            self._cnx = None

    def config(self, **kwargs):
        """Configuration is done through the pool"""
        raise GBaseError.PoolError(
            "Configuration for pooled connections should "
            "be done through the pool itself."
        )

    @property
    def pool_name(self):
        """Return the name of the connection pool"""
        return self._cnx_pool.pool_name


class GBaseConnectionPool(object):
    """Class defining a pool of GBase connections"""
    def __init__(self, pool_size=5, pool_name=None, pool_reset_session=True,
                 **kwargs):
        """Initialize

        Initialize a GBase connection pool with a maximum number of
        connections set to pool_size. The rest of the keywords
        arguments, kwargs, are configuration arguments for GBaseConnection
        instances.
        """
        self._pool_size = None
        self._pool_name = None
        self._reset_session = pool_reset_session
        self._set_pool_size(pool_size)
        self._set_pool_name(pool_name or generate_pool_name(**kwargs))
        self._cnx_config = {}
        self._cnx_queue = queue.Queue(self._pool_size)
        self._config_version = uuid4()

        if kwargs:
            self.set_config(**kwargs)
            cnt = 0
            while cnt < self._pool_size:
                self.add_connection()
                cnt += 1

    @property
    def pool_name(self):
        """Return the name of the connection pool"""
        return self._pool_name

    @property
    def pool_size(self):
        """Return number of connections managed by the pool"""
        return self._pool_size

    @property
    def reset_session(self):
        """Return whether to reset session"""
        return self._reset_session

    def set_config(self, **kwargs):
        """Set the connection configuration for GBaseConnection instances

        This method sets the configuration used for creating GBaseConnection
        instances. See GBaseConnection for valid connection arguments.

        Raises PoolError when a connection argument is not valid, missing
        or not supported by GBaseConnection.
        """
        if not kwargs:
            return

        with CONNECTION_POOL_LOCK:
            try:
                test_cnx = GBaseConnection()
                if "use_pure" in kwargs:
                    del kwargs["use_pure"]
                test_cnx.config(**kwargs)
                self._cnx_config = kwargs
                self._config_version = uuid4()
            except AttributeError as err:
                raise GBaseError.PoolError(
                    "Connection configuration not valid: {0}".format(err))

    def _set_pool_size(self, pool_size):
        """Set the size of the pool

        This method sets the size of the pool but it will not resize the pool.

        Raises an AttributeError when the pool_size is not valid. Invalid size
        is 0, negative or higher than pooling.CNX_POOL_MAXSIZE.
        """
        if pool_size <= 0 or pool_size > CNX_POOL_MAXSIZE:
            raise AttributeError(
                "Pool size should be higher than 0 and "
                "lower or equal to {0}".format(CNX_POOL_MAXSIZE))
        self._pool_size = pool_size

    def _set_pool_name(self, pool_name):
        r"""Set the name of the pool

        This method checks the validity and sets the name of the pool.

        Raises an AttributeError when pool_name contains illegal characters
        ([^a-zA-Z0-9._\-*$#]) or is longer than pooling.CNX_POOL_MAXNAMESIZE.
        """
        if CNX_POOL_NAMEREGEX.search(pool_name):
            raise AttributeError(
                "Pool name '{0}' contains illegal characters".format(pool_name))
        if len(pool_name) > CNX_POOL_MAXNAMESIZE:
            raise AttributeError(
                "Pool name '{0}' is too long".format(pool_name))
        self._pool_name = pool_name

    def _queue_connection(self, cnx):
        """Put connection back in the queue

        This method is putting a connection back in the queue. It will not
        acquire a lock as the methods using _queue_connection() will have it
        set.

        Raises PoolError on errors.
        """
        if not isinstance(cnx, GBaseConnection):
            raise GBaseError.PoolError(
                "Connection instance not subclass of GBaseConnection.")

        try:
            self._cnx_queue.put(cnx, block=False)
        except queue.Full:
            raise GBaseError.PoolError("Failed adding connection; queue is full")

    def add_connection(self, cnx=None):
        """Add a connection to the pool

        This method instantiates a GBaseConnection using the configuration
        passed when initializing the GBaseConnectionPool instance or using
        the set_config() method.
        If cnx is a GBaseConnection instance, it will be added to the
        queue.

        Raises PoolError when no configuration is set, when no more
        connection can be added (maximum reached) or when the connection
        can not be instantiated.
        """
        with CONNECTION_POOL_LOCK:
            if not self._cnx_config:
                raise GBaseError.PoolError(
                    "Connection configuration not available")

            if self._cnx_queue.full():
                raise GBaseError.PoolError(
                    "Failed adding connection; queue is full")

            if not cnx:
                cnx = GBaseConnection(**self._cnx_config)
                try:
                    if (self._reset_session and self._cnx_config['compress']
                            and cnx.get_server_version() < (5, 7, 3)):
                        raise GBaseError.NotSupportedError("Pool reset session is "
                                                       "not supported with "
                                                       "compression for GBase "
                                                       "server version 5.7.2 "
                                                       "or earlier.")
                except KeyError:
                    pass

                # pylint: disable=W0201,W0212
                cnx._pool_config_version = self._config_version
                # pylint: enable=W0201,W0212
            else:
                if not isinstance(cnx, GBaseConnection):
                    raise GBaseError.PoolError(
                        "Connection instance not subclass of GBaseConnection.")

            self._queue_connection(cnx)

    def get_connection(self):
        """Get a connection from the pool

        This method returns an PooledGBaseConnection instance which
        has a reference to the pool that created it, and the next available
        GBase connection.

        When the GBase connection is not connect, a reconnect is attempted.

        Raises PoolError on errors.

        Returns a PooledGBaseConnection instance.
        """
        with CONNECTION_POOL_LOCK:
            try:
                cnx = self._cnx_queue.get(block=False)
            except queue.Empty:
                raise GBaseError.PoolError(
                    "Failed getting connection; pool exhausted")

            # pylint: disable=W0201,W0212
            if not cnx.is_connected() \
                    or self._config_version != cnx._pool_config_version:
                cnx.config(**self._cnx_config)
                try:
                    cnx.reconnect()
                except GBaseError.InterfaceError:
                    # Failed to reconnect, give connection back to pool
                    self._queue_connection(cnx)
                    raise
                cnx._pool_config_version = self._config_version
            # pylint: enable=W0201,W0212

            return PooledGBaseConnection(self, cnx)

    def _remove_connections(self):
        """Close all connections

        This method closes all connections. It returns the number
        of connections it closed.

        Used mostly for tests.

        Returns int.
        """
        with CONNECTION_POOL_LOCK:
            cnt = 0
            cnxq = self._cnx_queue
            while cnxq.qsize():
                try:
                    cnx = cnxq.get(block=False)
                    cnx.disconnect()
                    cnt += 1
                except queue.Empty:
                    return cnt
                except GBaseError.PoolError:
                    raise
                except GBaseError.Error:
                    # Any other error when closing means connection is closed
                    pass

            return cnt
