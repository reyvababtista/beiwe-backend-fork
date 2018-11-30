import subprocess

from pipeline.configuration_getters import get_current_region


def set_default_region():
    region_name = get_current_region()
    subprocess.check_call(['aws', 'configure', 'set', 'default.region', region_name])

