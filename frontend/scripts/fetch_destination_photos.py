"""Download only manually verified, allowlisted Commons previews; never ML data.

Run from any directory with the project .venv Python (requests and Pillow).
Review photo_sources.json/source pages before adding or changing a source.
This tool does not infer subjects, author names or licensing from filenames.
"""
import hashlib
import io
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 2 * 1024 * 1024


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    sources = json.loads((ROOT / 'photo_sources.json').read_text(encoding='utf-8'))
    catalog = {}
    selected_ids = {entry['destination_id'] for entry in sources}
    with (ROOT.parent / 'data/processed/international/catalog.jsonl').open(encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            if row['destination_id'] in selected_ids:
                catalog[row['destination_id']] = row
    output = ROOT / 'public/images/destinations'
    output.mkdir(parents=True, exist_ok=True)
    manifest = {}
    destination = ROOT / 'src/data/destinationPhotos.json'
    cached = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
    session = requests.Session()
    session.headers['User-Agent'] = 'HumSafar/1.0 (university destination-photo attribution verification)'
    for entry in sources:
        record = catalog[entry['destination_id']]
        if not (record['name'] == entry['name'] and record['kind'] == 'attraction'
                and record['country'] == entry.get('country', 'Pakistan')
                and record['data_source'] == entry.get('data_source', 'pakistan_tourism')):
            raise ValueError('Photo source does not match the exact catalog identity/location/type')
        previous = cached.get(entry['destination_id'], {})
        if (all(previous.get(k) == v for k, v in entry.items()) and previous.get('variants')
                and all((ROOT / 'public' / v['src'].lstrip('/')).is_file()
                        and hashlib.sha256((ROOT / 'public' / v['src'].lstrip('/')).read_bytes()).hexdigest() == v['sha256']
                        for v in previous['variants'])):
            manifest[entry['destination_id']] = previous
            print(entry['name'], 'verified local files reused')
            continue
        filename = entry['file'].replace(' ', '_')
        digest = hashlib.md5(filename.encode('utf-8')).hexdigest()
        path = f'{digest[0]}/{digest[:2]}/{quote(filename)}'
        url = f'https://thumb.wikimedia.org/wikipedia/commons/thumb/{path}/{entry["preview_width"]}px-{quote(filename)}'
        with session.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            if not response.headers.get('Content-Type', '').startswith('image/'):
                raise ValueError('Expected an image, not an error page')
            chunks = bytearray()
            for chunk in response.iter_content(65536):
                chunks.extend(chunk)
                if len(chunks) > LIMIT:
                    raise ValueError('Preview exceeded 2 MiB limit')
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(chunks))).convert('RGB')
        variants = []
        native_width = min(image.width, entry.get('native_width', image.width))
        for width in sorted({min(480, native_width), min(960, native_width)}):
            height = round(image.height * width / image.width)
            resized = image.resize((width, height), Image.Resampling.LANCZOS)
            target = output / f'{entry["slug"]}-{width}.webp'
            resized.save(target, 'WEBP', quality=84)
            variants.append({'src': '/images/destinations/' + target.name, 'width': width, 'height': height,
                             'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
        manifest[entry['destination_id']] = {
            **entry, 'country': record['country'], 'kind': 'attraction', 'data_source': record['data_source'],
            'source_url': 'https://commons.wikimedia.org/wiki/File:' + quote(filename),
            'download_url': url, 'retrieved_on': date.today().isoformat(),
            'download_sha256': hashlib.sha256(chunks).hexdigest(),
            'changes': 'Resized and converted to WebP; no retouching. Card display may crop edges.',
            'variants': variants,
        }
        # Retain verified provenance if a later network request is interrupted.
        destination.parent.mkdir(parents=True, exist_ok=True)
        pending = destination.with_suffix('.json.tmp')
        pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        pending.replace(destination)
        print(entry['name'], image.size, sum(v['bytes'] for v in variants), 'bytes saved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
