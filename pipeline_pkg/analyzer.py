"""
Core Processing Logic (Section 3).
Identical logic is executed online (in the cloud) and offline (on the device).
"""

import math
from typing import Dict, List, Optional, Tuple, Any

SAMPLES_PER_SECOND = 400
WINDOW_SIZE = 400
RATE_WINDOW_SECONDS = 5
RATE_WINDOW_SAMPLES = RATE_WINDOW_SECONDS * SAMPLES_PER_SECOND  # 2000 samples
PEAK_HISTORY_REQUIRED = 800
MIN_PEAK_DISTANCE = 100


def compute_peaks(
    signal_ch2: Dict[int, int],
    start_index: int,
    end_index: int,
    previous_peak_index: Optional[int] = None
) -> Tuple[List[int], Optional[int]]:
    """
    Find peaks in sensor 1, channel 2 within range [start_index, end_index].
    
    A sample i is a peak when ALL 4 of these hold:
    1. The 800 samples before it (i - 800 to i - 1), and the sample after it (i + 1), are available.
    2. It is larger than both neighbours: val[i] > val[i - 1] and val[i] > val[i + 1].
    3. It is larger than half of the maximum of the 800 samples before it:
       val[i] > 0.5 * max(val[i - 800 : i - 1]).
    4. It is at least 100 samples after the previous peak:
       i - last_peak >= 100.
       
    Returns (peaks_in_range, last_peak_index).
    """
    peaks = []
    last_peak = previous_peak_index

    # To evaluate sample i, we need i >= 800, i - 800 <= j <= i + 1 available.
    for i in range(start_index, end_index + 1):
        if i < PEAK_HISTORY_REQUIRED:
            continue
        
        # Check availability of i and i + 1
        if i not in signal_ch2 or (i + 1) not in signal_ch2:
            continue
        
        # Check availability of preceding 800 samples and sample i - 1
        # Quick check: look up all 800 preceding samples
        history_missing = False
        max_history = -float("inf")
        for j in range(i - PEAK_HISTORY_REQUIRED, i):
            val_j = signal_ch2.get(j)
            if val_j is None:
                history_missing = True
                break
            if val_j > max_history:
                max_history = val_j
                
        if history_missing:
            continue
            
        cur_val = signal_ch2[i]
        prev_val = signal_ch2[i - 1]
        next_val = signal_ch2[i + 1]
        
        # Condition 2: Larger than both neighbours
        if not (cur_val > prev_val and cur_val > next_val):
            continue
            
        # Condition 3: Larger than half of max of 800 samples before it
        if not (cur_val > 0.5 * max_history):
            continue
            
        # Condition 4: At least 100 samples after previous peak
        if last_peak is not None and (i - last_peak) < MIN_PEAK_DISTANCE:
            continue
            
        peaks.append(i)
        last_peak = i

    return peaks, last_peak


