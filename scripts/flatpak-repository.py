#!/usr/bin/env python3
"""Create discoverable, signed-repository install descriptors for a Pages site."""
import base64
import pathlib
import sys

site = pathlib.Path(sys.argv[1])
url = sys.argv[2].rstrip('/')
key = base64.b64encode(pathlib.Path(sys.argv[3]).read_bytes()).decode('ascii')
site.mkdir(parents=True, exist_ok=True)
(site / 'wondershot.flatpakrepo').write_text(f'''[Flatpak Repo]
Title=Wondershot
Url={url}/repo
Homepage=https://github.com/jackmusick/wondershot
Description=Stable Wondershot releases
GPGKey={key}
''')
(site / 'wondershot.flatpakref').write_text(f'''[Flatpak Ref]
Name=io.github.jackmusick.wondershot
Branch=stable
Title=Wondershot
Url={url}/repo
IsRuntime=false
SuggestRemoteName=wondershot
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
GPGKey={key}
''')
(site / 'index.html').write_text('''<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Wondershot for Linux</title>
<h1>Wondershot for Linux</h1>
<p><a href="wondershot.flatpakref">Install Wondershot</a> with Flatpak.</p>
<p>Future stable releases appear in your software manager and <code>flatpak update</code>.</p>
<p><a href="https://github.com/jackmusick/wondershot/releases">Release notes and other platforms</a></p>
</html>
''')
(site / '.nojekyll').touch()
