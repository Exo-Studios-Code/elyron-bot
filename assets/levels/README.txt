Drop your 11 level icon files directly into this folder, with these EXACT filenames:

1.png
2.png
3.png
4.png
5.png
6.png
7.png
8.png
9.png
10.png
challenger.png

As long as Config.LEVEL_ICON_BASE_URL (in utils/config.py) is left empty,
the bot will automatically find and attach these files from this folder -
no external hosting needed.

If you'd rather host them externally (GitHub raw URL, your own CDN, etc.)
instead, just set LEVEL_ICON_BASE_URL and this folder will be ignored.
