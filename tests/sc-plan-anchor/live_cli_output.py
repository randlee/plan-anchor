"""Parse the single-document and JSONL output modes used by live CLI cases."""
import json


def parse_cli_output(output, *, jsonl=False):
    """Parse one JSON document or one JSON object per nonempty line."""
    if jsonl:
        return [json.loads(line) for line in output.splitlines() if line.strip()]
    return json.loads(output)
