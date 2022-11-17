# Generated by Django 3.2.16 on 2022-11-17 21:34

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0092_auto_20221103_1709'),
    ]

    operations = [
        migrations.CreateModel(
            name='DataAccessRecord',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_on', models.DateTimeField(auto_now_add=True)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('query_params', models.TextField()),
                ('error', models.TextField(blank=True, null=True)),
                ('registry_dict_size', models.PositiveBigIntegerField(blank=True, null=True)),
                ('time_end', models.DateTimeField(blank=True, null=True)),
                ('bytes', models.PositiveBigIntegerField(blank=True, null=True)),
                ('researcher', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='data_access_record', to='database.researcher')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
