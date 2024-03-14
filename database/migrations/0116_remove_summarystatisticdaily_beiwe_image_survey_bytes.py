# Generated by Django 4.2.11 on 2024-03-12 13:09

from django.db import migrations


# image survey was a type that was never fully developed. Any instances of it are to be removed.
def remove_image_survey_chunkregistry(apps, schema_editor):
    ChunkRegistry = apps.get_model('database', 'ChunkRegistry')
    ChunkRegistry.objects.filter(data_type='image_survey').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0115_participant_enable_extensive_device_info_tracking'),
    ]

    operations = [
        migrations.RunPython(remove_image_survey_chunkregistry, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='summarystatisticdaily',
            name='beiwe_image_survey_bytes',
        ),
    ]
