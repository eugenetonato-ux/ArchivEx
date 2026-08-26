from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from academics.models import School, Level, Filiere
from contributors.models import ContributorProfile
from contributors.permissions import check_school_permission, require_school_permission
from django.http import HttpResponse

User = get_user_model()


class ContributorSchoolSecurityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.school_eneam = School.objects.create(name="ENEAM", code="ENEAM", slug="eneam", is_active=True)
        self.school_flash = School.objects.create(name="FLASH", code="FLASH", slug="flash", is_active=True)

        self.contrib_eneam = User.objects.create_user(username="contrib_eneam", password="Password123!")
        self.prof_eneam = ContributorProfile.objects.create(
            user=self.contrib_eneam,
            role="SCHOOL_CONTENT_MANAGER",
            is_active=True
        )
        self.prof_eneam.assigned_schools.add(self.school_eneam)

        self.superadmin = User.objects.create_superuser(username="superadmin", email="admin@test.com", password="Password123!")

    def test_school_manager_permissions(self):
        """School manager can manage assigned school, but not unauthorized school."""
        self.assertTrue(check_school_permission(self.contrib_eneam, self.school_eneam))
        self.assertFalse(check_school_permission(self.contrib_eneam, self.school_flash))

    def test_superadmin_permissions(self):
        """Superadmin has unrestricted access to all schools."""
        self.assertTrue(check_school_permission(self.superadmin, self.school_eneam))
        self.assertTrue(check_school_permission(self.superadmin, self.school_flash))

    def test_server_side_decorator_http_403_enforcement(self):
        """Decorator raises PermissionDenied (403) when attempting unauthorized access."""
        @require_school_permission(school_id_param="school_id")
        def mock_view(request, school_id):
            return HttpResponse("Success")

        class MockRequest:
            def __init__(self, user):
                self.user = user
                self.GET = {}
                self.POST = {}

        # Allowed request
        req_allowed = MockRequest(self.contrib_eneam)
        res = mock_view(req_allowed, school_id=self.school_eneam.id)
        self.assertEqual(res.status_code, 200)

        # Tampered request -> HTTP 403 expected
        from django.core.exceptions import PermissionDenied
        req_tampered = MockRequest(self.contrib_eneam)
        with self.assertRaises(PermissionDenied):
            mock_view(req_tampered, school_id=self.school_flash.id)
