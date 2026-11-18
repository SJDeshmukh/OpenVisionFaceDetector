import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from services import weather_theme_service as service


IST = ZoneInfo("Asia/Kolkata")


class WeatherThemeServiceTests(unittest.TestCase):
    def setUp(self):
        service._CACHE.clear()

    def test_india_seasonal_fallback_covers_normal_periods(self):
        self.assertEqual(service.normal_india_theme(4, 20)[0], "summer")
        self.assertEqual(service.normal_india_theme(7, 20)[0], "rainy")
        self.assertEqual(service.normal_india_theme(12, 20)[0], "winter")
        self.assertEqual(service.normal_india_theme(10, 20)[0], "autumn")

    def test_coordinates_reject_non_finite_and_out_of_range_values(self):
        for latitude, longitude in [("nan", 10), (91, 10), (10, 181), (None, 10)]:
            with self.subTest(latitude=latitude, longitude=longitude):
                with self.assertRaises(ValueError):
                    service.validate_coordinates(latitude, longitude)

    def test_llm_is_primary_and_result_is_cached_for_nearby_users(self):
        provider = Mock()
        provider.providers = None
        provider.complete.return_value = {"content": "rainy"}
        now = datetime(2026, 7, 18, 10, 0, tzinfo=IST)

        with patch("services.xchat_service.configured_provider", return_value=provider):
            first = service.resolve_weather_theme(19.9975, 73.7898, now=now)
            second = service.resolve_weather_theme(20.01, 73.81, now=now)

        self.assertEqual(first["theme"], "rainy")
        self.assertEqual(first["selection_source"], "llm_india_seasonal")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        provider.complete.assert_called_once()

    def test_invalid_llm_output_uses_india_seasonal_fallback(self):
        provider = Mock()
        provider.providers = None
        provider.complete.return_value = {"content": "storm"}
        now = datetime(2026, 4, 18, 10, 0, tzinfo=IST)
        with patch("services.xchat_service.configured_provider", return_value=provider):
            result = service.resolve_weather_theme(19.9, 73.7, now=now)
        self.assertEqual(result["theme"], "summer")
        self.assertEqual(result["selection_source"], "india_seasonal_fallback")

    def test_snow_response_is_rejected_outside_himalayan_winter(self):
        provider = Mock()
        provider.providers = None
        provider.complete.return_value = {"content": "snow"}
        now = datetime(2026, 7, 18, 10, 0, tzinfo=IST)
        with patch("services.xchat_service.configured_provider", return_value=provider):
            result = service.resolve_weather_theme(19.9, 73.7, now=now)
        self.assertEqual(result["theme"], "rainy")


if __name__ == "__main__":
    unittest.main()

