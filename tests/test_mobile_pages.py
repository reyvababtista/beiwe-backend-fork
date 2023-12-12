from tests.common import ParticipantSessionTest


class TestGraph(ParticipantSessionTest):
    ENDPOINT_NAME = "mobile_pages.fetch_graph"
    
    def test(self):
        # testing this requires setting up fake survey answers to see what renders in the javascript?
        resp = self.smart_post_status_code(200)
        self.assert_present("Rendered graph for user", resp.content)
    
    def test_deleted_participant(self):
        self.INJECT_DEVICE_TRACKER_PARAMS = False
        self.default_participant.update(deleted=True)
        response = self.smart_post_status_code(403)
        self.assertEqual(response.content, b"")
        self.INJECT_DEVICE_TRACKER_PARAMS = True
