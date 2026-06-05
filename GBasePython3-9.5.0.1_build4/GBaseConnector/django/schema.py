from django.db.backends.gbase.schema import DatabaseSchemaEditor as GBaseDatabaseSchemaEditor


class DatabaseSchemaEditor(GBaseDatabaseSchemaEditor):

    def quote_value(self, value):
        self.connection.ensure_connection()
        if isinstance(value, str):
            value = value.replace('%', '%%')
        quoted = self.connection.connection.converter.escape(value)
        if isinstance(value, str) and isinstance(quoted, bytes):
            quoted = quoted.decode()
        return quoted
