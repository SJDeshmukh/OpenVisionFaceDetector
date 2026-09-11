package com.example.faceid.ml

import android.graphics.Bitmap

enum class RejectReason { CNN_SPOOF, MOIRE_PATTERN }

data class LivenessVerdict(
    val isLive: Boolean,
    val cnnResult: LivenessResult,
    val moireResult: MoireResult,
    val rejectReason: RejectReason? = null
)

/**
 * Two independent signals gate liveness, not one:
 *  1. AntiSpoofDetector — MiniFASNet V1SE+V2 CNN ensemble (learned features)
 *  2. MoireDetector — frequency-domain periodicity analysis (classical signal
 *     processing, targets screen-replay specifically)
 *
 * Both must pass. They're deliberately different *kinds* of detector (learned
 * vs. hand-engineered) so they tend to fail on different inputs — an attack
 * that slips past one has a decent chance of tripping the other. This is
 * still not a guarantee against every attack (see MoireDetector's and
 * AntiSpoofDetector's own doc comments for what each one is weak against).
 */
class LivenessGate(
    private val antiSpoof: AntiSpoofDetector,
    private val moireDetector: MoireDetector = MoireDetector()
) {
    fun evaluate(v1seCrop4x: Bitmap, v2Crop2_7x: Bitmap): LivenessVerdict {
        val cnnResult = antiSpoof.check(v1seCrop4x, v2Crop2_7x)
        val cnnLive = antiSpoof.isLive(cnnResult)

        val moireResult = moireDetector.score(v2Crop2_7x)

        val isLive = cnnLive && !moireResult.flagged
        val reason = when {
            isLive -> null
            !cnnLive -> RejectReason.CNN_SPOOF
            else -> RejectReason.MOIRE_PATTERN
        }
        return LivenessVerdict(isLive, cnnResult, moireResult, reason)
    }
}