def process_window(
    window_idx: int,
    sensor1_samples: Dict[int, List[int]],
    sensor2_samples: Dict[int, List[int]],
    mode: str = "offline",
    known_peaks_in_window: Optional[List[int]] = None,
    all_peaks_cache: Optional[List[int]] = None
) -> Dict[str, Any]:
    """
    Produce the Section 3 output dictionary for window w (samples 400w to 400w + 399).
    """
    start_idx = window_idx * WINDOW_SIZE
    end_idx = start_idx + WINDOW_SIZE - 1

    # 1. Missing samples
    s1_avail = [sensor1_samples[i] for i in range(start_idx, end_idx + 1) if i in sensor1_samples]
    s2_avail = [sensor2_samples[i] for i in range(start_idx, end_idx + 1) if i in sensor2_samples]

    missing_1 = WINDOW_SIZE - len(s1_avail)
    missing_2 = WINDOW_SIZE - len(s2_avail)
    complete = (missing_1 == 0 and missing_2 == 0)

    # 2. Mean, Min, Max per channel
    # Sensor 1 has 3 channels
    if s1_avail:
        s1_ch1 = [v[0] for v in s1_avail]
        s1_ch2 = [v[1] for v in s1_avail]
        s1_ch3 = [v[2] for v in s1_avail]
        mean_s1 = [
            round(sum(s1_ch1) / len(s1_ch1), 1),
            round(sum(s1_ch2) / len(s1_ch2), 1),
            round(sum(s1_ch3) / len(s1_ch3), 1)
        ]
        min_s1 = [min(s1_ch1), min(s1_ch2), min(s1_ch3)]
        max_s1 = [max(s1_ch1), max(s1_ch2), max(s1_ch3)]
    else:
        mean_s1, min_s1, max_s1 = None, None, None

    # Sensor 2 has 2 channels
    if s2_avail:
        s2_ch1 = [v[0] for v in s2_avail]
        s2_ch2 = [v[1] for v in s2_avail]
        mean_s2 = [
            round(sum(s2_ch1) / len(s2_ch1), 1),
            round(sum(s2_ch2) / len(s2_ch2), 1)
        ]
        min_s2 = [min(s2_ch1), min(s2_ch2)]
        max_s2 = [max(s2_ch1), max(s2_ch2)]
        
        # Magnitude: Mean of sqrt(ch1^2 + ch2^2) over available sensor 2 samples
        mag_sum = sum(math.sqrt(v[0] ** 2 + v[1] ** 2) for v in s2_avail)
        magnitude = round(mag_sum / len(s2_avail), 1)
    else:
        mean_s2, min_s2, max_s2 = None, None, None
        magnitude = None

    # Format per channel structures
    if mean_s1 is not None and mean_s2 is not None:
        mean_out = {"sensor_1": mean_s1, "sensor_2": mean_s2}
        min_out = {"sensor_1": min_s1, "sensor_2": min_s2}
        max_out = {"sensor_1": max_s1, "sensor_2": max_s2}
    elif mean_s1 is not None:
        mean_out = {"sensor_1": mean_s1, "sensor_2": None}
        min_out = {"sensor_1": min_s1, "sensor_2": None}
        max_out = {"sensor_1": max_s1, "sensor_2": None}
    elif mean_s2 is not None:
        mean_out = {"sensor_1": None, "sensor_2": mean_s2}
        min_out = {"sensor_1": None, "sensor_2": min_s2}
        max_out = {"sensor_1": None, "sensor_2": max_s2}
    else:
        mean_out, min_out, max_out = None, None, None

    # 3. Heart Rate Rule
    # Rule 3: "heart_rate is null if w < 4, if any sample in those 5 seconds is missing,
    # or if there are fewer than 2 peaks."
    heart_rate = None
    if window_idx >= 4:
        # Check last 5 seconds: samples 400(w - 4) to 400(w + 1) - 1
        window_5s_start = 400 * (window_idx - 4)
        window_5s_end = 400 * (window_idx + 1) - 1

        # Check if any sample of sensor 1 in those 5 seconds is missing
        all_5s_present = True
        for idx in range(window_5s_start, window_5s_end + 1):
            if idx not in sensor1_samples:
                all_5s_present = False
                break

        if all_5s_present:
            # We can use all_peaks_cache if provided, or compute
            if all_peaks_cache is not None:
                peaks_5s = [p for p in all_peaks_cache if window_5s_start <= p <= window_5s_end]
            else:
                # Compute peaks up to window_5s_end
                ch2_map = {idx: sensor1_samples[idx][1] for idx in sensor1_samples}
                peaks_found, _ = compute_peaks(ch2_map, 0, window_5s_end)
                peaks_5s = [p for p in peaks_found if window_5s_start <= p <= window_5s_end]

            if len(peaks_5s) >= 2:
                # Mean gap between consecutive peaks, in seconds:
                # sample gap in seconds = (peak[j+1] - peak[j]) / 400.0
                gaps_sec = [(peaks_5s[j + 1] - peaks_5s[j]) / SAMPLES_PER_SECOND for j in range(len(peaks_5s) - 1)]
                mean_gap_sec = sum(gaps_sec) / len(gaps_sec)
                if mean_gap_sec > 0:
                    heart_rate = round(60.0 / mean_gap_sec, 1)

    return {
        "window": window_idx,
        "mode": mode,
        "missing_1": missing_1,
        "missing_2": missing_2,
        "complete": complete,
        "mean": mean_out,
        "min": min_out,
        "max": max_out,
        "magnitude": magnitude,
        "heart_rate": heart_rate
    }
