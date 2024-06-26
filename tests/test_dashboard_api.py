from typing import List

from django.http.response import HttpResponse
from django.utils import timezone

from constants.dashboard_constants import COMPLETE_DATA_STREAM_DICT, DASHBOARD_DATA_STREAMS
from constants.data_stream_constants import ACCELEROMETER
from constants.user_constants import ResearcherRole
from database.data_access_models import ChunkRegistry
from database.user_models_participant import Participant
from tests.common import ResearcherSessionTest


# trunk-ignore-all(ruff/B018)

#
## dashboard_api
#


class TestDashboard(ResearcherSessionTest):
    ENDPOINT_NAME = "dashboard_api.dashboard_page"
    
    def assert_data_streams_present(self, resp: HttpResponse):
        for data_stream_text in COMPLETE_DATA_STREAM_DICT.values():
            self.assert_present(data_stream_text, resp.content)
    
    def test_dashboard_no_participants(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_get_status_code(200, str(self.session_study.id))
        self.assert_present("Choose a participant or data stream to view", resp.content)
        self.assert_not_present(self.DEFAULT_PARTICIPANT_NAME, resp.content)
        self.assert_data_streams_present(resp)
    
    def test_dashboard_one_participant(self):
        self.default_participant
        # default user and default study already instantiated
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_get_status_code(200, str(self.session_study.id))
        self.assert_present("Choose a participant or data stream to view", resp.content)
        self.assert_present(self.DEFAULT_PARTICIPANT_NAME, resp.content)
        self.assert_data_streams_present(resp)
    
    def test_dashboard_many_participant(self):
        participants = self.generate_10_default_participants
        # default user and default study already instantiated
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_get_status_code(200, str(self.session_study.id))
        self.assert_present("Choose a participant or data stream to view", resp.content)
        for p in participants:
            self.assert_present(p.patient_id, resp.content)
        self.assert_data_streams_present(resp)


# FIXME: dashboard is going to require a fixture to populate data.
class TestDashboardStream(ResearcherSessionTest):
    ENDPOINT_NAME = "dashboard_api.get_data_for_dashboard_datastream_display"
    
    def test_no_participant(self):
        self.do_data_stream_test(create_chunkregistries=False, number_participants=0)
    
    def test_one_participant_no_data(self):
        self.do_data_stream_test(create_chunkregistries=False, number_participants=1)
    
    def test_three_participants_no_data(self):
        self.do_data_stream_test(create_chunkregistries=False, number_participants=3)
    
    def test_five_participants_with_data(self):
        self.do_data_stream_test(create_chunkregistries=True, number_participants=5)
    
    def do_data_stream_test(self, create_chunkregistries=False, number_participants=1):
        # self.default_participant  < -- breaks, collision with default name.
        self.set_session_study_relation()
        participants: List[Participant] = [
            self.generate_participant(self.session_study, patient_id=f"patient{i+1}")
            for i in range(number_participants)
        ]
        
        # create all the participants we need
        if create_chunkregistries:
            for i, participant in enumerate(participants, start=0):
                self.generate_chunkregistry(
                    self.session_study,
                    participant,
                    "junk",  # data_stream
                    file_size=123456 + i,
                    time_bin=timezone.localtime().replace(
                        hour=i, minute=0, second=0, microsecond=0
                    ),
                )
        
        for data_stream in DASHBOARD_DATA_STREAMS:
            if create_chunkregistries:  # force correct data type
                ChunkRegistry.objects.all().update(data_type=data_stream)
            
            html1 = self.smart_get_status_code(200, self.session_study.id, data_stream).content
            html2 = self.smart_post_status_code(200, self.session_study.id, data_stream).content
            title = COMPLETE_DATA_STREAM_DICT[data_stream]
            self.assert_present(title, html1)
            self.assert_present(title, html2)
            
            for i, participant in enumerate(participants, start=0):
                comma_separated = str(123456 + i)[:-3] + "," + str(123456 + i)[3:]
                if create_chunkregistries:
                    self.assert_present(participant.patient_id, html1)
                    self.assert_present(participant.patient_id, html2)
                    self.assert_present(comma_separated, html1)
                    self.assert_present(comma_separated, html2)
                else:
                    self.assert_not_present(participant.patient_id, html1)
                    self.assert_not_present(participant.patient_id, html2)
                    self.assert_not_present(comma_separated, html1)
                    self.assert_not_present(comma_separated, html2)
            
            if not participants or not create_chunkregistries:
                self.assert_present(f"There is no data currently available for {title}", html1)
                self.assert_present(f"There is no data currently available for {title}", html2)


# FIXME: this page renders with almost no data
class TestDashboardPatientDisplay(ResearcherSessionTest):
    ENDPOINT_NAME = "dashboard_api.dashboard_participant_page"
    
    def test_patient_display_no_data(self):
        self.set_session_study_relation()
        resp = self.smart_get_status_code(
            200, self.session_study.id, self.default_participant.patient_id
        )
        self.assert_present(
            "There is no data currently available for patient1 of Study", resp.content
        )
    
    def test_five_participants_with_data(self):
        self.set_session_study_relation()
        
        for i in range(10):
            self.generate_chunkregistry(
                self.session_study,
                self.default_participant,
                ACCELEROMETER,  # data_stream
                file_size=123456,
                time_bin=timezone.localtime().replace(hour=i, minute=0, second=0, microsecond=0),
            )
        
        # need to be post and get requests, it was just built that way
        html1 = self.smart_get_status_code(
            200, self.session_study.id, self.default_participant.patient_id
        ).content
        html2 = self.smart_post_status_code(
            200, self.session_study.id, self.default_participant.patient_id
        ).content
        title = COMPLETE_DATA_STREAM_DICT[ACCELEROMETER]
        self.assert_present(title, html1)
        self.assert_present(title, html2)
        # test for value of 10x for 1 day of 10 hours of data
        comma_separated = "1,234,560"
        for title in COMPLETE_DATA_STREAM_DICT.values():
            self.assert_present(title, html1)
            self.assert_present(title, html2)
        
        self.assert_present(self.default_participant.patient_id, html1)
        self.assert_present(self.default_participant.patient_id, html2)
        self.assert_present(comma_separated, html1)
        self.assert_present(comma_separated, html2)
