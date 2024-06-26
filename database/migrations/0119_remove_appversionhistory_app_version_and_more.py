# Generated by Django 4.2.11 on 2024-04-08 05:29

from django.db import migrations, models

# I screwed up the initial implementation of the AppVersionHistory model, but it never generated
# any data so we can just delete it and re-create it.

def create_initial_appversion_history(apps, schema_editor):
    AppVersionHistory = apps.get_model('database', 'AppVersionHistory')
    AppVersionHistory.objects.all().delete()
    
    Participant = apps.get_model('database', 'Participant')
    
    values = ("pk", "last_version_code", "last_version_name", "last_os_version")
    query = Participant.objects.all().values_list(*values)
    bulk_creations = []
    for pk, last_version_code, last_version_name, last_os_version in query:
        bulk_creations.append(AppVersionHistory(
            participant_id=pk,
            app_version_code=(last_version_code or "missing")[:16],
            app_version_name=(last_version_name or "missing")[:16],
            os_version=(last_os_version or "missing")[:16],
        ))
    AppVersionHistory.objects.bulk_create(bulk_creations)


class Migration(migrations.Migration):
    
    dependencies = [
        ('database', '0118_filetoprocess_app_version_appversionhistory'),
    ]
    
    operations = [
        migrations.RemoveField(
            model_name='appversionhistory',
            name='app_version',
        ),
        migrations.AddField(
            model_name='appversionhistory',
            name='app_version_code',
            field=models.CharField(default='migrated', max_length=16),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='appversionhistory',
            name='app_version_name',
            field=models.CharField(default='migrated', max_length=16),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='appversionhistory',
            name='os_version',
            field=models.CharField(default='migrated', max_length=16),
            preserve_default=False,
        ),
        migrations.RunPython(create_initial_appversion_history, reverse_code=migrations.RunPython.noop),
    ]
