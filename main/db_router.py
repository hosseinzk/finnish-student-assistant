"""
Database router to separate tutor data from teacher/exam data.
Tutor models go to 'tutor' database, everything else stays in 'default'.
"""

class TutorDatabaseRouter:
    """
    Routes database operations for tutor-related models to the tutor database.
    """

    # Models that should use the tutor database
    tutor_models = {'tutorchatsession', 'tutorchatmessage'}

    def db_for_read(self, model, **hints):
        """Point tutor models to the tutor database."""
        if model._meta.model_name in self.tutor_models:
            return 'tutor'
        return 'default'

    def db_for_write(self, model, **hints):
        """Point tutor models to the tutor database."""
        if model._meta.model_name in self.tutor_models:
            return 'tutor'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if both objects are in the same database.
        """
        db1 = 'tutor' if obj1._meta.model_name in self.tutor_models else 'default'
        db2 = 'tutor' if obj2._meta.model_name in self.tutor_models else 'default'
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Ensure tutor models only appear in the tutor database,
        and other models only appear in the default database.
        """
        if model_name in self.tutor_models:
            return db == 'tutor'
        return db == 'default'
