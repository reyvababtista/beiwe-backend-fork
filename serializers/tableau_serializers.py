from rest_framework import serializers

from database.security_models import ApiKey


# FIXMME: this is the only remaining DRF serializer we can do it we can finally get rid of them all
class ApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiKey
        fields = [
            "access_key_id",
            "created_on",
            "has_tableau_api_permissions",
            "is_active",
            "readable_name",
        ]
