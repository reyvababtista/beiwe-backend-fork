from django.db import migrations

from database.schedule_models import WeeklySchedule
from database.study_models import Survey

SQL_GET_TIMINGS = """
SELECT "id", "database_survey"."timings" FROM "database_survey"
""".strip()


def initial_weekly_schedules(*args, **kwargs):
    # We are removing the timings column field and django doesn't like having the attribute accessed
    # without a custom query.

    # Just to be safe we will not use the survey object returned (not worth possible bugs), and
    # in order to avoid a database call for every survey we will grab them all and store them by id.
    surveys_by_id = {s.id: s for s in Survey.objects.all()}

    for survey in Survey.objects.raw(SQL_GET_TIMINGS):
        WeeklySchedule.create_weekly_schedules_from_json(
            survey.timings, surveys_by_id[survey.id]
        )


class Migration(migrations.Migration):

    dependencies = [
        ('database', '0026_auto_20200304_2001'),
    ]

    operations = [
        migrations.RunPython(initial_weekly_schedules),
        migrations.RemoveField(
            model_name='survey',
            name='timings',
        ),
        migrations.RemoveField(
            model_name='surveyarchive',
            name='timings',
        ),
    ]
