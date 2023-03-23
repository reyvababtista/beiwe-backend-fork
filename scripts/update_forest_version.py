import pkg_resources
from constants.common_constants import BEIWE_PROJECT_ROOT
from database.system_models import ForestVersion
from posixpath import join as path_join

that_git_prefix = "git+https://git@github.com/onnela-lab/forest@"

with open(path_join(BEIWE_PROJECT_ROOT, "requirements_data_processing.txt"), "rt") as f:
    requirements_file_lines = f.read().splitlines()

git_version = ""
for line in requirements_file_lines:
    # in the insane case of multiple matches we are getting the first instance, not the last.
    if line.startswith(that_git_prefix):
        git_version = line.split(that_git_prefix)[-1]
        break


forest_version = ForestVersion.get_singleton_instance()
forest_version.package_version = pkg_resources.get_distribution("forest")
forest_version.git_commit = git_version
forest_version.save()
