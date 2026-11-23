"""Local digital notary: the only component that reads the Ed25519 private key.

keys.py (keygen/rotate/load, private side), service.py (signing and sealing logic + stdio server),
client.py (what the agent uses: it spawns the notary as a subprocess and never touches the key),
__main__.py (CLI: keygen, rotate, pubkey, serve).
Keep this file free of imports so `import mwia.notary.client` never loads key-handling code.
AI-assisted (Claude). Verified by: tests/test_notary_keys.py, test_chain.py, test_notary_process.py.
"""
