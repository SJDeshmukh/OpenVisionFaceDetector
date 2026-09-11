package com.faceplugin.facerecognition

import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.preference.*


class SettingsActivity : AppCompatActivity() {

    companion object {
        const val DEFAULT_CAMERA_LENS = "front"
        // Defaults from the in-repository FaceIDApp model contracts.
        const val DEFAULT_LIVENESS_THRESHOLD = "0.9"
        const val DEFAULT_IDENTIFY_THRESHOLD = "0.62"
        const val DEFAULT_LIVENESS_LEVEL = "0"
        const val DEFAULT_YAW_THRESHOLD = "40.0"
        const val DEFAULT_ROLL_THRESHOLD = "40.0"
        const val DEFAULT_PITCH_THRESHOLD = "40.0"
        const val DEFAULT_OCCLUSION_THRESHOLD = "0.5"
        const val DEFAULT_EYECLOSE_THRESHOLD = "0.5"
        const val DEFAULT_MOUTHOPEN_THRESHOLD = "0.5"
        const val DEFAULT_FACE_QUALITY_THRESHOLD = "0.5"
        const val DEFAULT_MIN_LUMINANCE = "0.15"
        const val DEFAULT_MAX_LUMINANCE = "0.90"

        private const val PREFS_SCHEMA = "facesdk_prefs_schema"
        private const val PREFS_SCHEMA_CURRENT = 3

        /** Migrates thresholds that belonged to the earlier SDK generation. */
        @JvmStatic
        fun applyEngineDefaults(context: Context) {
            val preferences = PreferenceManager.getDefaultSharedPreferences(context)
            val currentSchema = preferences.getInt(PREFS_SCHEMA, 0)
            if (currentSchema >= PREFS_SCHEMA_CURRENT) return
            val editor = preferences.edit()
            if (currentSchema < 1) {
                editor.putString("liveness_threshold", DEFAULT_LIVENESS_THRESHOLD)
                    .putString("identify_threshold", DEFAULT_IDENTIFY_THRESHOLD)
                    .putString("yaw_threshold", DEFAULT_YAW_THRESHOLD)
                    .putString("roll_threshold", DEFAULT_ROLL_THRESHOLD)
                    .putString("pitch_threshold", DEFAULT_PITCH_THRESHOLD)
                    .putString("eyeclose_threshold", DEFAULT_EYECLOSE_THRESHOLD)
            }
            if (!preferences.contains("face_quality_threshold")) {
                editor.putString("face_quality_threshold", DEFAULT_FACE_QUALITY_THRESHOLD)
            }
            if (!preferences.contains("min_luminance")) {
                editor.putString("min_luminance", DEFAULT_MIN_LUMINANCE)
            }
            if (!preferences.contains("max_luminance")) {
                editor.putString("max_luminance", DEFAULT_MAX_LUMINANCE)
            }
            if (currentSchema < 3) {
                // Earlier SDK scores are not calibrated like ArcFace/MiniFASNet scores.
                editor.putString("liveness_threshold", DEFAULT_LIVENESS_THRESHOLD)
                    .putString("identify_threshold", DEFAULT_IDENTIFY_THRESHOLD)
            }
            editor.putInt(PREFS_SCHEMA, PREFS_SCHEMA_CURRENT).apply()
        }

        @JvmStatic
        fun livenessPassed(context: Context, score: Float, label: String?): Boolean {
            val normalizedLabel = label.orEmpty().lowercase()
            if (!score.isFinite()) return false
            if (listOf("spoof", "fake", "print", "replay", "attack").any(normalizedLabel::contains)) return false
            return score >= getLivenessThreshold(context)
        }

        private fun boundedPreference(context: Context, key: String, default: String, min: Float, max: Float): Float {
            val preferences = PreferenceManager.getDefaultSharedPreferences(context)
            return preferences.getString(key, default)?.toFloatOrNull()?.takeIf { it.isFinite() }
                ?.coerceIn(min, max) ?: default.toFloat().coerceIn(min, max)
        }

        @JvmStatic
        fun getLivenessThreshold(context: Context): Float {
            return boundedPreference(context, "liveness_threshold", DEFAULT_LIVENESS_THRESHOLD, 0f, 1f)
        }

        @JvmStatic
        fun getIdentifyThreshold(context: Context): Float {
            return boundedPreference(context, "identify_threshold", DEFAULT_IDENTIFY_THRESHOLD, 0f, 1f)
        }

        @JvmStatic
        fun getCameraLens(context: Context): Int {
            val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(context)
            val cameraLens = sharedPreferences.getString("camera_lens", SettingsActivity.DEFAULT_CAMERA_LENS)
            if(cameraLens == "back") {
                return CameraSelector.LENS_FACING_BACK
            } else {
                return CameraSelector.LENS_FACING_FRONT
            }
        }

        @JvmStatic
        fun getLivenessLevel(context: Context): Int {
            val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(context)
            val livenessLevel = sharedPreferences.getString("liveness_level", SettingsActivity.DEFAULT_LIVENESS_LEVEL)
            return if (livenessLevel == "1") 1 else 0
        }

        @JvmStatic
        fun getYawThreshold(context: Context): Float {
            return boundedPreference(context, "yaw_threshold", DEFAULT_YAW_THRESHOLD, 0f, 90f)
        }

        @JvmStatic
        fun getRollThreshold(context: Context): Float {
            return boundedPreference(context, "roll_threshold", DEFAULT_ROLL_THRESHOLD, 0f, 90f)
        }

        @JvmStatic
        fun getPitchThreshold(context: Context): Float {
            return boundedPreference(context, "pitch_threshold", DEFAULT_PITCH_THRESHOLD, 0f, 90f)
        }

        @JvmStatic
        fun getOcclusionThreshold(context: Context): Float {
            return boundedPreference(context, "occlusion_threshold", DEFAULT_OCCLUSION_THRESHOLD, 0f, 1f)
        }

        @JvmStatic
        fun getEyecloseThreshold(context: Context): Float {
            return boundedPreference(context, "eyeclose_threshold", DEFAULT_EYECLOSE_THRESHOLD, 0f, 1f)
        }

        @JvmStatic
        fun getMouthopenThreshold(context: Context): Float {
            return boundedPreference(context, "mouthopen_threshold", DEFAULT_MOUTHOPEN_THRESHOLD, 0f, 1f)
        }

        @JvmStatic
        fun getFaceQualityThreshold(context: Context): Float {
            return boundedPreference(context, "face_quality_threshold", DEFAULT_FACE_QUALITY_THRESHOLD, 0f, 1f)
        }

        @JvmStatic
        fun getMinLuminance(context: Context): Float {
            val min = boundedPreference(context, "min_luminance", DEFAULT_MIN_LUMINANCE, 0f, 1f)
            val max = boundedPreference(context, "max_luminance", DEFAULT_MAX_LUMINANCE, 0f, 1f)
            return minOf(min, max)
        }

        @JvmStatic
        fun getMaxLuminance(context: Context): Float {
            val min = boundedPreference(context, "min_luminance", DEFAULT_MIN_LUMINANCE, 0f, 1f)
            val max = boundedPreference(context, "max_luminance", DEFAULT_MAX_LUMINANCE, 0f, 1f)
            return maxOf(min, max)
        }

        @JvmStatic
        fun isHighPerformanceMode(context: Context): Boolean {
            val sharedPreferences = PreferenceManager.getDefaultSharedPreferences(context)
            return sharedPreferences.getBoolean("high_performance_mode", false)
        }
    }

