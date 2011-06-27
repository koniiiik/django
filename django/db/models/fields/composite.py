from django.db.models.fields import Field
from collections import namedtuple
from django.db.models import signals

class VirtualField(Field):
    """
    Base class for field types with no direct database representation.
    """
    def __init__(self, **kwargs):
        kwargs['virtual'] = True
        super(VirtualField, self).__init__(**kwargs)

    def db_type(self, connection):
        return None

    def contribute_to_class(self, cls, name):
        self.set_attributes_from_name(name)
        self.model = cls
        cls._meta.add_field(self)
        # Virtual fields are descriptors; they are not handled
        # individually at instance level.
        setattr(cls, name, self)

    def get_attname_column(self):
        return self.get_attname(), None

    # XXX: Abstraction artifact: Virtual fields in general don't enclose
    # any basic fields. However, the only actual implementation
    # (CompositeField) does. Therefore, to avoid ugly special-casing
    # inside the index creation code, this has been placed here.
    def get_enclosed_fields(self):
        return None

    def __get__(self, instance, owner):
        return None

    def __set__(self, instance, value):
        pass

class CompositeField(VirtualField):
    """
    Virtual field type enclosing several atomic fields into one.
    """
    def __init__(self, *fields, **kwargs):
        self.fields = fields
        super(CompositeField, self).__init__(**kwargs)

    def db_type(self, connection):
        # We want to return a tuple of db_types of enclosed fields for use
        # in SQL generation.
        return tuple(f.db_type(connection) for f in self.fields)

    def contribute_to_class(self, cls, name):
        # If we are a ``unique`` field (but not a primary one),
        # register as unique_together inside the model's _meta.
        if self._unique:
            cls._meta.unique_together.append(tuple(f.name for f in self.fields))

        # We can process the fields only after they've been added to the
        # model class. Parent's contribute_to_class calls
        # get_attname_column which in turn requires fields to be ready,
        # thus we have to delay almost everything.
        def process_enclosed_fields(sender, **kwargs):
            super(CompositeField, self).contribute_to_class(cls, name)

            nt_name = "%s_%s" % (cls.__name__, name)
            nt_fields = " ".join(f.name for f in self.fields)
            self.nt = namedtuple(nt_name, nt_fields)
            setattr(cls, name, self)

        signals.class_prepared.connect(process_enclosed_fields,
                                       sender=cls, weak=False)

    def get_attname_column(self):
        attname = self.get_attname()
        # Again, we return a tuple of enclosed database columns.
        column = tuple(f.column for f in self.fields)
        return attname, column

    def get_enclosed_fields(self):
        return self.fields

    def get_prep_lookup(self, lookup_type, value):
        if lookup_type == 'exact':
            if len(value) != len(self.fields):
                raise ValueError("%s lookup arguments must have length %d; "
                        "the length of %r is %d." % (self.name, len(self.fields),
                        value, len(value)))
            return [f.get_prep_lookup(lookup_type, v)
                    for f, v in zip(self.fields, value)]
        elif lookup_type == 'in':
            return [self.get_prep_lookup('exact', v) for v in value]
        else:
            raise TypeError("Lookup type %r not supported." % lookup_type)

    def get_db_prep_lookup(self, lookup_type, value, connection, prepared=False):
        if lookup_type == 'exact':
            if len(value) != len(self.fields):
                raise ValueError("%s lookup arguments must have length %d; "
                        "the length of %r is %d." % (self.name, len(self.fields),
                        value, len(value)))
            prepared = [f.get_db_prep_lookup(lookup_type, v, connection, prepared)
                        for f, v in zip(self.fields, value)]
            # Since other fields' get_db_prep_lookup return lists, we need
            # to flatten ours.
            return [v for vallist in prepared for v in vallist]
        elif lookup_type == 'in':
            return [self.get_db_prep_lookup('exact', v, connection, prepared)
                    for v in value]
        else:
            raise TypeError("Lookup type %r not supported." % lookup_type)

    def __get__(self, instance, owner):
        if instance is None:
            raise AttributeError("%s can only be retrieved via instance."
                                 % self.name)
        return self.nt._make(getattr(instance, f.name, None) for f in self.fields)

    def __set__(self, instance, value):
        for f, val in zip(self.nt._fields, value):
            setattr(instance, f, val)
