"""
Tests for inline copy functionality.

**Feature: policy-payment-enhancements**

These tests verify that the copy button is properly configured in the inline.
"""
import pytest
from django.contrib.admin.sites import AdminSite
from apps.policies.admin import PaymentScheduleInline, PolicyAdmin
from apps.policies.models import Policy


@pytest.mark.django_db
class TestInlineCopyConfiguration:
    """Tests for inline copy button configuration."""
    
    def test_inline_has_media_js(self):
        """
        Test that PaymentScheduleInline includes the copy JavaScript file.
        """
        inline = PaymentScheduleInline(Policy, AdminSite())
        
        # Check that Media class exists
        assert hasattr(inline, 'Media')
        
        # Check that js is defined
        assert hasattr(inline.Media, 'js')
        
        # Check that our copy script is included
        js_files = inline.Media.js
        assert 'policies/js/copy_payment_inline.js' in js_files
    
    def test_inline_has_media_css(self):
        """
        Test that PaymentScheduleInline includes the copy CSS file.
        """
        inline = PaymentScheduleInline(Policy, AdminSite())
        
        # Check that css is defined
        assert hasattr(inline.Media, 'css')
        
        # Check that our copy styles are included
        css_files = inline.Media.css.get('all', [])
        assert 'policies/css/copy_payment_inline.css' in css_files
    
    def test_inline_registered_in_policy_admin(self):
        """
        Test that PaymentScheduleInline is registered in PolicyAdmin.
        """
        site = AdminSite()
        admin = PolicyAdmin(Policy, site)
        
        # Check that inlines are defined
        assert hasattr(admin, 'inlines')
        
        # Check that PaymentScheduleInline is in the inlines
        assert PaymentScheduleInline in admin.inlines
