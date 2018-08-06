
from setuptools import setup

setup(
  name = 'spotifyfs',
  packages = ['spotifyfs'], # this must be the same as the name above
  version = '0.1.0',
  description = 'Uses spotify API to create a filesystem with all songs',
  author = 'Paulo Costa',
  author_email = 'me@paulo.costa.nom.br',
  url = 'https://github.com/paulo-raca/spotifyfs',
  download_url = 'https://github.com/paulo-raca/spotifyfs',
  keywords = ['fuse', 'spotify'],
  entry_points = {
      'console_scripts': ['mount.spotifyfs=spotifyfs.__main__:main'],
  },
  install_requires = [
    "fusetree",
    "spotipy",
    "expiringdict",
  ]
)
