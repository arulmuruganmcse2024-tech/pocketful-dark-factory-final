import os

# Stage gating: this folder's default stage; POCKETFUL_STAGE overrides it.
STAGE = int(os.environ.get("POCKETFUL_STAGE", "4"))
