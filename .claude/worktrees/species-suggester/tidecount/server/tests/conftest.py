import os
import tempfile

# Set before anything imports tidecount.config, so tests never touch real data.
os.environ["TIDECOUNT_DATA"] = tempfile.mkdtemp(prefix="tidecount-test-")
