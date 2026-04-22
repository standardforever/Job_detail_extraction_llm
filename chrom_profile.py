import os
import json

base_path = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome"
)

for profile in os.listdir(base_path):
    if profile == "Default" or profile.startswith("Profile"):
        pref_path = os.path.join(base_path, profile, "Preferences")

        if os.path.exists(pref_path):
            try:
                with open(pref_path, "r") as f:
                    data = json.load(f)

                account = data.get("account_info", [])
                email = account[0]["email"] if account else "no email"

                print(f"{profile} -> {email}")
            except:
                print(f"{profile} -> (could not read)")