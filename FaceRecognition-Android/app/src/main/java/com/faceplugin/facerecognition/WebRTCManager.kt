package com.faceplugin.facerecognition

import android.content.Context
import android.graphics.*
import android.util.Log
import io.socket.client.Socket
import org.json.JSONObject
import org.webrtc.*
import org.webrtc.PeerConnection.IceServer
import java.nio.ByteBuffer
import java.util.*

class WebRTCManager(
    private val context: Context,
    private val socket: Socket,
    private val vendorId: Int,
    private val deviceId: String
) {
    private val TAG = "WebRTCManager"
    
    private var peerConnectionFactory: PeerConnectionFactory? = null
    private var peerConnection: PeerConnection? = null
    private var videoSource: VideoSource? = null
    private var videoTrack: VideoTrack? = null
    private var surfaceTextureHelper: SurfaceTextureHelper? = null
    
    private val iceServers = listOf(
        IceServer.builder("stun:stun.l.google.com:19302").createIceServer()
    )

    init {
        initWebRTC()
    }

    private fun initWebRTC() {
        val options = PeerConnectionFactory.InitializationOptions.builder(context)
            .setEnableInternalTracer(true)
            .createInitializationOptions()
        PeerConnectionFactory.initialize(options)

        val factoryOptions = PeerConnectionFactory.Options()
        val encoderFactory = DefaultVideoEncoderFactory(
            EglBase.create().eglBaseContext, true, true
        )
        val decoderFactory = DefaultVideoDecoderFactory(EglBase.create().eglBaseContext)

        peerConnectionFactory = PeerConnectionFactory.builder()
            .setOptions(factoryOptions)
            .setVideoEncoderFactory(encoderFactory)
            .setVideoDecoderFactory(decoderFactory)
            .createPeerConnectionFactory()

        videoSource = peerConnectionFactory?.createVideoSource(false)
        videoTrack = peerConnectionFactory?.createVideoTrack("VIDEO_TRACK_ID", videoSource)
        
        setupSocketListeners()
    }

    private fun setupSocketListeners() {
        socket.on("webrtc_signal") { args ->
            val data = args[0] as JSONObject
            val type = data.getString("type")
            val signal = data.optJSONObject("signal")
            val fromRoom = data.optString("from_room")

            Log.d(TAG, "Received signal: $type from $fromRoom")

            when (type) {
                "offer" -> handleOffer(signal, fromRoom)
                "answer" -> handleAnswer(signal)
                "candidate" -> handleCandidate(signal)
            }
        }
    }

    private fun createPeerConnection(targetRoom: String) {
        val rtcConfig = PeerConnection.RTCConfiguration(iceServers)
        peerConnection = peerConnectionFactory?.createPeerConnection(rtcConfig, object : PeerConnection.Observer {
            override fun onIceCandidate(candidate: IceCandidate) {
                val signal = JSONObject().apply {
                    put("sdpMid", candidate.sdpMid)
                    put("sdpMLineIndex", candidate.sdpMLineIndex)
                    put("candidate", candidate.sdp)
                }
                sendSignal("candidate", signal, targetRoom)
            }

            override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>?) {}
            override fun onSignalingChange(state: PeerConnection.SignalingState?) {}
            override fun onIceConnectionChange(state: PeerConnection.IceConnectionState?) {
                Log.d(TAG, "ICE Connection State: $state")
            }
            override fun onIceConnectionReceivingChange(p0: Boolean) {}
            override fun onIceGatheringChange(state: PeerConnection.IceGatheringState?) {}
            override fun onAddStream(stream: MediaStream?) {}
            override fun onRemoveStream(stream: MediaStream?) {}
            override fun onDataChannel(channel: DataChannel?) {}
            override fun onRenegotiationNeeded() {}
            override fun onAddTrack(receiver: RtpReceiver?, streams: Array<out MediaStream>?) {}
        })

        peerConnection?.addTrack(videoTrack)
    }

    private fun handleOffer(sdpJson: JSONObject?, targetRoom: String) {
        if (sdpJson == null) return
        
        createPeerConnection(targetRoom)
        
        val sdp = SessionDescription(SessionDescription.Type.OFFER, sdpJson.getString("sdp"))
        peerConnection?.setRemoteDescription(object : SimpleSdpObserver() {
            override fun onSetSuccess() {
                peerConnection?.createAnswer(object : SimpleSdpObserver() {
                    override fun onCreateSuccess(sessionDescription: SessionDescription) {
                        peerConnection?.setLocalDescription(object : SimpleSdpObserver() {
                            override fun onSetSuccess() {
                                val signal = JSONObject().apply {
                                    put("sdp", sessionDescription.description)
                                    put("type", "answer")
                                }
                                sendSignal("answer", signal, targetRoom)
                            }
                        }, sessionDescription)
                    }
                }, MediaConstraints())
            }
        }, sdp)
    }

    private fun handleAnswer(sdpJson: JSONObject?) {
        if (sdpJson == null) return
        val sdp = SessionDescription(SessionDescription.Type.ANSWER, sdpJson.getString("sdp"))
        peerConnection?.setRemoteDescription(SimpleSdpObserver(), sdp)
    }

    private fun handleCandidate(candidateJson: JSONObject?) {
        if (candidateJson == null) return
        val candidate = IceCandidate(
            candidateJson.getString("sdpMid"),
            candidateJson.getInt("sdpMLineIndex"),
            candidateJson.getString("candidate")
        )
        peerConnection?.addIceCandidate(candidate)
    }

    private fun sendSignal(type: String, signal: JSONObject, targetRoom: String) {
        val data = JSONObject().apply {
            put("type", type)
            put("signal", signal)
            put("target_room", targetRoom)
            put("from_room", "device_${vendorId}_${deviceId}")
            put("vendor_id", vendorId)
            put("device_id", deviceId)
        }
        socket.emit("webrtc_signal", data)
    }

    // Connects the video source to the frames
    fun onNewFrame(bitmap: Bitmap) {
        val capturer = videoSource?.capturerObserver
        
        // Convert Bitmap to YUV or feed it to the source
        // For simplicity, we can use a custom VideoCapturer or feed raw bytes
        // A more efficient way is to use the capturerObserver directly
        
        val width = bitmap.width
        val height = bitmap.height
        val timestampNs = System.nanoTime()

        val yuvFrame = bitmapToYuv(bitmap)
        val buffer = JavaI420Buffer.wrap(
            width, height,
            yuvFrame.y, width,
            yuvFrame.u, width / 2,
            yuvFrame.v, width / 2,
            null
        )
        
        val videoFrame = VideoFrame(buffer, 0, timestampNs)
        capturer?.onFrameCaptured(videoFrame)
        videoFrame.release()
    }

    private fun bitmapToYuv(bitmap: Bitmap): YuvData {
        val width = bitmap.width
        val height = bitmap.height
        val size = width * height
        val y = ByteBuffer.allocateDirect(size)
        val u = ByteBuffer.allocateDirect(size / 4)
        val v = ByteBuffer.allocateDirect(size / 4)

        val argb = IntArray(size)
        bitmap.getPixels(argb, 0, width, 0, 0, width, height)

        for (i in 0 until height) {
            for (j in 0 until width) {
                val p = argb[i * width + j]
                val r = (p shr 16) and 0xFF
                val g = (p shr 8) and 0xFF
                val b = p and 0xFF

                val yVal = ((66 * r + 129 * g + 25 * b + 128) shr 8) + 16
                y.put(i * width + j, yVal.toByte())

                if (i % 2 == 0 && j % 2 == 0) {
                    val uVal = ((-38 * r - 74 * g + 112 * b + 128) shr 8) + 128
                    val vVal = ((112 * r - 94 * g - 18 * b + 128) shr 8) + 128
                    u.put((i / 2) * (width / 2) + (j / 2), uVal.toByte())
                    v.put((i / 2) * (width / 2) + (j / 2), vVal.toByte())
                }
            }
        }
        return YuvData(y, u, v)
    }

    private data class YuvData(val y: ByteBuffer, val u: ByteBuffer, val v: ByteBuffer)

    open class SimpleSdpObserver : SdpObserver {
        override fun onCreateSuccess(sessionDescription: SessionDescription) {}
        override fun onSetSuccess() {}
        override fun onCreateFailure(error: String?) { Log.e("WebRTC", "SDP Create Failure: $error") }
        override fun onSetFailure(error: String?) { Log.e("WebRTC", "SDP Set Failure: $error") }
    }
    
    fun dispose() {
        peerConnection?.dispose()
        peerConnectionFactory?.dispose()
        videoSource?.dispose()
    }
}
