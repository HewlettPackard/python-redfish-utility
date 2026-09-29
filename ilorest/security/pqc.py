###
# Copyright 2016-2026 Hewlett Packard Enterprise, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
###

# -*- coding: utf-8 -*-
"""PQC crypto-agility helpers for iLOrest.

The shared PQC primitives (mode handling, feature detection, TLS group
resolution) have a single canonical implementation in the transport library
(:mod:`redfish.rest.pqc`). This module **re-exports** those primitives so the
CLI and library never drift, and adds only the CLI-specific pieces:

* :func:`build_ssl_context` -- a ``requests``/``verify``-oriented context builder
  used by CLI code paths (distinct from the library's urllib3-oriented
  ``build_pqc_ssl_context``).
* :class:`CryptoCapabilities` -- the per-target descriptor gated on iLO
  generation, consumed by the raw-command layer.

Generation gating summary:

* iLO5 / iLO6 -- No PQC; classical TLS only.
* iLO7 -- PQC-TLS candidate; hybrid mode (``X25519MLKEM768`` + classical
  fallbacks). No PQC certificate algorithms.
* iLO8+ -- Full PQC support: extended KEM group set (``ILO8_KEM_GROUPS``),
  strict mode recommended, and PQC certificate algorithms (ML-DSA family).

Requires ``python-ilorest-library`` new enough to provide ``redfish.rest.pqc``
(see the pinned minimum in ``setup.py``).
"""

import logging
import ssl

# Single source of truth: the shared primitives live in the transport library.
from redfish.rest.pqc import (  # noqa: F401  (re-exported for CLI consumers/tests)
    CLASSICAL_GROUPS,
    DEFAULT_KEM_GROUP,
    DEFAULT_MODE,
    ILO7_KEM_GROUPS,
    ILO8_KEM_GROUPS,
    PQC_MODE_ENV_VAR,
    PQC_MODE_HYBRID,
    PQC_MODE_OFF,
    PQC_MODE_STRICT,
    VALID_MODES,
    PQCNotAvailableError,
    is_pqc_available,
    kem_groups_for_generation,
    normalize_mode,
    resolve_groups,
    resolve_mode_from_env,
)

# Wrapped re-exports of library-internal helpers.  These are private in the
# transport library but needed by the CLI's build_ssl_context / CryptoCapabilities.
# Wrapping insulates callers from future renames in the library.
from redfish.rest.pqc import _apply_groups as _lib_apply_groups
from redfish.rest.pqc import _mode_from_generation as _lib_mode_from_generation


def apply_groups(context, groups, strict=False):
    """Apply TLS group list to *context* (delegates to transport library)."""
    return _lib_apply_groups(context, groups, strict=strict)


def mode_from_generation(generation):
    """Return the recommended PQC mode string for an iLO generation."""
    return _lib_mode_from_generation(generation)


LOGGER = logging.getLogger(__name__)

__all__ = [
    # Re-exported shared primitives (canonical impl in redfish.rest.pqc)
    "PQC_MODE_OFF",
    "PQC_MODE_HYBRID",
    "PQC_MODE_STRICT",
    "VALID_MODES",
    "PQC_MODE_ENV_VAR",
    "DEFAULT_MODE",
    "DEFAULT_KEM_GROUP",
    "CLASSICAL_GROUPS",
    "ILO7_KEM_GROUPS",
    "ILO8_KEM_GROUPS",
    "PQCNotAvailableError",
    "normalize_mode",
    "resolve_mode_from_env",
    "is_pqc_available",
    "resolve_groups",
    "kem_groups_for_generation",
    # CLI-specific
    "build_ssl_context",
    "CryptoCapabilities",
    # PQC cert algorithm catalogues
    "ILO7_CERT_ALGORITHMS",
    "ILO8_CERT_ALGORITHMS",
]

# ---------------------------------------------------------------------------
# iLO generation thresholds for PQC feature gating
# ---------------------------------------------------------------------------
# iLO generation at/above which a target is treated as a PQC-TLS candidate.
_PQC_CANDIDATE_MIN_GENERATION = 7

