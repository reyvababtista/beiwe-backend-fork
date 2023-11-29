# Generated by Django 3.2.23 on 2023-11-28 01:42

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0107_alter_devicesettings_consent_form_text'),
    ]

    operations = [
        migrations.CreateModel(
            name='GlobalSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_on', models.DateTimeField(auto_now_add=True)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('downtime_enabled', models.BooleanField(default=False)),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.RemoveField(
            model_name='foresttask',
            name='forest_param',
        ),
        migrations.RemoveField(
            model_name='foresttask',
            name='params_dict_cache',
        ),
        migrations.RemoveField(
            model_name='study',
            name='is_test',
        ),
        migrations.AddField(
            model_name='foresttask',
            name='forest_commit',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='foresttask',
            name='output_zip_s3_path',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='foresttask',
            name='pickled_parameters',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='summarystatisticdaily',
            name='oak_cadence',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='summarystatisticdaily',
            name='oak_steps',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='summarystatisticdaily',
            name='oak_task',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='oak_summary_statistics', to='database.foresttask'),
        ),
        migrations.AddField(
            model_name='summarystatisticdaily',
            name='oak_walking_time',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='summarystatisticdaily',
            name='willow_uniq_individual_call_or_text_count',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='foresttask',
            name='forest_tree',
            field=models.TextField(choices=[('jasmine', 'Jasmine'), ('oak', 'Oak'), ('sycamore', 'Sycamore'), ('willow', 'Willow')]),
        ),
        migrations.AlterField(
            model_name='foresttask',
            name='forest_version',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
        migrations.DeleteModel(
            name='ForestParameters',
        ),
    ]
