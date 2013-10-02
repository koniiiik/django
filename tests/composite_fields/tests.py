from __future__ import unicode_literals

from datetime import date, datetime, time
from decimal import Decimal
import unittest

from django.test import TestCase, TransactionTestCase
from django.db import connection, IntegrityError
from django.db.models.fields import FieldDoesNotExist
from django.db.transaction import atomic
from django.utils.encoding import force_text

from .models import (Person, PersonWithBirthplace, Song, MostFieldTypes,
    EvenMoreFields, WeekDay, Sentence, SentenceFreq)


class CompositeFieldTests(TestCase):
    def setUp(self):
        self.p1 = PersonWithBirthplace.objects.create(
            first_name='John', last_name='Lennon', birthday=date(1940, 10, 9),
            birthplace='Liverpool',
        )
        self.p2 = Person.objects.create(
            first_name='George', last_name='Harrison', birthday=date(1943, 2, 25),
        )
        PersonWithBirthplace.objects.create(
            first_name='Paul', last_name='McCartney', birthday=date(1942, 6, 18),
            birthplace='Liverpool',
        )
        Person.objects.create(
            first_name='Ringo', last_name='Starr', birthday=date(1940, 7, 7),
        )

    def test_cf_retrieval(self):
        name1 = self.p1.full_name
        self.assertEqual(name1.first_name, 'John')
        self.assertEqual(name1.last_name, self.p1.last_name)

        self.assertEqual(self.p2.full_name.first_name, self.p2.first_name)
        self.assertEqual(self.p2.full_name.last_name, 'Harrison')

    def test_cf_assignment(self):
        self.p1.full_name = ('Keith', 'Sanderson')
        self.assertEqual(self.p1.first_name, 'Keith')
        self.assertEqual(self.p1.last_name, 'Sanderson')

        name2 = self.p2.full_name._replace(first_name='Elliot',
                                           last_name='Roberts')
        self.p2.full_name = name2
        self.assertEqual(self.p2.first_name, name2.first_name)
        self.assertEqual(self.p2.last_name, name2.last_name)

    def test_cf_lookup(self):
        p1 = Person.objects.get(full_name=('John', 'Lennon'))
        self.assertEqual(p1.first_name, self.p1.first_name)
        self.assertEqual(p1.birthday, self.p1.birthday)

        qs = Person.objects.filter(full_name__in=[('John', 'Lennon'),
                                                  ('George', 'Harrison')])
        self.assertEqual(qs.count(), 2)
        self.assertQuerysetEqual(qs, [
            '<Person: George Harrison>',
            '<Person: John Lennon>',
        ])

    def test_cf_order(self):
        qs = Person.objects.order_by('full_name')
        self.assertQuerysetEqual(qs, [
            '<Person: George Harrison>',
            '<Person: John Lennon>',
            '<Person: Paul McCartney>',
            '<Person: Ringo Starr>',
        ])

    def test_cf_primary_key(self):
        # Verify there's no autogenerated ``id`` field.
        self.assertRaises(FieldDoesNotExist, Person._meta.get_field, 'id')

        self.assertEqual(self.p1.pk, ('John', 'Lennon'))

        self.p2.pk = ('Joe', 'Pepitone')
        self.assertEqual(self.p2.first_name, 'Joe')
        self.assertEqual(self.p2.last_name, 'Pepitone')

        qs = Person.objects.filter(pk=('Paul', 'McCartney'))
        self.assertQuerysetEqual(qs, ['<Person: Paul McCartney>'])

        qs = Person.objects.filter(pk__in=[('John', 'Lennon'),
                                           ('George', 'Harrison')])
        self.assertEqual(qs.count(), 2)
        self.assertQuerysetEqual(qs, [
            '<Person: George Harrison>',
            '<Person: John Lennon>',
        ])

    def test_cf_pk_deletion(self):
        self.p1.delete()

        self.assertQuerysetEqual(Person.objects.all(), [
            '<Person: George Harrison>',
            '<Person: Paul McCartney>',
            '<Person: Ringo Starr>',
        ])

        qs = Person.objects.filter(full_name__in=[('George', 'Harrison'),
                                                  ('Paul', 'McCartney')])
        qs.delete()

        self.assertQuerysetEqual(Person.objects.all(), [
            '<Person: Ringo Starr>',
        ])

    def test_composite_val_string_repr(self):
        instance = MostFieldTypes.objects.create(
            bool_field=True,
            char_field="some~unpleasant, string!#%;'",
            date_field=date(2011, 7, 7),
            dtime_field=datetime(2010, 3, 4, 12, 47, 47),
            time_field=time(10, 11, 12),
            dec_field=Decimal('123.4747'),
            float_field=47.474,
            int_field=474747,
        )
        text_repr = force_text(instance.all_fields)
        self.assertEqual(text_repr, "True,some~7Eunpleasant~2C string!#%;',2011-07-07,2010-03-04 12:47:47,10:11:12,123.4747,47.474,474747")
        another = MostFieldTypes(all_fields=text_repr)
        self.assertEqual(instance.all_fields, another.all_fields)

        # We modify the new clone a bit and save it to have something else
        # in the DB.
        another.bool_field=None
        another.char_field='Some;`).,2~other\\/unpleasant&^%#string'
        another.save()
        self.assertNotEqual(instance.pk, another.pk)

        field = MostFieldTypes._meta.get_field('all_fields')
        unpacked = field.to_python(text_repr)
        fetched = MostFieldTypes.objects.get(all_fields=unpacked)
        self.assertEqual(fetched.pk, instance.pk)
        self.assertEqual(fetched.all_fields, instance.all_fields)

        # Query filtering using the text representation of a PK works
        # just as well.
        fetched = MostFieldTypes.objects.get(all_fields=text_repr)
        self.assertEqual(fetched.pk, instance.pk)
        self.assertEqual(fetched.all_fields, instance.all_fields)

    def test_composite_of_related_fields(self):
        tuesday = WeekDay(name='Tuesday', pos=2)
        tuesday.save()
        big_day = Sentence(sentence='? is the big day')
        big_day.save()
        tues_big_day = SentenceFreq(
            weekday=tuesday, sentence=big_day, score=210)
        tues_big_day.save()
        self.assertEqual(tues_big_day.pk, (tuesday.pk, big_day.pk))

    def test_cf_concrete_inheritance(self):
        mft = MostFieldTypes.objects.create(
            bool_field=True,
            char_field="some~unpleasant, string!#%;'",
            date_field=date(2011, 7, 7),
            dtime_field=datetime(2010, 3, 4, 12, 47, 47),
            time_field=time(10, 11, 12),
            dec_field=Decimal('123.4747'),
            float_field=47.474,
            int_field=474747,
        )
        emf = EvenMoreFields.objects.create(
            all_fields=(
                False,
                "a very pleasant string",
                date(2010, 7, 7),
                datetime(2011, 4, 3, 10, 11, 12),
                time(4, 7, 7),
                Decimal('321.4747'),
                74.7,
                747474,
            ),
            extra_field=47,
        )
        self.assertFalse(emf.bool_field)
        self.assertEqual(emf.int_field, 747474)
        self.assertEqual(emf.extra_field, 47)
        self.assertQuerysetEqual(MostFieldTypes.objects.all(), [
            "<MostFieldTypes: char: a very pleasant string; dtime: datetime.datetime(2011, 4, 3, 10, 11, 12); int: 747474>",
            '<MostFieldTypes: char: some~unpleasant, string!#%;\'; dtime: datetime.datetime(2010, 3, 4, 12, 47, 47); int: 474747>',
        ])
        self.assertQuerysetEqual(EvenMoreFields.objects.all(), [
            "<EvenMoreFields: char: a very pleasant string; dtime: datetime.datetime(2011, 4, 3, 10, 11, 12); int: 747474; extra: 47>",
        ])

        emf_parent = MostFieldTypes.objects.exclude(pk=mft.pk).get()
        self.assertEqual(emf_parent.all_fields, emf.all_fields)

    def test_composite_fk_save_retrieve(self):
        s1 = Song(title="Help!", author=self.p1)
        s1.save()
        s1 = Song.objects.get()
        self.assertEqual(s1.author_first_name, "John")
        self.assertEqual(s1.author_last_name, "Lennon")

        s1.author = self.p2
        self.assertEqual(s1.author_id, ('George', 'Harrison'))
        s1.save()
        s1 = Song.objects.get()
        self.assertEqual(s1.author_id, ('George', 'Harrison'))

    def test_composite_select_related(self):
        s1 = Song(title="Help!", author=self.p1)
        s1.save()
        with self.assertNumQueries(1):
            s1 = Song.objects.select_related('author').get()
            self.assertEqual(s1.author.first_name, "John")
            self.assertEqual(s1.author.last_name, "Lennon")

    def test_composite_pk_concrete_inheritance(self):
        self.assertEqual(self.p1.person_ptr_first_name, 'John')
        self.assertEqual(self.p1.person_ptr_last_name, 'Lennon')

        self.assertQuerysetEqual(PersonWithBirthplace.objects.all(), [
            "<PersonWithBirthplace: John Lennon>",
            "<PersonWithBirthplace: Paul McCartney>",
        ])

        self.assertEqual(self.p1.person_ptr_id, self.p1.full_name)
        self.p1.birthday = date(1940, 10, 10)
        self.p1.save()

        john = Person.objects.get(pk=self.p1.pk)
        self.assertEqual(john.birthday, date(1940, 10, 10))
        self.assertEqual(john.personwithbirthplace.birthplace,
                         self.p1.birthplace)

        with self.assertRaises(PersonWithBirthplace.DoesNotExist):
            self.p2.personwithbirthplace


def CompositeFieldTransactionTests(TransactionTestCase):
    @unittest.skipUnless(connection.features.supports_foreign_keys, "No FK support")
    def test_composite_fk_database_constraints(self):
        with self.assertRaises(IntegrityError):
            with atomic():
                Song.objects.create(author_first_name="Unknown",
                                    author_last_name="Artist", title="Help!")

        s = Song.objects.create(author=self.p1, title="Help!")
        s.author_first_name = "John2"
        with self.assertRaises(IntegrityError):
            with atomic():
                s.save()
