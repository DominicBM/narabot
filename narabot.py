#!/usr/bin/python
# -*- coding: utf-8  -*-

import os
import re
import shutil
import tempfile
import urllib

from bs4 import BeautifulSoup
import Image

class UploadBatch(set):
    def __init__(self, index_filename, *directories):
        f = open(index_filename)
        filename_arcids = {}
        lineno = 1
        for line in f:
            m = re.match('^(.+)\s+([0-9]+)$', line)
            if m:
                filename, arcid = m.groups()
                filename_arcids[filename.lower()] = int(arcid)
            else:
                raise IOError("bad mapping on line {0}: {1}"
                              .format(lineno, line))
            lineno += 1
        
        item_filenames = {}
        for directory in directories:
            for filename in os.listdir(directory):
                filename = directory + os.path.sep + filename
                basename = os.path.basename(filename.lower())
                if basename in filename_arcids:
                    arcid = filename_arcids[basename]
                    if arcid in item_filenames:
                        item_filenames[arcid] += filename
                        item_filenames[arcid].sort()
                    else:
                        item_filenames[arcid] = [filename]

        for arcid, filenames in item_filenames.items():
            files = []
            for filename in filenames:
                files.append(File.from_extension(self, filename))
            self.add(Item(arcid, *files))

class Item(object):
    def __init__(self, arcid, *files):
        self.arcid = arcid
        self.files = files
        for n in range(len(self.files)):
            files[n].item = self
            files[n].index = n

    def __getitem__(self, key):
        return self.files[key]

    def __repr__(self):
        return "Item({0}, {1})".format(self.arcid, self.files)

    @property
    def metadata(self):
        if not hasattr(self, '_metadata'):
            metadata = {'title': "",
                        'scope_and_content': "",
                        'general_notes': "",
                        'arc': "",
                        'local_identifier': "",
                        'creator': "",
                        'author': "",
                        'place': "",
                        'location': "",
                        'date': "",
                        'record_group': "",
                        'record_group_arc': "",
                        'series': "",
                        'series_arc': "",
                        'file_unit': "",
                        'file_unit_arc': "",
                        'variant_control_numbers': "",
                        'tiff': "",
                        'other versions': ""}
            metadata['arc'] = self.arcid
            
            html = urllib.urlopen('http://arcweb.archives.gov/arc/action/'
                                  'ExternalIdSearch?id={0}'
                                  .format(self.arcid)).read()
            soup1 = BeautifulSoup(html)

            metadata['title'] = soup1.find('strong', 'sFC').children.next()
            metadata['record_group'] = re.sub("Item from: ", "",
                                              soup1.find('span', 'LOD').text)
            
            for field_label in soup1.findAll("th"):
                name = re.sub(":$", "", field_label.text)
                value = field_label.next_sibling.text
                if name == "Creator(s)":
                    metadata['creator'] = value
                if name == "Contact(s)":
                    metadata['location'] = value
                if name == "Coverage Dates":
                    metadata['date'] = value
                if name == "Production Date(s)":
                    metadata['date'] = value
                if name == "Part Of":
                    m = re.match("Series: (.+)", value)
                    if m:
                        metadata['series'] = m.groups()[0]
                if name == "Variant Control Number(s)":
                    # TODO: test multiple numbers?
                    metadata['variant_control_numbers'] = value

            html = urllib.urlopen('http://arcweb.archives.gov/arc/action/'
                                  'ExternalIdSearch?id={0}'
                                  .format(self.arcid)).read()
            soup1 = BeautifulSoup(html)
            
            
            # TODO
            self._metadata = metadata
            
        return self._metadata

    @property
    def title(self):
        return self.metadata['title']

    @property
    def wikitext(self):
        template = u"""== {{{{int:filedesc}}}} ==
{{{{NARA-image-full
|Title={title}
|Scope and content={scope_and_content}
|General notes={general_notes}
|ARC={arc}
|Local identifier={local_identifier}
|Creator={creator}
|Author={author}
|Place={place}
|Location={location}
|Date={date}
|Record group={record_group}
|Record group ARC={record_group_arc}
|Series={series}
|Series ARC={series_arc}
|File unit={file_unit}
|File unit ARC={file_unit_arc}
|Variant control numbers={variant_control_numbers}
|TIFF={tiff}
|Other versions={other versions}
}}}}

== {{{{int:license}}}} ==
{{{{NARA-cooperation}}}}
{{{{PD-USGov}}}}"""
        return template.format(**self.metadata)

class File(object):
    def __init__(self, filename):
        self.filename = filename
        self.item = None
        self.index = None

    @staticmethod
    def from_extension(self, filename):
        known_exts = {'.jpg':  JPEGFile,
                      '.jpeg': JPEGFile,
                      '.tif':  TIFFFile,
                      '.tiff': TIFFFile}
        ext = os.path.splitext(filename)[1].lower()
        return known_exts[ext](filename)

    @property
    def size(self):
        return os.path.getsize(self.filename)

    def to_jpeg(self):
        new_basename = os.path.basename(self.filename[:self.filename.rindex('.')] + ".jpg")
        new_filename = tempfile.gettempdir() + os.path.sep + new_basename
        Image.open(self.filename).save(new_filename, "jpeg")
        new_file = JPEGFile(new_filename)
        new_file.item = self.item
        new_file.index = self.index
        
        return new_file

    @property
    def wiki_filename(self):
        extension = self.filename[self.filename.rindex('.'):]
        if len(self.item.files) == 1:
            return self.item.title + extension
        else:
            return self.item.title + ", page " + (self.index + 1) + \
                   os.path.basename(self.filename)

    @property
    def wikitext(self):
        return self.item.wikitext

class ImageFile(File):
    pass

class JPEGFile(ImageFile):
    def to_jpeg(self):
        return self

class TIFFFile(ImageFile):
    pass

class AudioFile(File):
    pass

class VorbisFile(AudioFile):
    pass

class VideoFile(File):
    pass

class TheoraFile(VideoFile):
    pass

class UploadBot(object):
    def __init__(self, index_filename="EAP files"):
        self.index_filename = index_filename
    
    def upload_directory(self, *directories):
        self.upload_batch(UploadBatch(self.index_filename, *directories))

    def upload_batch(self, batch):
        for item in batch:
            self.upload_item(item)

    def upload_item(self, item):
        for file_ in item.files:
            self.upload_file(file_)

    def upload_file(self, file_):
        if self.get_duplicate_name(file_):
            self.rename_file()
            return

        if file_.size > 100 * 1024**2:
            self.upload_big_file(file_)
        else:
            self.upload_big_file(file_)
        
        if not isinstance(file_, JPEGFile):
            self.upload_file(file_.to_jpeg())
    
    def get_duplicate_name(self, file):
        pass # TODO

    def upload_big_file(self, file_):
        new_filename = "bigfiles" + \
                       os.path.sep + \
                       file_.wiki_filename
        shutil.copy(file_.filename, new_filename)
        file(new_filename + ".txt", "w").write(file_.wikitext)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='MediaWiki file uploader for NARA EAP')
    parser.add_argument('directories', metavar='DIR', type=str, nargs='+',
                        help='directory with images to upload')
    args = parser.parse_args()
    
    bot = UploadBot()
    bot.upload_directory(*args.directories)