# iLO generation at/above which strict PQC mode is recommended and PQC
# certificate algorithms are available.
_PQC_STRICT_MIN_GENERATION = 8

# ---------------------------------------------------------------------------
# iLO PQC certificate algorithm catalogues
# ---------------------------------------------------------------------------
# iLO7 (Level III): ML-DSA-44 and ML-DSA-65 certificate signatures.
ILO7_CERT_ALGORITHMS = ("ML-DSA-44", "ML-DSA-65")

# ML-DSA (Module Lattice Digital Signature Algorithm, NIST FIPS 204) signing
# algorithms supported for iLO8 TLS certificates.  Security level increases
# from ML-DSA-44 (level 2) to ML-DSA-87 (level 5).
ILO8_CERT_ALGORITHMS = ("ML-DSA-44", "ML-DSA-65", "ML-DSA-87")


# ---------------------------------------------------------------------------
# CLI-specific SSLContext construction (verify/cafile oriented)
# ---------------------------------------------------------------------------
def build_ssl_context(
    mode,
    *,
    kem_group=None,
    verify=False,
    cafile=None,
    base_context=None,
    pqc_available=None,
    generation=None,
):
    """Build (or augment) an ``SSLContext`` configured for *mode*.

    Args:
        mode: A PQC mode string (``"off"`` | ``"hybrid"`` | ``"strict"``).
        kem_group: Optional override for the primary hybrid KEM group name.
        verify: Whether to require server certificate verification.
        cafile: Path to a CA bundle used when *verify* is ``True``.
        base_context: Optional existing :class:`ssl.SSLContext` to augment
            instead of creating a fresh one.
        pqc_available: Optional bool override for feature detection.
        generation: Optional iLO generation. When *kem_group* is not supplied it
            selects the generation-appropriate KEM group list (iLO8+ offers the
            Level-V ``MLKEM1024`` groups a strict iLO8 requires; iLO7 offers the
            Level-III hybrids). When ``None`` the Level-III default is used.

    Returns:
        A configured :class:`ssl.SSLContext`.

    Raises:
        PQCNotAvailableError: When ``strict`` mode is requested but the runtime
            cannot select PQC TLS groups.
    """
    mode = normalize_mode(mode)

    context = base_context if base_context is not None else _build_base_context(verify=verify, cafile=cafile)

    _apply_verify_policy(context, verify=verify, cafile=cafile)

    if pqc_available is None:
        pqc_available = is_pqc_available()

    groups = resolve_groups(mode, kem_group=kem_group, available=pqc_available, generation=generation)
    if groups:
        apply_groups(context, groups, strict=(mode == PQC_MODE_STRICT))

    return context


def _build_base_context(verify=False, cafile=None):
    """Create a fresh client TLS context with the requested verify policy."""
    context = ssl.create_default_context(cafile=cafile if verify else None)
    _apply_verify_policy(context, verify=verify, cafile=cafile)
    try:
        context.minimum_version = ssl.TLSVersion.TLSv1_2
    except (AttributeError, ValueError):  # pragma: no cover - old runtimes
        pass
    return context


def _apply_verify_policy(context, verify=False, cafile=None):
    """Apply the certificate-verification policy to *context*."""
    if verify:
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if cafile and hasattr(context, "load_verify_locations"):
            try:
                context.load_verify_locations(cafile=cafile)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.debug("Could not load CA file %r: %s", cafile, exc)
    else:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Crypto capability descriptor (CLI-specific: iLO generation gating)
