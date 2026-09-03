import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { API_URL } from '../config';

const MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/ogg;codecs=opus',
  'audio/mp4',
  'audio/webm',
];
const SPEECH_THRESHOLD = 0.035;
const SILENCE_THRESHOLD = 0.025;
const SILENCE_TO_STOP_MS = 1400;

const preferredMimeType = () => {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') return '';
  return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || '';
};

const voiceErrorMessage = (error) => {
  const code = String(error.response?.data?.code || '');
  if (code === 'NO_SPEECH_DETECTED') return 'No speech was detected. Please try again.';
  if (code === 'STT_BUSY' || error.response?.status === 429) return 'Voice transcription is busy. Please try again in a moment.';
  if (code === 'STT_DISABLED' || code === 'STT_UNAVAILABLE') return 'Voice input is unavailable on this server.';
  if (code === 'INVALID_AUDIO') return error.response?.data?.error || 'That recording could not be processed.';
  return 'Could not transcribe the recording. Please try again.';
};

export const useVoiceRecorder = ({ active, blocked, onTranscript, onError }) => {
  const [availability, setAvailability] = useState('unknown');
  const [phase, setPhase] = useState('idle');
  const [level, setLevel] = useState(0);
  const [speechDetected, setSpeechDetected] = useState(false);
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const audioContextRef = useRef(null);
  const sourceRef = useRef(null);
  const animationFrameRef = useRef(null);
  const transcriptionControllerRef = useRef(null);
  const chunksRef = useRef([]);
  const submitOnStopRef = useRef(true);
  const speechDetectedRef = useRef(false);
  const silenceStartedRef = useRef(null);
  const recordingStartedRef = useRef(0);
  const maxAudioSecondsRef = useRef(20);
  const activeRef = useRef(active);
  const onTranscriptRef = useRef(onTranscript);
  const onErrorRef = useRef(onError);

  useEffect(() => { activeRef.current = active; }, [active]);
  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  const cleanupAudio = useCallback(() => {
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    animationFrameRef.current = null;
    try { sourceRef.current?.disconnect(); } catch { /* already disconnected */ }
    sourceRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(() => {});
    }
    audioContextRef.current = null;
    mediaRecorderRef.current = null;
    setLevel(0);
  }, []);

  const transcribe = useCallback(async (blob, mimeType) => {
    setPhase('transcribing');
    const controller = new AbortController();
    transcriptionControllerRef.current = controller;
    try {
      const extension = mimeType.includes('mp4') ? 'm4a' : (mimeType.includes('ogg') ? 'ogg' : 'webm');
      const form = new FormData();
      form.append('audio', blob, `xchat-voice.${extension}`);
      const { data } = await axios.post(`${API_URL}/xchat/transcribe`, form, { signal: controller.signal });
      const text = String(data.text || '').trim();
      if (!text) throw new Error('Empty transcription');
      setPhase('idle');
      if (activeRef.current) onTranscriptRef.current?.(text);
    } catch (error) {
      setPhase('idle');
      if (axios.isCancel(error) || error.code === 'ERR_CANCELED') return;
      if (activeRef.current) onErrorRef.current?.(voiceErrorMessage(error));
    } finally {
      if (transcriptionControllerRef.current === controller) transcriptionControllerRef.current = null;
    }
  }, []);

  const stop = useCallback((submit = true) => {
    const recorder = mediaRecorderRef.current;
    submitOnStopRef.current = submit;
    if (!submit) {
      transcriptionControllerRef.current?.abort();
      transcriptionControllerRef.current = null;
    }
    if (recorder?.state === 'recording') {
      recorder.stop();
    } else {
      cleanupAudio();
      setPhase('idle');
    }
  }, [cleanupAudio]);

  const start = useCallback(async () => {
    if (blocked || phase !== 'idle' || availability !== 'ready') return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      onErrorRef.current?.('Voice recording is not supported by this browser.');
      return;
    }
    onErrorRef.current?.('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!activeRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        stream.getTracks().forEach((track) => track.stop());
        onErrorRef.current?.('Live microphone analysis is not supported by this browser.');
        return;
      }
      const audioContext = new AudioContextClass();
      await audioContext.resume();
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.72;
      const source = audioContext.createMediaStreamSource(stream);
      source.connect(analyser);

      const mimeType = preferredMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      streamRef.current = stream;
      audioContextRef.current = audioContext;
      sourceRef.current = source;
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];
      submitOnStopRef.current = true;
      speechDetectedRef.current = false;
      silenceStartedRef.current = null;
      recordingStartedRef.current = performance.now();
      setSpeechDetected(false);

      recorder.ondataavailable = (event) => {
        if (event.data?.size) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        submitOnStopRef.current = false;
        cleanupAudio();
        setPhase('idle');
        onErrorRef.current?.('The microphone stopped unexpectedly. Please try again.');
      };
      recorder.onstop = () => {
        const shouldSubmit = submitOnStopRef.current;
        const heardSpeech = speechDetectedRef.current;
        const recordedType = recorder.mimeType || mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type: recordedType });
        chunksRef.current = [];
        cleanupAudio();
        if (!shouldSubmit || !activeRef.current) {
          setPhase('idle');
          return;
        }
        if (!heardSpeech || !blob.size) {
          setPhase('idle');
          onErrorRef.current?.('No speech was detected. Please try again.');
          return;
        }
        transcribe(blob, recordedType);
      };

      recorder.start(250);
      setPhase('listening');
      const samples = new Uint8Array(analyser.fftSize);
      const analyse = () => {
        if (recorder.state !== 'recording') return;
        analyser.getByteTimeDomainData(samples);
        let sumSquares = 0;
        for (const sample of samples) {
          const normalized = (sample - 128) / 128;
          sumSquares += normalized * normalized;
        }
        const rms = Math.sqrt(sumSquares / samples.length);
        setLevel(Math.min(1, rms * 10));
        const now = performance.now();
        if (rms >= SPEECH_THRESHOLD) {
          if (!speechDetectedRef.current) {
            speechDetectedRef.current = true;
            setSpeechDetected(true);
          }
          silenceStartedRef.current = null;
        } else if (speechDetectedRef.current && rms < SILENCE_THRESHOLD) {
          silenceStartedRef.current ??= now;
          if (now - silenceStartedRef.current >= SILENCE_TO_STOP_MS) {
            stop(true);
            return;
          }
        } else if (rms >= SILENCE_THRESHOLD) {
          silenceStartedRef.current = null;
        }
        if (now - recordingStartedRef.current >= maxAudioSecondsRef.current * 1000) {
          stop(true);
          return;
        }
        animationFrameRef.current = requestAnimationFrame(analyse);
      };
      animationFrameRef.current = requestAnimationFrame(analyse);
    } catch (error) {
      cleanupAudio();
      setPhase('idle');
      const denied = error?.name === 'NotAllowedError' || error?.name === 'SecurityError';
      onErrorRef.current?.(denied
        ? 'Microphone permission was denied. Allow microphone access and try again.'
        : 'Could not start the microphone. Please try again.');
    }
  }, [availability, blocked, cleanupAudio, phase, stop, transcribe]);

  useEffect(() => {
    if (!active) {
      setAvailability('unknown');
      stop(false);
      return undefined;
    }
    let current = true;
    setAvailability('checking');
    axios.get(`${API_URL}/xchat/transcription/status`)
      .then(({ data }) => {
        if (!current) return;
        maxAudioSecondsRef.current = Number(data.max_audio_seconds) || 20;
        setAvailability(data.enabled && data.ready ? 'ready' : 'unavailable');
      })
      .catch(() => current && setAvailability('unavailable'));
    return () => { current = false; };
  }, [active, stop]);

  useEffect(() => () => stop(false), [stop]);

  return {
    available: availability === 'ready',
    phase,
    level,
    speechDetected,
    start,
    stop: () => stop(true),
    cancel: () => stop(false),
  };
};
