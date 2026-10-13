"""Upload client."""

import time

MAX_RETRIES = 5


def upload_with_retry(send, payload) -> bool:
    """Call `send(payload)` until it succeeds or the attempts are used up."""
    for _attempt in range(MAX_RETRIES):
        try:
            send(payload)
            return True
        except ConnectionError:
            time.sleep(1)
    return False
