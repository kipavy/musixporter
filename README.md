## Musixporter

### Installation

You can also skip installation and just replace all `musixporter` commands with:

```sh
uvx --refresh --from git+https://github.com/kipavy/musixporter.git musixporter
```

but if you prefer to install it into a virtual environment, do:
```sh
uv venv
uv pip install git+https://github.com/kipavy/musixporter.git
```

### Usage

Examples:

Export from YT-Music Playlist to [Monochrome](https://monochrome.samidy.com/):

```sh
musixporter ytmusic --yt-playlist PLjfeWyMu9MJi_1aaHr4ge5uGZ3d3vcN2M
```

### Import into Monochrome

Import the generated `monochrome_tidal_import.json` file into Monochrome.

![](https://private-user-images.githubusercontent.com/182520/531663753-3183857f-1e33-4815-9d02-08f1b5d5b16f.png?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3Njc2NDk1MTQsIm5iZiI6MTc2NzY0OTIxNCwicGF0aCI6Ii8xODI1MjAvNTMxNjYzNzUzLTMxODM4NTdmLTFlMzMtNDgxNS05ZDAyLTA4ZjFiNWQ1YjE2Zi5wbmc_WC1BbXotQWxnb3JpdGhtPUFXUzQtSE1BQy1TSEEyNTYmWC1BbXotQ3JlZGVudGlhbD1BS0lBVkNPRFlMU0E1M1BRSzRaQSUyRjIwMjYwMTA1JTJGdXMtZWFzdC0xJTJGczMlMkZhd3M0X3JlcXVlc3QmWC1BbXotRGF0ZT0yMDI2MDEwNVQyMTQwMTRaJlgtQW16LUV4cGlyZXM9MzAwJlgtQW16LVNpZ25hdHVyZT1hZDdjYTRiOWIwOTNmZmE4ZmViMDQ0ZTJjNzc1ZGJmZjNhMjhiZGMxMDQyMDZkNzM4ZmRkYjU1YWU2MGJkMTllJlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCJ9.dA6nSCJzfoTj-kBe8orNX2HV6BgcdsQB2FksdNLdrzM)