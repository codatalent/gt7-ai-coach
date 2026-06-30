"""Salsa20 decryption of the GT7 telemetry stream.

GT7 broadcasts its telemetry encrypted. Each packet carries a 4-byte seed at
offset 0x40; the initialisation vector is derived from it (XOR with the magic
constant 0xDEADBEAF) and the stream is decrypted with the first 32 bytes of the
simulator-interface key.
"""

from Crypto.Cipher import Salsa20

from .config import KEY

_MAGIC = 0xDEADBEAF


def decrypt(data):
    """Decrypt one raw GT7 UDP packet, returning the plaintext bytes."""
    oiv = data[0x40:0x44]
    iv1 = int.from_bytes(oiv, byteorder="little")
    iv2 = iv1 ^ _MAGIC
    iv  = bytearray()
    iv.extend(iv2.to_bytes(4, "little"))
    iv.extend(iv1.to_bytes(4, "little"))
    return Salsa20.new(KEY[0:32], bytes(iv)).decrypt(data)
