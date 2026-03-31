export interface SpeechPlaybackSnapshot {
  activeId: string | null;
  supported: boolean;
}

type SpeechPlaybackListener = (snapshot: SpeechPlaybackSnapshot) => void;

let activeSpeechId: string | null = null;
const playbackListeners = new Set<SpeechPlaybackListener>();

export const supportsSpeechSynthesis = () =>
  typeof window !== "undefined" && "speechSynthesis" in window;

function notifyPlaybackListeners() {
  const snapshot: SpeechPlaybackSnapshot = {
    activeId: activeSpeechId,
    supported: supportsSpeechSynthesis(),
  };

  playbackListeners.forEach((listener) => {
    listener(snapshot);
  });
}

function clearPlayback(id?: string | null) {
  if (id && activeSpeechId && activeSpeechId !== id) {
    return;
  }

  activeSpeechId = null;
  notifyPlaybackListeners();
}

export const subscribeToSpeechPlayback = (
  listener: SpeechPlaybackListener,
) => {
  playbackListeners.add(listener);
  listener({
    activeId: activeSpeechId,
    supported: supportsSpeechSynthesis(),
  });

  return () => {
    playbackListeners.delete(listener);
  };
};

export const speakText = ({
  id,
  text,
  lang,
  onEnd,
  onError,
}: {
  id: string;
  text: string;
  lang?: string;
  onEnd?: () => void;
  onError?: () => void;
}) => {
  if (!supportsSpeechSynthesis()) {
    onError?.();
    return;
  }

  const synthesis = window.speechSynthesis;
  synthesis.cancel();

  activeSpeechId = id;
  notifyPlaybackListeners();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang || "en-US";

  const languagePrefix = (lang || "en").toLowerCase();
  const matchingVoice = synthesis
    .getVoices()
    .find((voice) => voice.lang.toLowerCase().startsWith(languagePrefix));
  if (matchingVoice) {
    utterance.voice = matchingVoice;
  }

  utterance.onend = () => {
    clearPlayback(id);
    onEnd?.();
  };
  utterance.onerror = () => {
    clearPlayback(id);
    onError?.();
  };

  synthesis.speak(utterance);
};

export const stopSpeaking = (id?: string) => {
  if (!supportsSpeechSynthesis()) {
    return;
  }

  if (id && activeSpeechId && activeSpeechId !== id) {
    return;
  }

  window.speechSynthesis.cancel();
  clearPlayback(id ?? activeSpeechId);
};