# ---------------------------------------------------------------------------
class CryptoCapabilities:
    """Per-target crypto capability descriptor.

    Summarizes what PQC features are available on a specific iLO target,
    derived from its hardware generation.  Instances are typically built via
    :meth:`from_generation` and cached in-process by :class:`RawCommandBase`.

    Attributes:
        ilo_generation (int or None): The detected iLO hardware generation.
        sec_state (int or None): The cached security state (1=factory,
            3=production, 4=HighSecurity, 5=FIPS, 6=SuiteB).
        tls_pqc_groups (list): Ordered TLS KEM groups to advertise for PQC.
            Empty for iLO5/6 (no PQC).
        cert_pqc_algs (list): PQC signing algorithms available for iLO TLS
            certificate generation.  Non-empty only for iLO8+.
        source (str): Provenance tag (``"static-matrix"``, ``"cache"``).
    """

    def __init__(
        self,
        ilo_generation=None,
        sec_state=None,
        tls_pqc_groups=None,
        cert_pqc_algs=None,
        source="static-matrix",
    ):
        self.ilo_generation = ilo_generation
        self.sec_state = sec_state
        self.tls_pqc_groups = list(tls_pqc_groups) if tls_pqc_groups else []
        self.cert_pqc_algs = list(cert_pqc_algs) if cert_pqc_algs else []
        self.source = source

    @classmethod
    def from_generation(cls, generation, sec_state=None, source="static-matrix"):
        """Build a descriptor from an iLO generation using the static gate.

        Generation mapping:

        * iLO5 / iLO6 (gen < 7): No PQC support.
        * iLO7 (gen == 7): PQC-TLS hybrid mode with the primary KEM group
          (``X25519MLKEM768``) and classical fallbacks.
        * iLO8+ (gen >= 8): Full PQC support — extended KEM group set from
          :data:`ILO8_KEM_GROUPS`, strict mode recommended, and PQC certificate
          algorithms from :data:`ILO8_CERT_ALGORITHMS`.

        Args:
            generation: Raw iLO generation value (int, float, or string).
            sec_state: Optional security state to attach to the descriptor.
            source: Provenance tag for the descriptor.

        Returns:
            A new :class:`CryptoCapabilities` instance.
        """
        gen = _coerce_generation(generation)
        groups = []
        cert_algs = []

        if gen is not None and gen >= _PQC_CANDIDATE_MIN_GENERATION:
            if gen >= _PQC_STRICT_MIN_GENERATION:
                # iLO8+: broader KEM selection (Level V first) and PQC cert algorithms.
                groups = list(ILO8_KEM_GROUPS)
                cert_algs = list(ILO8_CERT_ALGORITHMS)
            else:
                # iLO7: Level-III KEM groups (768-bit hybrids) and Level-III cert algorithms.
                groups = list(ILO7_KEM_GROUPS)
                cert_algs = list(ILO7_CERT_ALGORITHMS)

        return cls(
            ilo_generation=gen,
            sec_state=sec_state,
            tls_pqc_groups=groups,
            cert_pqc_algs=cert_algs,
            source=source,
        )

    @classmethod
    def from_dict(cls, data):
        """Reconstruct a descriptor from a cached dict (tolerant of missing keys)."""
        data = data or {}
        return cls(
            ilo_generation=data.get("ilo_generation"),
            sec_state=data.get("sec_state"),
            tls_pqc_groups=data.get("tls_pqc_groups") or [],
            cert_pqc_algs=data.get("cert_pqc_algs") or [],
            source=data.get("source", "cache"),
        )

    def supports_pqc_tls(self):
        """Return ``True`` if this target is a PQC-TLS candidate."""
        return bool(self.tls_pqc_groups)

    def supports_pqc_certs(self):
        """Return ``True`` if firmware advertised PQC/hybrid CSR algorithms."""
        return bool(self.cert_pqc_algs)

    def recommended_pqc_mode(self):
        """Return the recommended PQC mode for this target's generation.

        Mode recommendations by generation:

        * iLO5 / iLO6 -- ``"off"`` (no PQC TLS support).
        * iLO7 -- ``"hybrid"`` (adds a PQC KEM group alongside classical ones).
        * iLO8+ -- ``"strict"`` (require PQC; refuse to downgrade to classical).

        Returns:
            str: One of :data:`PQC_MODE_OFF`, :data:`PQC_MODE_HYBRID`, or
            :data:`PQC_MODE_STRICT`.
        """
        gen = self.ilo_generation
        if gen is None:
            return PQC_MODE_OFF
        if gen >= _PQC_STRICT_MIN_GENERATION:
            return PQC_MODE_STRICT
        if gen >= _PQC_CANDIDATE_MIN_GENERATION:
            return PQC_MODE_HYBRID
        return PQC_MODE_OFF

    def to_dict(self):
        """Serialize to a JSON-friendly dict for the capability cache."""
        return {
            "ilo_generation": self.ilo_generation,
            "sec_state": self.sec_state,
            "tls_pqc_groups": list(self.tls_pqc_groups),
            "cert_pqc_algs": list(self.cert_pqc_algs),
            "source": self.source,
        }

    def __repr__(self):  # pragma: no cover - debugging aid
        return (
            "CryptoCapabilities(ilo_generation=%r, sec_state=%r, "
            "tls_pqc_groups=%r, cert_pqc_algs=%r, source=%r)"
            % (
                self.ilo_generation,
                self.sec_state,
                self.tls_pqc_groups,
                self.cert_pqc_algs,
                self.source,
            )
        )


