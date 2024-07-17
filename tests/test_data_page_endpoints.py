from typing import List

from django.http.response import HttpResponse
from django.utils import timezone

from constants.data_stream_constants import (ACCELEROMETER, COMPLETE_DATA_STREAM_DICT,
    DASHBOARD_DATA_STREAMS)
from constants.user_constants import ResearcherRole
from database.data_access_models import ChunkRegistry
from database.security_models import ApiKey
from database.user_models_participant import Participant
from libs.security import generate_easy_alphanumeric_string
from tests.common import ResearcherSessionTest


#
## data_access_web_form
#
class TestDataAccessWebFormPage(ResearcherSessionTest):
    ENDPOINT_NAME = "data_page_endpoints.data_api_web_form_page"
    
    def test(self):
        resp = self.smart_get()
        self.assert_present("can download data. Go to", resp.content)
        
        api_key = ApiKey.generate(researcher=self.session_researcher)
        id_key, secret_key = api_key.access_key_id, api_key.access_key_secret_plaintext
        
        resp = self.smart_get()
        self.assert_not_present("can download data. Go to", resp.content)


#
## dashboard pages
#


class TestDashboard(ResearcherSessionTest):
    ENDPOINT_NAME = "data_page_endpoints.dashboard_page"
    
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
        self.using_default_participant()
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
    ENDPOINT_NAME = "data_page_endpoints.get_data_for_dashboard_datastream_display"
    
    def test_no_participant(self):
        self.do_data_stream_test(create_chunkregistries=False, number_participants=0)
    
    def test_one_participant_no_data(self):
        self.do_data_stream_test(create_chunkregistries=False, number_participants=1)
    
    def test_three_participants_no_data(self):
        self.do_data_stream_test(create_chunkregistries=False, number_participants=3)
    
    def test_five_participants_with_data(self):
        self.do_data_stream_test(create_chunkregistries=True, number_participants=5)
    
    def do_data_stream_test(self, create_chunkregistries=False, number_participants=1):
        # this is slow because it make SO MANY REQUESTS
        
        # self.default_participant  < -- breaks, collision with default name.
        self.set_session_study_relation()
        participants: List[Participant] = [
            self.generate_participant(self.session_study, patient_id=f"patient{i+1}")
            for i in range(number_participants)
        ]
        # create all the participants we need
        if create_chunkregistries:
            # miniscule optimization...
            bulk = []
            for i, participant in enumerate(participants, start=0):
                bulk.append(ChunkRegistry(
                    study=self.session_study,
                    participant=participant,
                    data_type="junk",
                    chunk_path=generate_easy_alphanumeric_string(),
                    chunk_hash=generate_easy_alphanumeric_string(),
                    time_bin=timezone.localtime().replace(hour=i, minute=0, second=0, microsecond=0),
                    file_size=123456 + i,
                    is_chunkable=False,
                ))
            ChunkRegistry.objects.bulk_create(bulk)
        
        # technically the end point accepts post and get. We don't care enouhg to test both.
        for data_stream in DASHBOARD_DATA_STREAMS:
            if create_chunkregistries:  # force correct data type
                ChunkRegistry.objects.all().update(data_type=data_stream)
            
            html = self.smart_get_status_code(200, self.session_study.id, data_stream).content
            title = COMPLETE_DATA_STREAM_DICT[data_stream]
            self.assert_present(title, html)
            
            for i, participant in enumerate(participants, start=0):
                comma_separated = str(123456 + i)[:-3] + "," + str(123456 + i)[3:]
                if create_chunkregistries:
                    self.assert_present(participant.patient_id, html)
                    self.assert_present(comma_separated, html)
                else:
                    self.assert_not_present(participant.patient_id, html)
                    self.assert_not_present(comma_separated, html)
            if not participants or not create_chunkregistries:
                self.assert_present(f"There is no data currently available for {title}", html)


# FIXME: this page renders with almost no data
class TestDashboardPatientDisplay(ResearcherSessionTest):
    ENDPOINT_NAME = "data_page_endpoints.dashboard_participant_page"
    
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
