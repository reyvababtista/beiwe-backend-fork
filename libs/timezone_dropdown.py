from collections import defaultdict
from datetime import timedelta
from typing import List, Tuple

import pytz
from dateutil import tz

REGION_SUBREGION_SEPARATOR = " - "
REGION_SEPARATOR = "\n"


def timedelta_to_label(td: timedelta) -> str:
    """ returns a string like +1:00 """
    label = "-" + str(abs(td)) if td.total_seconds() < 0 else "+" + str(abs(td))
    return label[:-3]


def string_sorter(key: str):
    """ get the first timedelta's floating point representation as the 'key' in our sort algo."""
    return float(key.split("/")[0].replace(":", "."))


def build_dictionary_of_timezones():
    # defaultdicts are cool.
    zones_by_offset = defaultdict(list)

    # there are more timezones in pytz.all_timezones
    for zone_name in pytz.common_timezones:
        # this 'tz_info' variable's type may be dependent on your platform, which is ... just insane.
        # This has been tested and works on Ubuntu and AWS Linux 1.
        tz_info: tz.tzfile = tz.gettz(zone_name)
        utc_offset: timedelta = tz_info._ttinfo_std.delta

        # No DST case
        if tz_info._ttinfo_dst is None:
            label = timedelta_to_label(utc_offset)
        else:
            dst_offset = tz_info._ttinfo_dst.delta
            # fun timezone case: some timezones HAD daylight savings in the past, but not anymore.
            # treat those as not having dst because anything else is madness.
            if dst_offset == utc_offset:
                label = timedelta_to_label(utc_offset)
            else:
                # this ordering yields +4:00/+5:00 ordering in most cases, but there are exceptions?
                # It's not hemispheric, I don't what those places are doing with time.
                label = f"{timedelta_to_label(utc_offset)}/{timedelta_to_label(dst_offset)}"

        zones_by_offset[label].append(zone_name)

    and_finally_sorted = {}
    for offset in sorted(zones_by_offset, key=string_sorter):
        and_finally_sorted[offset] = zones_by_offset[offset]

    return and_finally_sorted


def flatten_time_zones(all_zones_by_offset):
    """ Builds a dropdown-friendly list of tuples for populating a dropdown. """
    ret = []
    for offset_numbers, locations in all_zones_by_offset.items():
        for location_names in locations:
            ret.append([location_names, offset_numbers + " - " + location_names])
    return ret


ALL_TIMEZONES_DROPDOWN = flatten_time_zones(build_dictionary_of_timezones())
ALL_TIMEZONES = set([name for name,_ in ALL_TIMEZONES_DROPDOWN])
