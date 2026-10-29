"""Load the workspace's shared video pool policy for native camera tools."""
import os
from pathlib import Path
import runpy
import sys


def policy_path():
    override = os.environ.get('CHIMERA_VIDEO_POOL_POLICY')
    if override:
        return Path(override).expanduser().resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sync_config import load_config
    return load_config()['repos']['5g_drone'] / 'umd_uas' / 'video_pool_policy.py'


POLICY_PATH = policy_path()
_policy = runpy.run_path(str(POLICY_PATH))
DECODER_EXTRA_SURFACES = _policy['DECODER_EXTRA_SURFACES']
CONVERTER_BUFFERS = _policy['CONVERTER_TARGET_BUFFERS']
set_pool_property = _policy['set_pool_property']

if __name__ == '__main__':
    if sys.argv[1:] != ['--shell']:
        raise SystemExit('Use --shell to read the video pool settings')
    print(f'VIDEO_DECODER_EXTRA_SURFACES={int(DECODER_EXTRA_SURFACES)}')
    print(f'VIDEO_CONVERTER_BUFFERS={int(CONVERTER_BUFFERS)}')