def _coerce_generation(generation):
    """Coerce a generation value to an int, or ``None`` if not parseable."""
    if generation is None:
        return None
    if isinstance(generation, bool):  # guard: bool is an int subclass
        return None
    if isinstance(generation, (int, float)):
        # Guard against NaN and Inf which are valid floats but not valid ints.
        try:
            return int(generation)
        except (ValueError, OverflowError):
            return None
    try:
        return int(float(str(generation).strip()))
    except (TypeError, ValueError):
        return None


def make_pqc_session(url=None, generation=None):
    """Return a ``requests.Session`` with PQC-aware TLS for direct iLO HTTPS calls.

    This is the project-wide factory for any code that needs to call an iLO
    endpoint directly via ``requests`` rather than through the Redfish library.
    It injects a custom :class:`ssl.SSLContext` configured with the widest KEM
    group list (ML-KEM-1024 first) so that both iLO7 (hybrid) and iLO8 (CNSA
    2.0 Level-V) accept the TLS handshake.

    Environment proxies are always bypassed (``trust_env=False``) because iLO
    addresses are either link-local (16.1.15.1) or direct rack management IPs
    that should never transit a corporate HTTP proxy.

    When PQC is unavailable in the runtime (e.g. OpenSSL < 3.x), the function
    degrades gracefully by returning a plain ``requests.Session`` so existing
    behaviour on iLO5/6/7 is preserved.

    Args:
        url: Reserved for future generation-aware group selection; currently
            unused. Pass the target URL for forward-compatibility.
        generation: Optional iLO generation integer; when supplied, limits the
            KEM group list to the generation-specific set.  Defaults to
            ``_PQC_STRICT_MIN_GENERATION`` (widest superset, safe for all
            PQC-capable iLOs).

    Returns:
        A configured :class:`requests.Session`.
    """
    import requests
    from requests.adapters import HTTPAdapter

    session = requests.Session()
    session.trust_env = False  # never proxy iLO addresses

    effective_gen = generation if generation is not None else _PQC_STRICT_MIN_GENERATION
    try:
        ssl_ctx = build_ssl_context(resolve_mode_from_env(), verify=False, generation=effective_gen)
    except Exception as exc:
        LOGGER.debug("make_pqc_session: could not build PQC SSL context (%s); using default TLS", exc)
        ssl_ctx = None

    if ssl_ctx is not None:

        class _PQCAdapter(HTTPAdapter):
            """HTTPAdapter that injects a custom ssl_context into urllib3."""

            def __init__(self, ctx, **kwargs):
                self._ssl_context = ctx
                super().__init__(**kwargs)

            def init_poolmanager(self, *args, **kwargs):
                kwargs["ssl_context"] = self._ssl_context
                super().init_poolmanager(*args, **kwargs)

            def proxy_manager_for(self, proxy, **proxy_kwargs):
                proxy_kwargs["ssl_context"] = self._ssl_context
                return super().proxy_manager_for(proxy, **proxy_kwargs)

        session.mount("https://", _PQCAdapter(ssl_ctx))

    return session
