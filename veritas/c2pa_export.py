"""Bind the Veritas receipt into exported media as a C2PA Content Credential.

Sidecar receipts (veritas.lock.json) get stripped when media is uploaded to
social platforms, CDNs, or datasets. C2PA (https://c2pa.org) is the industry
standard — backed by Meta, Adobe, Microsoft, the BBC — for binding a
tamper-evident manifest *into* the media itself. This module embeds:

  - a `c2pa.created` action honestly labelling the image as AI-generated, and
  - an `org.veritas.verification` assertion carrying the full receipt (policy,
    per-critic scores, SHA-256 asset hashes).

The dev build self-signs with an ephemeral certificate chain, so the credential
validates internally; swap in a production cert to verify against the C2PA trust
list. Imports are lazy so the package loads without the optional deps.
"""

from __future__ import annotations

import datetime
import json
import os

_AI_SOURCE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


def _dev_cert_chain():
    """Generate an ephemeral CA -> leaf ES256 chain meeting the C2PA cert profile."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    pem = serialization.Encoding.PEM
    now = datetime.datetime.now(datetime.timezone.utc)

    def name(cn):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Veritas")])

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = name("Veritas Dev Root CA")
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(days=1))
          .not_valid_after(now + datetime.timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                       key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, key_cert_sign=True, crl_sign=True,
                                       encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))

    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder().subject_name(name("Veritas Dev Signer")).issuer_name(ca_name)
            .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))

    chain = leaf.public_bytes(pem) + ca.public_bytes(pem)
    key = leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return chain, key


def dev_signer():
    import c2pa
    chain, key = _dev_cert_chain()
    info = c2pa.C2paSignerInfo(alg="es256", sign_cert=chain, private_key=key, ta_url=None)
    return c2pa.Signer.from_info(info)


def _manifest(receipt: dict) -> dict:
    return {
        "claim_generator": "veritas/0.3",
        "title": "Veritas verified asset",
        "assertions": [
            {"label": "c2pa.actions",
             "data": {"actions": [{"action": "c2pa.created", "digitalSourceType": _AI_SOURCE}]}},
            {"label": "org.veritas.verification", "data": receipt},
        ],
    }


def embed_receipt(source_image_path: str, receipt: dict, out_path: str, *, signer=None) -> str:
    """Sign `source_image_path` into `out_path` with the receipt as a C2PA credential."""
    import c2pa
    signer = signer or dev_signer()
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    c2pa.Builder(_manifest(receipt)).sign_file(source_image_path, out_path, signer)
    return out_path


def read_credential(path: str) -> dict:
    """Read back the embedded C2PA manifest (for verification)."""
    import c2pa
    mime = ("image/webp" if path.endswith(".webp")
            else "image/png" if path.endswith(".png") else "image/jpeg")
    with open(path, "rb") as f:
        return json.loads(c2pa.Reader(mime, f).json())
