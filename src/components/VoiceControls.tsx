import { runGrokAgentLoop } from '@/agent/runGrokAgentLoop';
import { useProjectStore } from '@/store/projectStore';
import { useCallback, useEffect, useRef, useState } from 'react';

export function VoiceControls() {
  const [busy, setBusy] = useState(false);
  const recRef = useRef<SpeechRecognition | null>(null);
  const log = useProjectStore((s) => s.voiceLog);
  const pushVoice = useProjectStore((s) => s.pushVoice);
  const always = useProjectStore((s) => s.voiceAlwaysListen);
  const setAlways = useProjectStore((s) => s.setVoiceAlwaysListen);
  const listening = useProjectStore((s) => s.voiceListening);
  const setListening = useProjectStore((s) => s.setVoiceListening);

  const playTts = useCallback(async (text: string) => {
    try {
      const res = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error((j as { error?: string }).error || res.statusText);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      await audio.play();
      audio.onended = () => URL.revokeObjectURL(url);
    } catch (e) {
      console.warn('TTS', e);
    }
  }, []);

  const sendToGrok = useCallback(
    async (userText: string) => {
      setBusy(true);
      pushVoice({ role: 'user', text: userText });
      try {
        const { reply, error } = await runGrokAgentLoop(userText);
        const text =
          reply ||
          error ||
          'No response. Check GROK_API_KEY and that the server supports tools (/api/agent/step).';
        pushVoice({ role: 'assistant', text });
        await playTts(text);
      } finally {
        setBusy(false);
      }
    },
    [playTts, pushVoice]
  );

  useEffect(() => {
    const SR =
      (window as unknown as { SpeechRecognition?: new () => SpeechRecognition })
        .SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognition })
        .webkitSpeechRecognition;
    if (!SR) return;
    const r = new SR();
    r.lang = 'en-US';
    r.continuous = always;
    r.interimResults = false;
    r.onresult = (ev) => {
      const t = ev.results[0]?.[0]?.transcript?.trim();
      if (t) void sendToGrok(t);
      if (!always) setListening(false);
    };
    r.onerror = (ev) => {
      const code =
        (ev as SpeechRecognitionErrorEvent).error ?? 'unknown';
      const hint =
        code === 'not-allowed'
          ? 'Microphone permission denied — allow the mic for this site in the browser lock icon.'
          : code === 'network'
            ? 'Speech recognition network error.'
            : `Speech error: ${code}`;
      pushVoice({ role: 'assistant', text: `[Mic] ${hint}` });
      setListening(false);
    };
    r.onend = () => {
      if (always) r.start();
      else setListening(false);
    };
    recRef.current = r;
    return () => {
      r.stop();
      recRef.current = null;
    };
  }, [always, pushVoice, sendToGrok, setListening]);

  const clearAiFocus = useCallback(() => {
    const fn = (
      window as unknown as { __takeoffClearAiFocus?: () => void }
    ).__takeoffClearAiFocus;
    fn?.();
  }, []);

  const toggleMic = () => {
    const r = recRef.current;
    if (!r) {
      alert('Speech recognition not supported in this browser.');
      return;
    }
    if (listening) {
      r.stop();
      setListening(false);
      return;
    }
    setListening(true);
    r.start();
  };

  return (
    <div className="border-t border-ost-border bg-gradient-to-b from-[#141b27] to-[#10151f] p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={toggleMic}
          disabled={busy}
          className={`rounded-full px-4 py-2 text-sm font-semibold ${
            listening
              ? 'bg-red-600 text-white'
              : 'bg-slate-700 text-white hover:bg-slate-600'
          }`}
        >
          {listening ? '● Stop mic' : 'Mic'}
        </button>
        <label className="flex items-center gap-2 text-xs text-ost-muted">
          <input
            type="checkbox"
            checked={always}
            onChange={(e) => setAlways(e.target.checked)}
          />
          Always listen
        </label>
        {busy && (
          <span className="text-xs text-amber-300">
            Agent (Grok + tools)…
          </span>
        )}
        <button
          type="button"
          onClick={clearAiFocus}
          className="rounded border border-violet-500/40 px-2 py-1 text-[10px] text-violet-200 hover:bg-violet-900/30"
          title="Remove the purple AI focus box from this sheet"
        >
          Clear AI box
        </button>
      </div>
      <div className="max-h-32 overflow-y-auto rounded border border-ost-border/80 bg-black/30 p-2 text-xs text-slate-300">
        {log.length === 0 ? (
          <span className="text-ost-muted">Voice transcript appears here.</span>
        ) : (
          log.map((t) => (
            <div key={t.id} className="mb-1">
              <span className="text-ost-muted">{t.role}:</span> {t.text}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

interface SpeechRecognitionErrorEvent {
  error?: string;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((ev: { results: { [key: number]: { [key: number]: { transcript: string } } } }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onend: (() => void) | null;
}
