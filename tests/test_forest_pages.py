import uuid

from constants.forest_constants import FOREST_NO_TASK
from constants.user_constants import ResearcherRole
from database.forest_models import ForestTask
from tests.common import ResearcherSessionTest


#
## forest_pages
#


# FIXME: make a real test...
class TestForestAnalysisProgress(ResearcherSessionTest):
    ENDPOINT_NAME = "forest_pages.forest_tasks_progress"
    
    def test(self):
        # hey it loads...
        self.set_session_study_relation(ResearcherRole.researcher)
        for _ in range(10):
            self.generate_participant(self.session_study)
        # print(Participant.objects.count())
        self.smart_get(self.session_study.id)



# class TestForestCreateTasks(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.create_tasks"
#     def test(self):
#         self.smart_get()


# class TestForestTaskLog(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.task_log"
#     def test(self):
#         self.smart_get()


# TODO: make a test for whether a tsudy admin can hit this endpoint? I think there's a bug in the authenticate_admin decorator that allows that.....
# class TestForestDownloadTaskLog(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_log"
#
#     def test(self):
#         # this streams a csv of tasks on a tsudy
#         self.smart_get()


# class TestForestCancelTask(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.cancel_task"
#     def test(self):
#         self.smart_get()


# class TestForestDownloadTaskData(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_data"
#     def test(self):
#         self.smart_get()


# class TestForestDownloadOutput(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_data"
#     def test(self):
#         self.smart_get()


class TestRerunForestTask(ResearcherSessionTest):
    ENDPOINT_NAME = "forest_pages.copy_forest_task"
    REDIRECT_ENDPOINT_NAME = "forest_pages.task_log"
    
    def test_no_task_specified(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_post_redirect(self.session_study.id)
        self.assert_present(FOREST_NO_TASK, self.redirect_get_contents(self.session_study.id))
    
    def test_no_such_task(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_post_redirect(self.session_study.id, external_id=uuid.uuid4())
        self.assert_present(FOREST_NO_TASK, self.redirect_get_contents(self.session_study.id))
    
    def test_bad_uuid(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_post_redirect(self.session_study.id, external_id="abc123")
        self.assert_present(FOREST_NO_TASK, self.redirect_get_contents(self.session_study.id))
    
    def test_success(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        old_task = self.default_forest_task
        self.assertEqual(ForestTask.objects.count(), 1)
        self.smart_post_redirect(self.session_study.id, external_id=old_task.external_id)
        self.assertEqual(ForestTask.objects.count(), 2)
        new_task = ForestTask.objects.exclude(id=old_task.id).get()
        msg = f"Made a copy of {old_task.external_id} with id {new_task.external_id}."
        self.assert_present(msg, self.redirect_get_contents(self.session_study.id))
    
    def test_researcher_cannot(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        old_task = self.default_forest_task
        self.assertEqual(ForestTask.objects.count(), 1)
        self.smart_post_status_code(403, self.session_study.id, external_id=old_task.external_id)
        self.assertEqual(ForestTask.objects.count(), 1)
        self.smart_post_status_code(403, self.session_study.id)
    
    def test_study_admin_cannot(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        old_task = self.default_forest_task
        self.assertEqual(ForestTask.objects.count(), 1)
        self.smart_post_status_code(403, self.session_study.id, external_id=old_task.external_id)
        self.assertEqual(ForestTask.objects.count(), 1)
        self.smart_post_status_code(403, self.session_study.id)
