# Generated by Django 3.2.23 on 2024-01-27 09:44

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0111_auto_20240118_2311'),
    ]

    operations = [
        migrations.CreateModel(
            name='ParticipantActionLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(db_index=True)),
                ('action', models.TextField()),
                ('participant', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='action_logs', to='database.participant')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
