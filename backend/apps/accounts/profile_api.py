"""Self-service profile endpoints (apps/accounts/profile.py).

    GET   auth/me/profile/   identity (read only), school, roles, editable fields
    PATCH auth/me/profile/   {phone, occupation, address, emergency_phone, preferred_language}
                             -- only the fields of `editable`; anything else: 400 VALIDATION_ERROR
    GET   auth/me/photo/     image/jpeg (the owner only; 404 without photo)
    POST  auth/me/photo/     multipart "photo"     DELETE auth/me/photo/

An ACTIVE membership in an ACTIVE school is required (IsSchoolMember): a
suspended member, or a parent still awaiting approval, cannot edit.
Password: auth/password/change/. Sessions: auth/sessions/ (existing).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, Http404
from rest_framework import serializers
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsSchoolMember
from common.tenancy import get_active_membership

from . import profile
from .services import ClientContext


class MeProfileView(APIView):
    permission_classes = [IsSchoolMember]
    parser_classes = [JSONParser]

    def get(self, request):
        return Response(profile.profile_data(get_active_membership(request)))

    def patch(self, request):
        if not isinstance(request.data, dict):
            raise serializers.ValidationError({"non_field_errors": ["Objet JSON attendu."]})
        try:
            data = profile.update_profile(
                get_active_membership(request), dict(request.data), ctx=ClientContext.from_request(request)
            )
        except DjangoValidationError as exc:
            if hasattr(exc, "error_dict"):
                raise serializers.ValidationError(exc.message_dict) from None  # per-field, like any form
            raise
        return Response(data)


class MePhotoView(APIView):
    permission_classes = [IsSchoolMember]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        user = get_active_membership(request).user
        if not user.profile_photo:
            raise Http404
        response = FileResponse(user.profile_photo.open("rb"), content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def post(self, request):
        membership = get_active_membership(request)
        profile.set_photo(membership, request.FILES.get("photo"), ctx=ClientContext.from_request(request))
        return Response(profile.profile_data(membership))

    def delete(self, request):
        membership = get_active_membership(request)
        profile.remove_photo(membership, ctx=ClientContext.from_request(request))
        return Response(profile.profile_data(membership))