    lateinit var dbManager: DBManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)
        if (savedInstanceState == null) {
            supportFragmentManager
                .beginTransaction()
                .replace(R.id.settings, SettingsFragment())
                .commit()
        }
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        dbManager = DBManager(this)
    }

    class SettingsFragment : PreferenceFragmentCompat() {
        override fun onViewCreated(view: android.view.View, savedInstanceState: Bundle?) {
            super.onViewCreated(view, savedInstanceState)
            listView.setBackgroundColor(android.graphics.Color.TRANSPARENT)
            view.setBackgroundColor(android.graphics.Color.TRANSPARENT)
            setDivider(null)
        }

        override fun onCreatePreferences(savedInstanceState: Bundle?, rootKey: String?) {
            setPreferencesFromResource(R.xml.root_preferences, rootKey)

            val cameraLensPref = findPreference<ListPreference>("camera_lens")
            val livenessThresholdPref = findPreference<EditTextPreference>("liveness_threshold")
            val livenessLevelPref = findPreference<ListPreference>("liveness_level")
            val identifyThresholdPref = findPreference<EditTextPreference>("identify_threshold")
            val yawThresholdPref = findPreference<EditTextPreference>("yaw_threshold")
            val rollThresholdPref = findPreference<EditTextPreference>("roll_threshold")
            val pitchThresholdPref = findPreference<EditTextPreference>("pitch_threshold")
            val occlusionThresholdPref = findPreference<EditTextPreference>("occlusion_threshold")
            val eyeCloseThresholdPref = findPreference<EditTextPreference>("eyeclose_threshold")
            val mouthOpenThresholdPref = findPreference<EditTextPreference>("mouthopen_threshold")
            val faceQualityThresholdPref = findPreference<EditTextPreference>("face_quality_threshold")
            val minLuminancePref = findPreference<EditTextPreference>("min_luminance")
            val maxLuminancePref = findPreference<EditTextPreference>("max_luminance")
            val buttonRestorePref = findPreference<Preference>("restore_default_settings")

            val unitIntervalValidator = Preference.OnPreferenceChangeListener { _, newValue ->
                val value = (newValue as? String)?.toFloatOrNull()
                val valid = value != null && value.isFinite() && value in 0f..1f
                if (!valid) Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                valid
            }
            faceQualityThresholdPref?.onPreferenceChangeListener = unitIntervalValidator
            minLuminancePref?.onPreferenceChangeListener = unitIntervalValidator
            maxLuminancePref?.onPreferenceChangeListener = unitIntervalValidator

            livenessThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 1.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            identifyThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 1.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            yawThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 90.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            rollThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 90.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            pitchThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 90.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            occlusionThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 1.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            eyeCloseThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 1.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            mouthOpenThresholdPref?.setOnPreferenceChangeListener{ preference, newValue ->
                val stringPref = newValue as String
                try {
                    if(stringPref.toFloat() < 0.0f || stringPref.toFloat() > 1.0f) {
                        Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                        false
                    } else {
                        true
                    }
                } catch (e:Exception) {
                    Toast.makeText(context, getString(R.string.invalid_value), Toast.LENGTH_SHORT).show()
                    false
                }
            }

            buttonRestorePref?.setOnPreferenceClickListener {

                cameraLensPref?.value = SettingsActivity.DEFAULT_CAMERA_LENS
                livenessLevelPref?.value = SettingsActivity.DEFAULT_LIVENESS_LEVEL
                livenessThresholdPref?.text = SettingsActivity.DEFAULT_LIVENESS_THRESHOLD
                identifyThresholdPref?.text = SettingsActivity.DEFAULT_IDENTIFY_THRESHOLD
                yawThresholdPref?.text = SettingsActivity.DEFAULT_YAW_THRESHOLD
                rollThresholdPref?.text = SettingsActivity.DEFAULT_ROLL_THRESHOLD
                pitchThresholdPref?.text = SettingsActivity.DEFAULT_PITCH_THRESHOLD
                occlusionThresholdPref?.text = SettingsActivity.DEFAULT_OCCLUSION_THRESHOLD
                eyeCloseThresholdPref?.text = SettingsActivity.DEFAULT_EYECLOSE_THRESHOLD
                mouthOpenThresholdPref?.text = SettingsActivity.DEFAULT_MOUTHOPEN_THRESHOLD
                faceQualityThresholdPref?.text = SettingsActivity.DEFAULT_FACE_QUALITY_THRESHOLD
                minLuminancePref?.text = SettingsActivity.DEFAULT_MIN_LUMINANCE
                maxLuminancePref?.text = SettingsActivity.DEFAULT_MAX_LUMINANCE


                Toast.makeText(activity, getString(R.string.restored_default_settings), Toast.LENGTH_LONG).show()
                true
            }

            val buttonClearPref = findPreference<Preference>("clear_all_person")
            buttonClearPref?.setOnPreferenceClickListener {
                val settingsActivity = activity as SettingsActivity
                settingsActivity.dbManager.clearDB()

                Toast.makeText(activity, getString(R.string.cleared_all_person), Toast.LENGTH_LONG).show()
                true
            }
        }
    }
}
