# Generated by Django 2.2.14 on 2021-01-28 16:32

import datetime

import django.core.validators
from django.db import migrations, models

from database.schedule_models import AbsoluteSchedule


# due to complex timezone bugs we are simply deleting all absolute schedules from the system
# in this migration.  There were no live deployments other than onnela lab's staging deployment
# at time of writing.
def purge_absolute_schedules(apps, schema_editor):
    AbsoluteSchedule.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0045_auto_20210121_0301'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='participant',
            name='timezone',
        ),
        migrations.RemoveField(
            model_name='study',
            name='timezone',
        ),
        migrations.AddField(
            model_name='absoluteschedule',
            name='date',
            field=models.DateField(default=datetime.date(1900, 1, 1)),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='absoluteschedule',
            name='hour',
            field=models.PositiveIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(23)]),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='absoluteschedule',
            name='minute',
            field=models.PositiveIntegerField(default=0, validators=[django.core.validators.MaxValueValidator(59)]),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='participant',
            name='timezone_name',
            field=models.CharField(default='America/New_York', max_length=256),
        ),
        migrations.AddField(
            model_name='study',
            name='timezone_name',
            field=models.CharField(default='America/New_York', max_length=256),
        ),
        migrations.RemoveField(
            model_name='absoluteschedule',
            name='scheduled_date',
        ),
        migrations.RunPython(purge_absolute_schedules, migrations.RunPython.noop),
    ]