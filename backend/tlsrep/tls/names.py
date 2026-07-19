"""Human-readable names for TLS cipher suites, extensions, and signature algorithms."""

CIPHERS = {
    "0x1301": "TLS_AES_128_GCM_SHA256",
    "0x1302": "TLS_AES_256_GCM_SHA384",
    "0x1303": "TLS_CHACHA20_POLY1305_SHA256",
    "0xc02b": "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
    "0xc02f": "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
    "0xc02c": "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
    "0xc030": "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
    "0xcca9": "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305",
    "0xcca8": "TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305",
    "0xccaa": "TLS_DHE_RSA_WITH_CHACHA20_POLY1305",
    "0xc013": "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA",
    "0xc014": "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA",
    "0xc009": "TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA",
    "0xc00a": "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA",
    "0xc023": "TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256",
    "0xc024": "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA384",
    "0xc027": "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256",
    "0xc028": "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA384",
    "0x009c": "TLS_RSA_WITH_AES_128_GCM_SHA256",
    "0x009d": "TLS_RSA_WITH_AES_256_GCM_SHA384",
    "0x009e": "TLS_DHE_RSA_WITH_AES_128_GCM_SHA256",
    "0x009f": "TLS_DHE_RSA_WITH_AES_256_GCM_SHA384",
    "0x002f": "TLS_RSA_WITH_AES_128_CBC_SHA",
    "0x0035": "TLS_RSA_WITH_AES_256_CBC_SHA",
    "0x003c": "TLS_RSA_WITH_AES_128_CBC_SHA256",
    "0x003d": "TLS_RSA_WITH_AES_256_CBC_SHA256",
    "0x0033": "TLS_DHE_RSA_WITH_AES_128_CBC_SHA",
    "0x0039": "TLS_DHE_RSA_WITH_AES_256_CBC_SHA",
    "0x0067": "TLS_DHE_RSA_WITH_AES_128_CBC_SHA256",
    "0x006b": "TLS_DHE_RSA_WITH_AES_256_CBC_SHA256",
    "0x0032": "TLS_DHE_DSS_WITH_AES_128_CBC_SHA",
    "0x0038": "TLS_DHE_DSS_WITH_AES_256_CBC_SHA",
    "0x0040": "TLS_DHE_DSS_WITH_AES_128_CBC_SHA256",
    "0x006a": "TLS_DHE_DSS_WITH_AES_256_CBC_SHA256",
    "0x0051": "TLS_RSA_WITH_RC4_128_MD5",  # legacy
    "0x00ff": "TLS_EMPTY_RENEGOTIATION_INFO",
    "0x0157": "TLS_RSA_WITH_AES_256_CBC_SHA256",
    "0xc0af": "TLS_ECDHE_ECDSA_WITH_AES_256_CCM_8",
    "0xc0ad": "TLS_ECDHE_ECDSA_WITH_AES_256_CCM",
    "0xc0ae": "TLS_ECDHE_ECDSA_WITH_AES_128_CCM_8",
    "0xc0ac": "TLS_ECDHE_ECDSA_WITH_AES_128_CCM",
    "0xc0a3": "TLS_DHE_RSA_WITH_AES_256_CCM_8",
    "0xc09f": "TLS_DHE_RSA_WITH_AES_256_CCM",
    "0xc0a2": "TLS_DHE_RSA_WITH_AES_128_CCM_8",
    "0xc09e": "TLS_DHE_RSA_WITH_AES_128_CCM",
    "0xc0a1": "TLS_RSA_WITH_AES_256_CCM_8",
    "0xc09d": "TLS_RSA_WITH_AES_256_CCM",
    "0xc0a0": "TLS_RSA_WITH_AES_128_CCM_8",
    "0xc09c": "TLS_RSA_WITH_AES_128_CCM",
    "0xc05d": "TLS_ECDHE_ECDSA_WITH_ARIA_256_GCM_SHA384",
    "0xc061": "TLS_ECDHE_RSA_WITH_ARIA_256_GCM_SHA384",
    "0xc057": "TLS_DHE_RSA_WITH_ARIA_256_GCM_SHA384",
    "0xc053": "TLS_RSA_WITH_ARIA_256_GCM_SHA384",
    "0xc05c": "TLS_ECDHE_ECDSA_WITH_ARIA_128_GCM_SHA256",
    "0xc060": "TLS_ECDHE_RSA_WITH_ARIA_128_GCM_SHA256",
    "0xc056": "TLS_DHE_RSA_WITH_ARIA_128_GCM_SHA256",
    "0xc052": "TLS_RSA_WITH_ARIA_128_GCM_SHA256",
    "0xc050": "TLS_RSA_WITH_ARIA_128_CBC_SHA256",
    "0xc051": "TLS_RSA_WITH_ARIA_256_CBC_SHA384",
    "0x00a2": "TLS_DHE_DSS_WITH_AES_128_GCM_SHA256",
    "0x00a3": "TLS_DHE_DSS_WITH_AES_256_GCM_SHA384",
    "0x0107": "TLS_DHE_RSA_WITH_AES_256_GCM_SHA384",
    "0x0103": "TLS_DHE_RSA_WITH_AES_128_GCM_SHA256",
    "0xc161": "TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA",
    "0xc171": "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA",
    "0x4865": "TLS_AES_128_GCM_SHA256 (alias)",
    "0x4866": "TLS_AES_256_GCM_SHA384 (alias)",
    "0x4867": "TLS_CHACHA20_POLY1305_SHA256 (alias)",
}

