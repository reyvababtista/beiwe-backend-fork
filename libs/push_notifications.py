from config.constants import ScheduleTypes
from database.schedule_models import AbsoluteSchedule, RelativeSchedule, WeeklySchedule


SCHEDULE_CLASS_LOOKUP = {
    ScheduleTypes.absolute: AbsoluteSchedule,
    ScheduleTypes.relative: RelativeSchedule,
    ScheduleTypes.weekly: WeeklySchedule,
}

