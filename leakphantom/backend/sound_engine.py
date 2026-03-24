"""
LEAKPHANTOM v2.3.1 — Sound Design Configuration
Web Audio API sound definitions sent to frontend.
All synthesis happens client-side; this module defines the sound library.
"""

# Sound library — these are Web Audio API synthesis parameters
# sent to the frontend to be materialized as AudioNodes.

SOUND_LIBRARY = {
    # Ambient low hum (continuous oscillator)
    "ambient_hum": {
        "type": "continuous",
        "oscillator": "sawtooth",
        "frequency": 55,
        "gain": 0.015,
        "filter": {"type": "lowpass", "frequency": 120, "Q": 2},
        "lfo": {"frequency": 0.1, "depth": 5},  # Slow pitch wobble
    },

    # Heartbeat — synced to leak rate
    "heartbeat": {
        "type": "trigger",
        "oscillator": "sine",
        "frequency": 40,
        "gain": 0.08,
        "envelope": {"attack": 0.01, "decay": 0.15, "sustain": 0, "release": 0.3},
        "filter": {"type": "lowpass", "frequency": 80, "Q": 5},
    },

    # Keypress click
    "click": {
        "type": "trigger",
        "oscillator": "square",
        "frequency": 800,
        "gain": 0.03,
        "envelope": {"attack": 0.001, "decay": 0.02, "sustain": 0, "release": 0.01},
        "filter": {"type": "highpass", "frequency": 600},
    },

    # New leak event — short blip
    "leak_blip": {
        "type": "trigger",
        "oscillator": "sine",
        "frequency": 440,
        "gain": 0.04,
        "envelope": {"attack": 0.005, "decay": 0.08, "sustain": 0, "release": 0.1},
        "frequency_map": {
            "wifi": 440,
            "ble": 587,
            "zigbee": 659,
            "thread": 523,
            "matter": 698,
            "zwave": 392,
        },
    },

    # Hover — rising tension
    "hover_tone": {
        "type": "continuous",
        "oscillator": "triangle",
        "frequency": 220,
        "gain": 0.02,
        "filter": {"type": "bandpass", "frequency": 300, "Q": 3},
        "pitch_rise": {"target": 440, "duration": 0.5},
    },

    # Correlation lock-in arpeggio
    "correlation_lock": {
        "type": "arpeggio",
        "notes": [440, 554, 659, 880],
        "oscillator": "triangle",
        "gain": 0.05,
        "note_duration": 0.08,
        "envelope": {"attack": 0.005, "decay": 0.06, "sustain": 0, "release": 0.1},
    },

    # Particle whoosh (noise burst)
    "particle_whoosh": {
        "type": "noise_burst",
        "gain": 0.015,
        "duration": 0.3,
        "filter": {"type": "bandpass", "frequency": 2000, "Q": 1},
        "filter_sweep": {"start": 3000, "end": 500, "duration": 0.3},
    },

    # Correlation thunk (impact)
    "correlation_thunk": {
        "type": "trigger",
        "oscillator": "sine",
        "frequency": 80,
        "gain": 0.1,
        "envelope": {"attack": 0.001, "decay": 0.2, "sustain": 0, "release": 0.4},
        "harmonics": [
            {"frequency": 160, "gain": 0.05},
            {"frequency": 40, "gain": 0.08},
        ],
    },

    # Spark (for new edge flash)
    "spark": {
        "type": "noise_burst",
        "gain": 0.06,
        "duration": 0.1,
        "filter": {"type": "highpass", "frequency": 4000},
    },

    # Glitch burst
    "glitch": {
        "type": "glitch",
        "gain": 0.04,
        "duration": 0.15,
        "segments": 8,
        "frequency_range": [100, 4000],
    },

    # Sub-bass hit (Easter egg: 666 leaks)
    "sub_bass_hit": {
        "type": "trigger",
        "oscillator": "sine",
        "frequency": 30,
        "gain": 0.15,
        "envelope": {"attack": 0.01, "decay": 0.5, "sustain": 0, "release": 1.0},
        "distortion": True,
    },

    # Konami activation
    "konami_activate": {
        "type": "arpeggio",
        "notes": [262, 330, 392, 523, 659, 784, 1047],
        "oscillator": "square",
        "gain": 0.04,
        "note_duration": 0.06,
        "envelope": {"attack": 0.002, "decay": 0.04, "sustain": 0, "release": 0.08},
        "filter": {"type": "lowpass", "frequency": 3000},
    },

    # Focus mode enter (downward sweep)
    "focus_enter": {
        "type": "trigger",
        "oscillator": "sawtooth",
        "frequency": 880,
        "gain": 0.03,
        "envelope": {"attack": 0.01, "decay": 0.4, "sustain": 0, "release": 0.2},
        "pitch_sweep": {"start": 880, "end": 220, "duration": 0.4},
        "filter": {"type": "lowpass", "frequency": 2000},
    },

    # Focus mode exit
    "focus_exit": {
        "type": "trigger",
        "oscillator": "sawtooth",
        "frequency": 220,
        "gain": 0.03,
        "envelope": {"attack": 0.01, "decay": 0.3, "sustain": 0, "release": 0.2},
        "pitch_sweep": {"start": 220, "end": 880, "duration": 0.3},
        "filter": {"type": "lowpass", "frequency": 2000},
    },
}

# Spatial panning configuration
SPATIAL_CONFIG = {
    "enabled": True,
    "listener_distance": 1.0,
    "x_range": [-1.0, 1.0],  # Maps graph X to pan position
    "y_range": [-0.3, 0.3],  # Subtle vertical panning
    "master_ducking": {
        "threshold": -20,
        "ratio": 4,
        "attack": 0.01,
        "release": 0.5,
    },
}


def get_sound_config() -> dict:
    """Return full sound configuration for the frontend."""
    return {
        "library": SOUND_LIBRARY,
        "spatial": SPATIAL_CONFIG,
        "master_volume": 0.5,
        "enabled": True,
    }
