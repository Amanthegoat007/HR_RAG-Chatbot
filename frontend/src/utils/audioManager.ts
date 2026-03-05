// Global Audio Manager to control TTS playback
class AudioManager {
    private static instance: AudioManager;
    private currentAudio: HTMLAudioElement | null = null;
    private audioUrl: string | null = null;

    private constructor() { }

    static getInstance(): AudioManager {
        if (!AudioManager.instance) {
            AudioManager.instance = new AudioManager();
        }
        return AudioManager.instance;
    }

    setAudio(audio: HTMLAudioElement, url: string) {
        // Stop any currently playing audio before setting new one
        this.stopAudio();
        this.currentAudio = audio;
        this.audioUrl = url;
    }

    stopAudio() {
        if (this.currentAudio) {
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this.currentAudio = null;
        }
        if (this.audioUrl) {
            URL.revokeObjectURL(this.audioUrl);
            this.audioUrl = null;
        }
    }

    isPlaying(): boolean {
        return this.currentAudio !== null && !this.currentAudio.paused;
    }

    clearAudio() {
        this.currentAudio = null;
        if (this.audioUrl) {
            URL.revokeObjectURL(this.audioUrl);
            this.audioUrl = null;
        }
    }
}

export const audioManager = AudioManager.getInstance();
