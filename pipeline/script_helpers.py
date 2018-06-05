import subprocess

# Do not modify this * import, this is how we solve all the pipeline/scripts folder's import problems
from configuration_getters import custom_config_components


def set_default_region():
    aws_object_names = custom_config_components()
    region_name = aws_object_names['region_name']
    subprocess.check_call(['aws', 'configure', 'set', 'default.region', region_name])

