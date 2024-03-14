# -*- coding: utf-8 -*-
# Generated by Django 1.11.5 on 2018-04-06 16:14
from django.db import migrations
from django.db.migrations.state import StateApps

from libs.security import generate_hash_and_salt, generate_random_bytestring, generate_random_string


def add_admin_user_if_not_exists(apps: StateApps, schema_editor):
    Researcher = apps.get_model('database', 'Researcher')
    
    if Researcher.objects.count() == 0:
        # these algorithm and iterations values need to be hardcoded for compatibility with the old
        # [bad!] password type
        access_key_secret, access_key_secret_salt = generate_hash_and_salt(
            "sha1", 1000, generate_random_bytestring(64)
        )
        password, salt = generate_hash_and_salt("sha1", 1000, b"abcABC123!@#")
        r = Researcher(
            username="default_admin",
            admin=True,
            password=password.decode(),
            salt=salt.decode(),
            access_key_id=generate_random_string(64),
            access_key_secret=access_key_secret.decode(),
            access_key_secret_salt=access_key_secret_salt.decode(),
        )
        r.save()


class Migration(migrations.Migration):
    
    dependencies = [
        ('database', '0004_study_is_test'),
    ]
    
    operations = [
        migrations.RunPython(add_admin_user_if_not_exists)
    ]
