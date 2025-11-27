from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from decimal import Decimal
from .models import Insurer, InsuranceType, CommissionRate

User = get_user_model()


class CommissionRateAPITest(TestCase):
    """Tests for commission rate API endpoint"""
    
    def setUp(self):
        # Create test user with staff permissions
        self.user = User.objects.create_user(
            username='testadmin',
            password='testpass123',
            is_staff=True
        )
        
        # Create test data
        self.insurer = Insurer.objects.create(
            insurer_name='Тестовая СК'
        )
        
        self.insurance_type = InsuranceType.objects.create(
            name='КАСКО'
        )
        
        self.commission_rate = CommissionRate.objects.create(
            insurer=self.insurer,
            insurance_type=self.insurance_type,
            kv_percent=Decimal('15.50')
        )
        
        self.client = Client()
        self.client.login(username='testadmin', password='testpass123')
    
    def test_get_commission_rate_success(self):
        """Test successful commission rate retrieval"""
        url = reverse('insurers:api_commission_rate')
        response = self.client.get(url, {
            'insurer_id': self.insurer.id,
            'insurance_type_id': self.insurance_type.id
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['commission_rate_id'], self.commission_rate.id)
        self.assertEqual(data['kv_percent'], '15.50')
        self.assertIn('display_name', data)
    
    def test_get_commission_rate_not_found(self):
        """Test commission rate not found"""
        # Create another insurance type without commission rate
        other_type = InsuranceType.objects.create(name='ОСАГО')
        
        url = reverse('insurers:api_commission_rate')
        response = self.client.get(url, {
            'insurer_id': self.insurer.id,
            'insurance_type_id': other_type.id
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertFalse(data['success'])
        self.assertIn('error', data)
    
    def test_get_commission_rate_missing_params(self):
        """Test missing required parameters"""
        url = reverse('insurers:api_commission_rate')
        response = self.client.get(url, {
            'insurer_id': self.insurer.id
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        
        self.assertFalse(data['success'])
        self.assertIn('error', data)
    
    def test_get_commission_rate_requires_staff(self):
        """Test that endpoint requires staff permissions"""
        # Create regular user without staff permissions
        regular_user = User.objects.create_user(
            username='regular',
            password='testpass123',
            is_staff=False
        )
        
        client = Client()
        client.login(username='regular', password='testpass123')
        
        url = reverse('insurers:api_commission_rate')
        response = client.get(url, {
            'insurer_id': self.insurer.id,
            'insurance_type_id': self.insurance_type.id
        })
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
