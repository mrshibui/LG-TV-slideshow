#!/usr/bin/env python3
"""Build the Kodi repository data (repo/) from the addon folders in this
project.

Run this after bumping any addon's version, then commit + push the
resulting repo/ folder (via GitHub raw URLs) so Kodi's update checker
picks up the new version and offers the normal "Update" button.
"""
import hashlib
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.join(ROOT, 'repo')

ADDON_IDS = [
    'script.tvslideshow',
    'service.tvslideshow.autostart',
    'repository.muggehslideshow',
]

EXCLUDE_NAMES = {'.DS_Store', '__pycache__'}

ADDON_TAG_RE = re.compile(r'<addon\b[^>]*>')
ID_ATTR_RE = re.compile(r'\bid="([^"]+)"')
VERSION_ATTR_RE = re.compile(r'\bversion="([^"]+)"')


def read_addon_xml(addon_id):
    path = os.path.join(ROOT, addon_id, 'addon.xml')
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    tag_match = ADDON_TAG_RE.search(content)
    if not tag_match:
        raise ValueError('No <addon> tag found in %s' % path)
    id_match = ID_ATTR_RE.search(tag_match.group(0))
    version_match = VERSION_ATTR_RE.search(tag_match.group(0))
    if not id_match or not version_match:
        raise ValueError('Could not find id/version attributes in %s' % path)

    if id_match.group(1) != addon_id:
        raise ValueError(
            'addon.xml id %r does not match folder name %r' % (id_match.group(1), addon_id)
        )

    # Strip the leading <?xml ...?> declaration, keep the rest verbatim.
    body = re.sub(r'^\s*<\?xml[^>]*\?>\s*', '', content, count=1).strip()
    return version_match.group(1), body


def zip_addon(addon_id, version):
    addon_folder = os.path.join(ROOT, addon_id)
    out_dir = os.path.join(REPO_DIR, addon_id)
    os.makedirs(out_dir, exist_ok=True)

    # Keep only the current version's zip around.
    for name in os.listdir(out_dir):
        if name.endswith('.zip'):
            os.remove(os.path.join(out_dir, name))

    zip_path = os.path.join(out_dir, '%s-%s.zip' % (addon_id, version))
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(addon_folder):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_NAMES]
            for filename in filenames:
                if filename in EXCLUDE_NAMES:
                    continue
                full_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(full_path, ROOT)  # keeps "<addon_id>/..." prefix
                zf.write(full_path, rel_path)
    return zip_path


def main():
    os.makedirs(REPO_DIR, exist_ok=True)
    addon_bodies = []

    for addon_id in ADDON_IDS:
        version, body = read_addon_xml(addon_id)
        zip_path = zip_addon(addon_id, version)
        addon_bodies.append(body)
        print('packaged %s %s -> %s' % (addon_id, version, os.path.relpath(zip_path, ROOT)))

    addons_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<addons>\n'
        + '\n'.join(addon_bodies)
        + '\n</addons>\n'
    )
    # Named "addons-manifest.xml" rather than the conventional "addons.xml"
    # because raw.githubusercontent.com cached a 404 against the plain
    # "addons.xml" path back when this repo was still private, and that
    # negative cache entry never expired even long after the repo went
    # public - a fresh, never-before-requested filename has no such baggage.
    with open(os.path.join(REPO_DIR, 'addons-manifest.xml'), 'w', encoding='utf-8') as f:
        f.write(addons_xml)

    # ".md5.txt" rather than the conventional ".md5": jsdelivr (tried before
    # raw.githubusercontent.com - see git history) blocks the plain ".md5"
    # extension outright. Kodi only cares about the checksum URL, not the
    # filename, so this is kept for consistency even now that jsdelivr is
    # no longer used.
    md5 = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
    with open(os.path.join(REPO_DIR, 'addons-manifest.xml.md5.txt'), 'w', encoding='utf-8') as f:
        f.write(md5)

    print('wrote repo/addons-manifest.xml and repo/addons-manifest.xml.md5.txt (md5=%s)' % md5)


if __name__ == '__main__':
    main()
