narabot
=======

MediaWiki upload bot for NARA. 

This fork was created as part of a field study project at the University of Maryland's iSchool in spring 2014.

A basic operation can be run with this command: 

    python narabot.py \
    --username "myUsername" --password "myPassword" \
    --index "/path/to/index/of/files.txt" "/path/to/folder/of/images/"

There is an additional optional "-- max-size" parameter which will instruct the bot to skip over files larger than the size specified in bytes (e.g. "-- max-size 104857600" to upload only files under 100 MB).

In order for this script to work, you will need:
* [Python 2.7](https://www.python.org/download/releases/2.7.6/)
* [Pillow](https://pypi.python.org/pypi/Pillow/)
* [Beautiful Soup](http://www.crummy.com/software/BeautifulSoup/)

The last two can be installed using [pip](http://pip.readthedocs.org/en/latest/installing.html) using "pip install pillow" and "pip install beautifulsoup4". If you are running this on Mavericks, you may encounter some issues with Pillow, however we have gotten it to work using [publicized workarounds](https://stackoverflow.com/questions/22334776/installing-pillow-pil-on-mavericks).
