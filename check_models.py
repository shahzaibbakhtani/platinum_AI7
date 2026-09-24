"""
Quick diagnostic — NOT the real prototype.
This just asks Google directly which models your API key can use,
so we stop guessing model names.
"""
import os
import requests

API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_KEY_HERE")

if API_KEY == "YOUR_KEY_HERE":
    print("No GEMINI_API_KEY set in this terminal session.")
else:
    resp = requests.get(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    )
    print(f"Status code: {resp.status_code}\n")

    if resp.status_code == 200:
        data = resp.json()
        print("Models your key can use for generateContent:\n")
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                print(f"  {m['name']}")
    else:
        print("Error response:")
        print(resp.text)
