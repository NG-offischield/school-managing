"""Read endpoint of the current school (configuration + branding)."""

from django.urls import path
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsSchoolMember
from common.tenancy import get_current_school

from .models import School, SchoolBranding, SchoolConfiguration


class SchoolConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolConfiguration
        exclude = ["id", "school", "created_at", "updated_at"]


class SchoolBrandingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolBranding
        exclude = ["id", "school", "created_at", "updated_at"]


class SchoolSerializer(serializers.ModelSerializer):
    configuration = SchoolConfigurationSerializer(read_only=True)
    branding = SchoolBrandingSerializer(read_only=True)

    class Meta:
        model = School
        fields = [
            "id",
            "code",
            "name",
            "legal_name",
            "short_name",
            "address",
            "city",
            "country",
            "phone",
            "email",
            "website",
            "timezone",
            "currency",
            "status",
            "configuration",
            "branding",
        ]


class CurrentSchoolView(APIView):
    """GET /api/v1/school/ — the school the caller is acting in.

    No id in the URL on purpose: the school is derived from the caller's
    membership (current_user + current_school), so there is nothing to tamper
    with. Readable by every active member.
    """

    permission_classes = [IsSchoolMember]

    def get(self, request):
        return Response(SchoolSerializer(get_current_school(request)).data)


urlpatterns = [path("school/", CurrentSchoolView.as_view(), name="current-school")]
