
from django.db.backends.gbase.features import DatabaseFeatures as GBaseDatabaseFeatures
from django.utils.functional import cached_property


class DatabaseFeatures(GBaseDatabaseFeatures):
    empty_fetchmany_value = []

    @cached_property
    def can_introspect_check_constraints(self):
        return False

    @cached_property
    def supports_microsecond_precision(self):
        return False

    @cached_property
    def can_introspect_foreign_keys(self):
        return False