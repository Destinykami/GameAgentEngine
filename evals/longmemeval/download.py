"""显式下载 LongMemEval cleaned split；默认写入被 .gitignore 排除的数据目录。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import urllib.request

BASE = 'https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/'
FILES = {
    'oracle': ('longmemeval_oracle.json', '~15 MB'),
    's': ('longmemeval_s_cleaned.json', '~277 MB'),
    'm': ('longmemeval_m_cleaned.json', '~2.7 GB'),
}
HERE = Path(__file__).resolve().parent
DEFAULT_DEST = HERE / 'data'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=tuple(FILES), default='oracle')
    parser.add_argument('--dest', default=str(DEFAULT_DEST))
    parser.add_argument('--base-url', default=BASE)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    name, size = FILES[args.split]
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / name
    if target.exists() and not args.force:
        print(f'已存在，跳过: {target} ({size})')
        return 0
    tmp = target.with_suffix(target.suffix + '.part')
    url = args.base_url.rstrip('/') + '/' + name
    print(f'下载 {url} -> {target} ({size})')
    try:
        with urllib.request.urlopen(url, timeout=120) as response, open(tmp, 'wb') as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    print(f'完成: {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
