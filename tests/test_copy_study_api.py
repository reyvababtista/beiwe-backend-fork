import orjson
from io import BytesIO

from django.http.response import FileResponse

from constants.user_constants import ResearcherRole
from libs.copy_study import format_study
from tests.common import ResearcherSessionTest


#
## copy_study_api
#

# FIXME: add interventions and surveys to the export tests
class TestExportStudySettingsFile(ResearcherSessionTest):
    ENDPOINT_NAME = "copy_study_api.export_study_settings_file"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        # FileResponse objects stream, which means you need to iterate over `resp.streaming_content``
        resp: FileResponse = self.smart_get(self.session_study.id)
        # sanity check...
        resp_string = b"".join(resp.streaming_content)
        self.assertNotEqual(len(resp_string), 0)
        # get survey, check device_settings, surveys, interventions are all present
        output_survey: dict = orjson.loads(resp_string)
        self.assertIn("device_settings", output_survey)
        self.assertIn("surveys", output_survey)
        self.assertIn("interventions", output_survey)
        output_device_settings: dict = output_survey["device_settings"]
        real_device_settings = self.session_device_settings.export()
        # confirm that all elements are equal for the dicts
        for k, v in output_device_settings.items():
            self.assertEqual(v, real_device_settings[k])


# FIXME: add interventions and surveys to the import tests
class TestImportStudySettingsFile(ResearcherSessionTest):
    ENDPOINT_NAME = "copy_study_api.import_study_settings_file"
    REDIRECT_ENDPOINT_NAME = "study_endpoints.edit_study"
    
    # other post params: device_settings, surveys
    
    def test_no_device_settings_no_surveys(self):
        content = self._test(False, False)
        self.assert_present("Did not alter", content)
        self.assert_present("Copied 0 Surveys and 0 Audio Surveys", content)
    
    def test_device_settings_no_surveys(self):
        content = self._test(True, False)
        self.assert_present("Settings with custom values.", content)
        self.assert_present("Copied 0 Surveys and 0 Audio Surveys", content)
    
    def test_device_settings_and_surveys(self):
        content = self._test(True, True)
        self.assert_present("Settings with custom values.", content)
        self.assert_present("Copied 0 Surveys and 0 Audio Surveys", content)
    
    def test_bad_filename(self):
        content = self._test(True, True, ".exe", success=False)
        # FIXME: this is not present in the html, it should be  - string doesn't appear in codebase...
        # self.assert_present("You can only upload .json files.", content)
    
    def _test(
        self,
        device_settings: bool,
        surveys: bool,
        extension: str = "json",
        success: bool = True
    ) -> bytes:
        self.set_session_study_relation(ResearcherRole.site_admin)
        study2 = self.generate_study("study_2")
        self.assertEqual(self.session_device_settings.gps, True)
        self.session_device_settings.update(gps=False)
        
        # this is the function that creates the canonical study representation wrapped in a burrito
        survey_json_file = BytesIO(format_study(self.session_study))
        survey_json_file.name = f"something.{extension}"  # ayup, that's how you add a name...
        
        self.smart_post_redirect(
            study2.id,
            upload=survey_json_file,
            device_settings="true" if device_settings else "false",
            surveys="true" if surveys else "false",
        )
        study2.device_settings.refresh_from_db()
        if success:
            self.assertEqual(study2.device_settings.gps, not device_settings)
        # return the page, we always need it
        return self.easy_get(
            self.REDIRECT_ENDPOINT_NAME, status_code=200, study_id=study2.id
        ).content
