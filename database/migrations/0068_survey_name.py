# Generated by Django 2.2.25 on 2022-02-18 03:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0067_auto_20220215_1932'),
    ]

    operations = [
        migrations.AddField(
            model_name='survey',
            name='name',
            field=models.TextField(blank=True, default=''),
        ),
    ]