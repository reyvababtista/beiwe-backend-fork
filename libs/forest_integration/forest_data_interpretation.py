import csv
from io import StringIO
from datetime import date, datetime

from database.study_models import Study
from database.tableau_api_models import SummaryStatisticDaily
from database.user_models import Participant



# alternative architecture:
#   no interpretation function, just a dictionary from tuples of (tree, column) to summary statistic
#   field name. ie {('gps', 'missing_time'): 'gps_data_missing_duration', ...}
# key considerations:
#    -much less code, more DRY
#    -possibly simpler to maintain (add a few dict entries instead of a new function)
#    -not customizable for things like unit conversions or multiple forest output fields
#     corresponding to a single summary statistic. might break later if something is introduced
#     that uses one of those patterns even if none exist now
#    -possibly issue with type conversions?
#    -possibly harder to debug if conversion info is missing, may fail quietly
#    -possible change: value as tuple of field name and optional function of data line (or value
#      and data line. flexible, but maybe overly complex?

# 2nd parameter is none or a lambda of the field value as well as the line (which contains that
# value among others)
# an example minutes to second conversion: interp = lambda value, _: value * 60
# an example using multiple fields: lambda _, line: line['a'] * line['b']
from libs.forest_integration.constants import TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS


def construct_summary_statistics(study, participant, tree_name, csv_string):
    if not Participant.objects.filter(patient_id=participant, study__name=study, deleted=False):
        raise ValueError("no participant or study associated with Forest data")
    file = StringIO(csv_string)  # this imitates the file interface to allow reading as a CSV
    with open(file, 'rb') as f:
        reader = csv.DictReader(f)
        data = list(reader)

    for line in data:
        summary_date = date(year=line['year'], month=line['month'], day=line['day'])
        updates = {}
        for column_name, value in line.items():
            if (tree_name, column_name) in TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS:
                summary_stat_field, interp_function = TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS[(tree_name, column_name)]
                if interp_function is not None:
                    updates[summary_stat_field] = interp_function(value, line)
                else:
                    updates[summary_stat_field] = value

        if len(updates) != len([k for k in TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS.keys() if k[0] == tree_name]):
            # error instead?
            print('some fields not found in forest data output, possible missing data. '
                  'Check if you are using an outdated version of Forest')

        obj, created = SummaryStatisticDaily.objects.update_or_create(
            study=study,
            participant=participant,
            date=summary_date,
            defaults=updates
        )  # TODO: make fields blank and null, or address the issue of missing fields here

