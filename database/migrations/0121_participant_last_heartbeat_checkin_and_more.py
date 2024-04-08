# Generated by Django 4.2.11 on 2024-04-08 22:05

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0120_devicesettings_heartbeat_message_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='last_heartbeat_checkin',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='devicesettings',
            name='heartbeat_timer_minutes',
            field=models.PositiveIntegerField(default=60, validators=[django.core.validators.MinValueValidator(1)]),
        ),
    ]
