# Generated by Django 3.2.15 on 2022-11-02 11:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0090_auto_20221025_0621'),
    ]

    operations = [
        migrations.AlterField(
            model_name='devicesettings',
            name='check_for_new_surveys_frequency_seconds',
            field=models.PositiveIntegerField(default=3600),
        ),
    ]
