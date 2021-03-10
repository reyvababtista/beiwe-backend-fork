from django import forms


# These should be changed to be inside the template
_CRED_MESSAGE_BASE = """
<p>Your new <b>Access Key</b> is:
  <div class="container-fluid">
    <textarea rows="1" cols="120" readonly="readonly"
    onclick="this.focus();this.select()">%s</textarea></p>
  </div>
<p>Your new <b>Secret Key</b> is:
  <div class="container-fluid">
    <textarea rows="1" cols="120" readonly="readonly"
    onclick="this.focus();this.select()">%s</textarea></p>
  </div>
<p>Please record these somewhere; they will not be shown again!</p>
"""

# these strings are nearly identical
RESET_DOWNLOAD_API_CREDENTIALS_MESSAGE = (
    "<h3>Your Data-Download API access credentials have been reset!</h3>" + _CRED_MESSAGE_BASE
).strip()


NEW_API_KEY_MESSAGE = (
    "<h3>New Tableau API credentials have been generated for you!</h3>" + _CRED_MESSAGE_BASE
).strip()


class NewApiKeyForm(forms.Form):
    readable_name = forms.CharField(required=False)

    def clean(self):
        super().clean()
        self.cleaned_data['tableau_api_permission'] = True


class DisableApiKeyForm(forms.Form):
    api_key_id = forms.CharField()
