# Generated by Django 3.2.16 on 2023-03-21 11:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0100_participant_last_get_latest_device_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='ForestVersion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_on', models.DateTimeField(auto_now_add=True)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('package_version', models.TextField(blank=True, default='')),
                ('git_commit', models.TextField(blank=True, default='')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
