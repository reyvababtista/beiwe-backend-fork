# Generated by Django 3.2.24 on 2024-03-05 06:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0114_devicestatusreporthistory'),
    ]

    operations = [
        migrations.AlterField(
            model_name='iosdecryptionkey',
            name='file_name',
            field=models.CharField(db_index=True, max_length=90, unique=True),
        ),
    ]
