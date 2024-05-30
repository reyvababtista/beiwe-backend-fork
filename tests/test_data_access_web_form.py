from database.security_models import ApiKey
from tests.common import ResearcherSessionTest


#
## data_access_web_form
#
class TestDataAccessWebFormPage(ResearcherSessionTest):
    ENDPOINT_NAME = "data_access_web_form.data_api_web_form_page"
    
    def test(self):
        resp = self.smart_get()
        self.assert_present("can download data. Go to", resp.content)
        
        api_key = ApiKey.generate(researcher=self.session_researcher)
        id_key, secret_key = api_key.access_key_id, api_key.access_key_secret_plaintext
        
        resp = self.smart_get()
        self.assert_not_present("can download data. Go to", resp.content)
