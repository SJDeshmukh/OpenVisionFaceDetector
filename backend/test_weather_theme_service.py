import os
import unittest
from unittest.mock import Mock, patch

from services import weather_theme_service as service


class WeatherThemeServiceTests(unittest.TestCase):
    def setUp(self):
        service._CACHE.clear()

    def test_precipitation_and_temperature_extremes_are_deterministic(self):
        self.assertEqual(service.deterministic_theme({"weather_code": 73, "temperature_2m": -1}, 20)[0], "snow")
        self.assertEqual(service.deterministic_theme({"weather_code": 63, "temperature_2m": 24}, 20)[0], "rainy")
        self.assertEqual(service.deterministic_theme({"weather_code": 0, "temperature_2m": 34}, 20)[0], "summer")
        self.assertEqual(service.deterministic_theme({"weather_code": 2, "temperature_2m": 8}, 20)[0], "winter")

    def test_coordinates_reject_non_finite_and_out_of_range_values(self):
        for latitude, longitude in [("nan", 10), (91, 10), (10, 181), (None, 10)]:
            with self.subTest(latitude=latitude, longitude=longitude):
                with self.assertRaises(ValueError):
                    service.validate_coordinates(latitude, longitude)

    @patch("services.weather_theme_service.requests.get")
    def test_live_result_is_classified_and_cached_without_repeating_provider_call(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "timezone": "Asia/Kolkata",
            "current": {
                "time": "2026-11-18T10:15",
                "temperature_2m": 25.2,
                "apparent_temperature": 26.1,
                "relative_humidity_2m": 82,
                "precipitation": 0.4,
                "rain": 0.4,
                "showers": 0,
                "snowfall": 0,
                "weather_code": 61,
                "cloud_cover": 88,
                "wind_speed_10m": 12,
                "is_day": 1,
            },
        }
        get.return_value = response

        weather_endpoint = "https://customer-api.open-meteo.com/v1/forecast"
        with patch.dict(os.environ, {
            "WEATHER_THEME_LLM_ASSISTANCE": "false",
            "WEATHER_API_BASE_URL": weather_endpoint,
            "OPEN_METEO_API_KEY": "test-api-key",
        }):
            first = service.resolve_weather_theme(19.9975, 73.7898)
            second = service.resolve_weather_theme(20.01, 73.81)

        self.assertEqual(first["theme"], "rainy")
        self.assertEqual(first["condition"], "Slight rain")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], weather_endpoint)
        self.assertEqual(get.call_args.kwargs["params"]["apikey"], "test-api-key")

    def test_llm_output_is_allowlisted_and_physically_constrained(self):
        mild = {
            "time": "2026-11-18T10:15",
            "weather_code": 2,
            "temperature_2m": 24,
            "apparent_temperature": 24,
            "relative_humidity_2m": 45,
            "cloud_cover": 35,
            "wind_speed_10m": 5,
            "is_day": 1,
        }
        provider = Mock()
        provider.complete.return_value = {"content": "snow"}
        with patch("services.xchat_service.configured_provider", return_value=provider):
            self.assertIsNone(service._llm_theme(mild, 20, "autumn"))


if __name__ == "__main__":
    unittest.main()

