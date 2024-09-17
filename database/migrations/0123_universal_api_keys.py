# Generated by Django 4.2.11 on 2024-05-30 10:37, manually extended.

from django.db import migrations
from django.db.migrations.state import StateApps


NEW_NAME = "Data Access API Key"

def migrate_access_to_api_keys(apps: StateApps, schema_editor):
    ResearcherOld = apps.get_model('database', 'Researcher')
    ApiKey = apps.get_model('database', 'ApiKey')
    
    # create a new api key for each researcher from their data access api keys
    for researcher in ResearcherOld.objects.all():
        if not researcher.access_key_id or not researcher.access_key_secret:
            # print("Skipping researcher", researcher)
            continue
        
        api_key = ApiKey.objects.create(
            access_key_id=researcher.access_key_id,
            access_key_secret=researcher.access_key_secret,
            is_active=True,
            has_tableau_api_permissions=True,
            researcher=researcher,
            readable_name=NEW_NAME,
        )
        # print("api_key created for", api_key.researcher)


def reverse_migration(apps: StateApps, schema_editor):
    ResearcherOld = apps.get_model('database', 'Researcher')
    ApiKey = apps.get_model('database', 'ApiKey')
    
    # get the api key that was generated for each researcher and add it back to the researcher model
    for researcher in ResearcherOld.objects.all():
        # we are not bothering to handle the case where the researcher has multiple api_keys with this name
        try:
            new_api_key = ApiKey.objects.get(researcher=researcher, readable_name=NEW_NAME)
        except ApiKey.DoesNotExist:
            # print("No api_key found for researcher", researcher)
            continue
        
        researcher.access_key_id = new_api_key.access_key_id
        researcher.access_key_secret = new_api_key.access_key_secret
        researcher.save()
        new_api_key.delete()
        # print("Deleted api_key for researcher, added it back to researcher model", researcher)


class Migration(migrations.Migration):
    
    dependencies = [
        ('database', '0122_remove_participant_enable_heartbeat'),
    ]
    
    operations = [
        migrations.RunPython(migrate_access_to_api_keys, reverse_code=reverse_migration),
        migrations.RemoveField(
            model_name='researcher',
            name='access_key_id',
        ),
        migrations.RemoveField(
            model_name='researcher',
            name='access_key_secret',
        ),
    ]