EXTENSIONS = {
    "0x0000": "server_name (SNI)",
    "0x0001": "max_fragment_length",
    "0x0005": "status_request (OCSP)",
    "0x000a": "supported_groups",
    "0x000b": "ec_point_formats",
    "0x000d": "signature_algorithms",
    "0x000e": "use_srtp",
    "0x000f": "heartbeat",
    "0x0010": "application_layer_protocol_negotiation (ALPN)",
    "0x0012": "signed_certificate_timestamp",
    "0x0015": "padding",
    "0x0016": "encrypt_then_mac",
    "0x0017": "extended_master_secret",
    "0x001b": "compress_certificate",
    "0x001c": "record_size_limit",
    "0x0023": "session_ticket",
    "0x002b": "supported_versions",
    "0x002d": "psk_key_exchange_modes",
    "0x0031": "post_handshake_auth",
    "0x0033": "key_share",
    "0x0039": "quic_transport_parameters",
    "0x44cd": "delegated_credentials",
    "0xfe0d": "encrypted_client_hello",
    "0xff01": "renegotiation_info",
}

SIG_ALGOS = {
    "0x0201": "rsa_pkcs1_sha1",
    "0x0203": "ecdsa_sha1",
    "0x0301": "rsa_pkcs1_sha256 (legacy)",
    "0x0302": "rsa_pkcs1_sha384 (legacy)",
    "0x0303": "rsa_pkcs1_sha512 (legacy)",
    "0x0401": "rsa_pkcs1_sha256",
    "0x0402": "rsa_pkcs1_sha384",
    "0x0403": "ecdsa_secp256r1_sha256",
    "0x0501": "rsa_pkcs1_sha384",
    "0x0502": "ecdsa_secp384r1_sha384",
    "0x0503": "ecdsa_secp384r1_sha384",
    "0x0601": "rsa_pkcs1_sha512",
    "0x0602": "ecdsa_secp521r1_sha512",
    "0x0603": "ecdsa_secp521r1_sha512",
    "0x0804": "rsa_pss_rsae_sha256",
    "0x0805": "rsa_pss_rsae_sha384",
    "0x0806": "rsa_pss_rsae_sha512",
    "0x0807": "ed25519",
    "0x0808": "ed448",
    "0x0809": "rsa_pss_pss_sha256",
    "0x080a": "rsa_pss_pss_sha384",
    "0x080b": "rsa_pss_pss_sha512",
}

CURVES = {
    "0x0017": "secp256r1 (P-256)",
    "0x0018": "secp384r1 (P-384)",
    "0x0019": "secp521r1 (P-521)",
    "0x001d": "x25519",
    "0x001e": "x448",
    "0x0100": "ffdhe2048",
    "0x0101": "ffdhe3072",
    "0x0102": "ffdhe4096",
    "0x0103": "ffdhe6144",
    "0x0104": "ffdhe8192",
    "0x11ec": "X25519MLKEM768",
}


def resolve_hex_list(hex_list_json: str | None, lookup: dict) -> list[dict] | None:
    """Parse a JSON array of hex strings and return [{hex, name}]."""
    if not hex_list_json:
        return None
    import json
    try:
        items = json.loads(hex_list_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return [{"hex": h, "name": lookup.get(h, "")} for h in items]


def decorate(values: list[int], table: dict[str, str]) -> list[dict[str, str]]:
    """Pair each u16 with its human name: [{"value": "0x1301", "name": "..."}].

    Unknown values are still returned, named "unknown (0x…)" — an unrecognised
    cipher is exactly the kind of thing someone looking up a fingerprint wants
    to see, so it must never be silently dropped.
    """
    out = []
    for v in values:
        key = f"0x{v:04x}"
        out.append({"value": key, "name": table.get(key, f"unknown ({key})")})
    return out
