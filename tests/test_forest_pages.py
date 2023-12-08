from constants.user_constants import ResearcherRole
from tests.common import ResearcherSessionTest

#fixme: implement.

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


# class TestForestDownloadTaskLog(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_log"
#     def test(self):
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
