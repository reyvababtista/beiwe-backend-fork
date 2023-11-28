import pkg_resources

from database.system_models import ForestVersion
from libs.forest_utils import get_forest_git_hash


forest_version = ForestVersion.get_singleton_instance()
forest_version.package_version = pkg_resources.get_distribution("forest")
forest_version.git_commit = get_forest_git_hash()
forest_version.save()
