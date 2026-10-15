"""
static_twin.py
REPS Digital Twin - static load channel, v1.0.0
CpE-1 Fall 2026, Cyber-Attack Modeling and Dataset Generation

A lightweight behavioral reference for the two load cells under static load.
It answers one question: given the commanded load and its position on the span,
what should each load cell read, and how far off is the observation?

Model
-----
    true_mass_kg  = mass_calibration[nominal_label]
    counts_cell   = offset[pos][cell] + gain[pos][cell] * true_mass_kg

The model is LINEAR in true mass. The apparent concavity in the nominal
labels is a mass-labeling error, not a load-cell nonlinearity: see
fit_static_twin.py and the Week 5 findings. Applying a nonlinear fit to the
nominal labels would fit that labeling error, not the physics.

The mass calibration table is PROVISIONAL, inferred from the load cells
themselves and anchored at 0 kg and 1.0 kg. It is superseded the moment ME-2
puts the physical masses on a scale.

Usage
-----
    from reps_twin import load_default
    twin = load_default()
    twin.predict_total(0.25, "PC")          -> expected total counts
    twin.residual_kg(observed_total, 0.25, "PC")
    twin.severity(observed_total, 0.25, "PC")
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COEFFS = os.path.join(_HERE, "coefficients", "twin_static_v1.0.0.json")

CELLS = ("left", "right")


class TwinError(ValueError):
    """Raised when the twin is asked for a prediction outside its validated envelope."""


@dataclass
class Bands:
    """Severity bands, expressed in multiples of the reference sigma."""
    s1: float = 1.0
    s2: float = 3.0
    s3: float = 10.0

    def band(self, n_sigma: float, eps: float = 1e-9) -> str:
        a = abs(n_sigma)
        if a < self.s1 - eps:
            return "S0"
        if a < self.s2 - eps:
            return "S1"
        if a < self.s3 - eps:
            return "S2"
        return "S3"


class StaticLoadTwin:
    def __init__(self, coeffs: dict):
        self.version = coeffs["twin_version"]
        self.source = coeffs.get("fitted_from", "unknown")
        self._gain = coeffs["gain_counts_per_kg"]
        self._offset = coeffs["offset_counts"]
        self._mass_cal = {float(k): float(v) for k, v in coeffs["mass_calibration_kg"].items()}
        self._sigma = coeffs["sigma_kg"]
        self._envelope = coeffs["validated_envelope"]
        self.bands = Bands(**coeffs.get("severity_bands", {}))
        self.notes = coeffs.get("notes", [])

    # -- calibration -------------------------------------------------------
    def true_mass(self, nominal_kg: float, strict: bool = True) -> float:
        """Map a recorded nominal load label onto the estimated true mass."""
        key = round(float(nominal_kg), 6)
        if key in self._mass_cal:
            return self._mass_cal[key]
        if strict:
            raise TwinError(
                f"nominal load {nominal_kg} kg has no mass calibration. "
                f"Calibrated levels: {sorted(self._mass_cal)}. "
                "Pass strict=False to fall back to the nominal label."
            )
        return float(nominal_kg)

    def positions(self):
        return sorted(self._gain)

    # -- forward prediction -------------------------------------------------
    def predict_cells(self, nominal_kg: float, position: str,
                      strict: bool = True) -> Dict[str, float]:
        if position not in self._gain:
            raise TwinError(f"unknown position {position!r}; known: {self.positions()}")
        m = self.true_mass(nominal_kg, strict=strict)
        return {c: self._offset[position][c] + self._gain[position][c] * m for c in CELLS}

    def predict_total(self, nominal_kg: float, position: str, strict: bool = True) -> float:
        c = self.predict_cells(nominal_kg, position, strict=strict)
        return c["left"] + c["right"]

    def predict_left_fraction(self, nominal_kg: float, position: str,
                              strict: bool = True) -> float:
        c = self.predict_cells(nominal_kg, position, strict=strict)
        tot = c["left"] + c["right"]
        return c["left"] / tot if tot else float("nan")

    def sensitivity(self, position: str) -> float:
        """Total counts per kg at this position, used to express residuals in kg."""
        return self._gain[position]["left"] + self._gain[position]["right"]

    # -- inverse and residuals ---------------------------------------------
    def infer_mass(self, observed_total: float, position: str) -> float:
        off = self._offset[position]["left"] + self._offset[position]["right"]
        return (observed_total - off) / self.sensitivity(position)

    def residual_kg(self, observed_total: float, nominal_kg: float, position: str,
                    strict: bool = True) -> float:
        """Observed minus expected, in kg. Positive means the cells read heavy."""
        exp = self.predict_total(nominal_kg, position, strict=strict)
        return (observed_total - exp) / self.sensitivity(position)

    def residual_sigma(self, observed_total: float, nominal_kg: float, position: str,
                       reference: str = "twin", strict: bool = True) -> float:
        return self.residual_kg(observed_total, nominal_kg, position,
                                strict=strict) / self.sigma(reference)

    def left_fraction_residual(self, observed_left: float, observed_right: float,
                               nominal_kg: float, position: str,
                               strict: bool = True) -> float:
        tot = observed_left + observed_right
        if not tot:
            return float("nan")
        return observed_left / tot - self.predict_left_fraction(nominal_kg, position,
                                                                strict=strict)

    # -- severity -----------------------------------------------------------
    def sigma(self, reference: str = "twin") -> float:
        """'twin' = run-level held-out model error. 'sensor' = within-run noise floor."""
        if reference not in self._sigma:
            raise TwinError(f"unknown sigma reference {reference!r}; "
                            f"known: {sorted(self._sigma)}")
        return self._sigma[reference]

    def severity(self, observed_total: float, nominal_kg: float, position: str,
                 reference: str = "twin", strict: bool = True) -> str:
        return self.bands.band(
            self.residual_sigma(observed_total, nominal_kg, position,
                                reference=reference, strict=strict))

    # -- envelope -----------------------------------------------------------
    def in_envelope(self, nominal_kg: float, position: str,
                    temperature_c: Optional[float] = None,
                    vibration_pwm: int = 0) -> Tuple[bool, str]:
        """The twin is only validated where ME-2 actually collected. Check before trusting."""
        e = self._envelope
        if position not in self._gain:
            return False, f"position {position!r} not fitted"
        if round(float(nominal_kg), 6) not in self._mass_cal:
            return False, f"load {nominal_kg} kg outside calibrated levels {sorted(self._mass_cal)}"
        if vibration_pwm != 0:
            return False, "twin v1 covers motor-off runs only; vibration not modeled"
        if temperature_c is not None:
            lo, hi = e["temperature_c"]
            if not lo <= temperature_c <= hi:
                return False, f"temperature {temperature_c} C outside fitted range {lo}-{hi}"
        return True, "ok"


def load_default(path: str = DEFAULT_COEFFS) -> StaticLoadTwin:
    with open(path) as fh:
        return StaticLoadTwin(json.load(fh))
