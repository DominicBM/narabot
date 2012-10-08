#!/usr/bin/python2
# -*- coding: utf-8  -*-

from __future__ import print_function
import cgi
from collections import namedtuple
import cookielib
from datetime import date
import hashlib
import itertools
import json
import mimetools
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import urllib
import urllib2

from bs4 import BeautifulSoup, SoupStrainer
import Image


def wikitext_escape(s):
    return re.sub(r'([#<>\[\]\|\{\}|]+)', r'<nowiki>\1</nowiki>', s)


class UploadBatch(set):
    def __init__(self, index_filename, *directories):
        f = open(index_filename)
        filename_arcids = {}
        lineno = 1
        for line in f:
            m = re.match('^(.+)\s+([0-9]+)\r?$', line)
            if m:
                filename, arcid = m.groups()
                filename_arcids[filename.lower()] = int(arcid)
            else:
                raise IOError("bad mapping on line {0}: {1}"
                              .format(lineno, line))
            lineno += 1
        
        item_filenames = {}
        self.unknown_filenames = []
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
                else:
                    self.unknown_filenames.append(filename)

        for arcid, filenames in item_filenames.items():
            files = []
            for filename in filenames:
                files.append(File.from_extension(self, filename))
            self.add(Item(arcid, *files))


Author = namedtuple('Author', ['id', 'name'])
ItemDate = namedtuple('ItemDate', ['year', 'month', 'day'])
FileUnit = namedtuple('FileUnit', ['id', 'name'])
Place = namedtuple('Place', ['id', 'name', 'latitude', 'longitude'])
RecordGroup = namedtuple('RecordGroup', ['id', 'name'])
Series = namedtuple('Series', ['id', 'name'])


class Item(object):
    def __init__(self, arcid, *files):
        self.arcid = arcid
        self.files = files
        for n in range(len(self.files)):
            files[n].item = self
            files[n].index = n

        jar = cookielib.CookieJar()
        self.__opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(jar))

    def __getitem__(self, key):
        return self.files[key]

    def __repr__(self):
        return "Item({0}, {1})".format(self.arcid, self.files)

    @property
    def __item_url(self):
        return 'http://arcweb.archives.gov/arc/action/ExternalIdSearch?id=' + \
               str(self.arcid)

    @property
    def __item_page(self):
        if not hasattr(self, '__item_page_cached'):
            self.__item_page_cached = \
                BeautifulSoup(self.__opener.open(self.__item_url).read())
        return self.__item_page_cached

    @property
    def __hierarchy_page(self):
        if not hasattr(self, '__hierarchy_page_cached'):
            hier_link = \
                self.__item_page.find('a',
                    href=re.compile('showFullDescriptionTabs/hierarchy'))
            if hier_link:
                hier_url = 'http://arcweb.archives.gov' + hier_link['href']
                self.__opener.addheaders = [('Referer', self.__item_url)]
                self.__hierarchy_page_cached = \
                    BeautifulSoup(self.__opener.open(hier_url).read())
            else:
                self.__hierarchy_page_cached = None
        return self.__hierarchy_page_cached

    @property
    def authors(self):
        if not hasattr(self, '__authors'):
            try:
                self.__authors = []
                for a in self.__item_page.findAll('a',
                        href=re.compile(r'^ExecuteRelatedPeopleSearch\?')):
                    m = re.match(r'^ExecuteRelatedPeopleSearch\?id=(\d+)&',
                                 a['href'])
                    self.__authors.append(Author(int(m.group(1)), a.text))
            except:
                self.__authors = None

        return self.__authors

    @property
    def contacts(self):
        return self.__item_page.find('p', 'contacts').text.split('\n')

    @property
    def creators(self):
        if not hasattr(self, '__creators'):
            try:
                self.__creators = \
                    map(lambda s: s.strip(),
                        self.__item_page.find(text=
                                              'Creator(s):')
                        .parent.next_sibling.text.split("\n"))
            except:
                self.__creators = None

        return self.__creators

    @property
    def date(self):
        date_field = self.__item_page.find(text='Production Date(s):') or \
                     self.__item_page.find(text='Coverage Dates:') or \
                     None

        if date_field:
            date_str = date_field.parent.parent.next_sibling.text.strip()

            if re.match('\d+(?:/\d+(?:/\d+)?)?', date_str):
                date = map(int, date_str.split("/"))

                if len(date) > 2:
                    return ItemDate(date[2], date[0], date[1])
                elif len(date) > 1:
                    return ItemDate(date[1], date[0], None)
                else:
                    return ItemDate(date[0], None, None)
            else:
                return date_str
        else:
            return None

    @property
    def description(self):
        return list(self.__item_page.find('strong', 'sFC'))[0].strip()

    @property
    def file_unit(self):
        if not hasattr(self, '__file_unit'):
            try:
                treel3 = self.__hierarchy_page.find('span', 'treel3')

                name = treel3.find('span', 'hierRecord').text
                id = treel3.find('span', 'hierlocalid').strong.text
                
                self.__file_unit = FileUnit(id, name)
            except:
                self.__file_unit = None
        
        return self.__file_unit

    @property
    def general_notes(self):
        if not hasattr(self, '__general_notes'):
            try:
                self.__general_notes = \
                    self.__item_page.find(text='General Note(s):') \
                    .parent.next_sibling.text.strip()
            except:
                self.__general_notes = None

        return self.__general_notes

    @property
    def local_id(self):
        if not hasattr(self, '__local_identifier'):
            arcid_field = self.__item_page.find('strong', 'arcID').text
            m = re.match('ARC Identifier (.+) / Local Identifier (.+)',
                         arcid_field)
            self.__local_identifier = m.group(2)
            
        return self.__local_identifier

    @property
    def places(self):
        if not hasattr(self, '__places'):
            try:
                self.__places = []
                for a in self.__item_page.findAll('a',
                        href=re.compile(r'^ExecuteRelatedGeographical')):
                    m = re.match(r'^ExecuteRelatedGeographicalSearch'
                                 '\?id=(\d+)&',
                                 a['href'])
                    id = int(m.group(1))
                    name = a.text
                    latitude = None
                    longitude = None

                    try:
                        place_url = ('http://arcweb.archives.gov/arc/action/'
                                     + a['href'])
                        self.__opener.addheaders = [('Referer',
                                                     self.__item_url)]
                        soup = BeautifulSoup(self.__opener.open(place_url)
                                             .read(),
                                             parse_only=
                                             SoupStrainer('div', 'genPad'))
                        coords = \
                            soup.find(text="Coordinates:").parent \
                            .next_sibling.text
                        m = re.search('\((.+), (.+)\)', coords)
                        latitude = m.group(1)
                        longitude = m.group(2)
                    except:
                        pass
                    
                    self.__places.append(Place(id, name, latitude, longitude))
            except:
                self.__places = None

        return self.__places

    @property
    def record_group(self):
        if not hasattr(self, '__record_group'):
            try:
                treel1 = self.__hierarchy_page.find('span', 'treel1')
                name = treel1.span.strong.text.strip() + " " + \
                       treel1.find('span', 'hierRecord').text.strip()
                id = int(treel1.find('span', 'hierlocalid').strong.text)
                
                self.__record_group = RecordGroup(id, name)
            except:
                self.__record_group = None
        
        return self.__record_group

    @property
    def scope_and_content(self):
        if not hasattr(self, '__scope_and_content'):
            scope_link = \
                self.__item_page.find('a',
                    href=re.compile('showFullDescriptionTabs/scope'))
            if scope_link:
                scope_url = 'http://arcweb.archives.gov' + scope_link['href']
                self.__opener.addheaders = [('Referer', self.__item_url)]
                soup = BeautifulSoup(self.__opener.open(scope_url).read(),
                                     parse_only=SoupStrainer('div', 'genPad'))
                self.__scope_and_content = soup.text.strip()
            else:
                self.__scope_and_content = None
        
        return self.__scope_and_content

    @property
    def series(self):
        if not hasattr(self, '__series'):
            try:
                treel2 = self.__hierarchy_page.find('span', 'treel2')
                name = treel2.find('span', 'hierRecord').text.strip()
                id = int(treel2.find('span', 'hierlocalid').strong.text)
                
                self.__series = Series(id, name)
            except:
                self.__series = None
        
        return self.__series

    @property
    def variant_control_numbers(self):
        if not hasattr(self, '__variant_control_numbers'):
            try:
                self.__variant_control_numbers = \
                    map(lambda s: s.strip(),
                        self.__item_page.find(text=
                                              'Variant Control Number(s):')
                        .parent.next_sibling.text.split("\n"))
            except:
                self.__variant_control_numbers = None

        return self.__variant_control_numbers


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
    def canonical_extension(self):
        raise NotImplementedError

    @property
    def size(self):
        return os.path.getsize(self.filename)

    def to_jpeg(self):
        new_basename_root, old_ext = \
            os.path.splitext(os.path.basename(self.filename))
        new_basename = new_basename_root + '.jpg'
        new_filename = tempfile.gettempdir() + os.path.sep + new_basename

        image = Image.open(self.filename)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(new_filename, 'jpeg')
        
        new_file = JPEGFile(new_filename)
        new_file.item = self.item
        new_file.index = self.index
        
        return new_file

    @property
    def wiki_filename(self):
        if len(self.item.files) == 1:
            suffix = " - NARA - {0}{1}".format(self.item.arcid,
                                               self.canonical_extension)
        else:
            suffix = ", page {0} - NARA - {1}{2}" \
                     .format(self.index + 1,
                             self.item.arcid,
                             self.canonical_extension)

        title = self.item.description
        while len(title + suffix) > 240:
            title = re.sub('\s+\S+$', '', title)
        if title == "":
            title = self.item.description[:240 - len(suffix)]

        title = re.sub(r'#|<|>|\[|\]|\||\{|\}', '-', title)

        return title + suffix

    @property
    def os_filename(self):
        return re.sub(r'<|>|:|"|/|\\|\||\?|\*', '-', self.wiki_filename)

    @property
    def wikitext(self):
        license_text = u"""== {{int:license}} ==
{{NARA-cooperation}}
{{PD-USGov}}"""
        return license_text


class ImageFile(File):
    @property
    def wikitext(self):
        image_template_text = u"""== {{{{int:filedesc}}}} ==
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
|Other versions={other_versions}
}}}}"""

        escape = wikitext_escape

        m = {}
        m['title'] = escape(self.item.description)
        m['scope_and_content'] = escape(self.item.scope_and_content or "")
        m['general_notes'] = escape(self.item.general_notes or "")
        m['arc'] = self.item.arcid
        m['local_identifier'] = escape(self.item.local_id or "")
        m['creator'] = "<br/>\n".join(map(escape, self.item.creators or []))
        
        authors = []
        for author in self.item.authors or []:
            authors.append("{{{{NARA-Author|{0}|{1}}}}}"
                           .format(escape(author.name), author.id))
        m['author'] = "<br/>\n".join(authors)

        places = []
        for place in self.item.places or []:
            if place.latitude and place.longitude:
                places.append("{{{{NARA-Place|{0}|{1}|{2}|{3}}}}}"
                              .format(escape(place.name),
                                      place.id,
                                      float(place.latitude),
                                      float(place.longitude)))
            else:
                places.append("{{{{NARA-Place|{0}|{1}}}}}" \
                              .format(escape(place.name),
                                      place.id))
        m['place'] = "<br/>\n".join(places)

        m['location'] = "<br/>\n".join(map(escape, self.item.contacts or ""))

        if isinstance(self.item.date, ItemDate):
            if self.item.date.day:
                m['date'] = "{{{{date|{0}|{1}|{2}}}}}" \
                            .format(self.item.date.year,
                                    self.item.date.month,
                                    self.item.date.day)
            elif self.item.date.month:
                m['date'] = "{{{{date|{0}|{1}}}}}" \
                            .format(self.item.date.year,
                                    self.item.date.month)
            else:
                m['date'] = "{{{{date|{0}}}}}" \
                            .format(self.item.date.year)
        else:
            m['date'] = escape(self.item.date or "")
        
        m['record_group_arc'], m['record_group'] = \
            self.item.record_group or ("", "")
        m['series_arc'], m['series'] = \
            self.item.series or ("", "")
        m['file_unit_arc'], m['file_unit'] = \
            self.item.file_unit or ("", "")
        m['variant_control_numbers'] = "\n" + \
            "<br/>\n".join(["* {0}".format(escape(vcm))
                            for vcm in
                            self.item.variant_control_numbers or []])
        m['tiff'] = "yes" if isinstance(self, TIFFFile) else ""
        
        m['other_versions'] = ""
        # TODO

        return image_template_text.format(**m) + "\n\n" + \
               File.__dict__['wikitext'].fget(self)


class JPEGFile(ImageFile):
    @property
    def canonical_extension(self):
        return ".jpg"
    
    def to_jpeg(self):
        return self


class TIFFFile(ImageFile):
    @property
    def canonical_extension(self):
        return ".tif"


class AudioFile(File):
    pass


class VorbisFile(AudioFile):
    pass


class VideoFile(File):
    pass


class TheoraFile(VideoFile):
    pass


class UploadBot(object):
    def __init__(self,
                 api_url,
                 username,
                 password,
                 index_filename="EAP files",
                 max_size=None,
                 overflow_dir=None,
                 state_filename=None):
        self.api_url = api_url
        self.jar = cookielib.CookieJar()
        self.opener = \
            urllib2.build_opener(urllib2.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [('User-Agent', "narabot.py")]

        print("logging in as [[User:{0}]]... ".format(username),
              end='',
              file=sys.stderr)
        sys.stderr.flush()
        reply = self.api_request(action='login',
                                 lgname=username,
                                 lgpassword=password)
        if reply['result'] == 'NeedToken':
            reply = self.api_request(action='login',
                                     lgname=username,
                                     lgpassword=password,
                                     lgtoken=reply['token'])
        assert reply['result'] == 'Success'
        print("success!", file=sys.stderr)
        
        self.index_filename = index_filename
        self.max_size = max_size
        self.overflow_dir = overflow_dir
        self.skip_filenames = {}
        if state_filename:
            try:
                for filename in open(state_filename).readlines():
                    self.skip_filenames[filename.strip()] = True
            except:
                open(state_filename, 'w').close()
        self.state_filename = state_filename

    def api_request(self, **post_data):
        for key, value in post_data.items():
            if key.endswith('_'):
                new_key = re.sub('_+$', '', key)
                post_data[new_key] = value
                del post_data[key]
        post_data['format'] = 'json'
        response = self.opener.open(self.api_url, urllib.urlencode(post_data))
        response_decoded = json.load(response)
        if not post_data['action'] in response_decoded:
            raise Exception(response_decoded['error']['info'])
        return response_decoded[post_data['action']]
    
    def upload_directory(self, *directories):
        self.upload_batch(UploadBatch(self.index_filename, *directories))

    def upload_batch(self, batch):
        for filename in batch.unknown_filenames:
            print("skipping unknown file '{0}'".format(filename),
                  file=sys.stderr)
        for item in batch:
            self.upload_item(item)

    def upload_item(self, item):
        for file in item.files:
            if file.filename in self.skip_filenames:
                print("file '{0}' was already uploaded"
                      .format(file.filename),
                      file=sys.stderr)
            else:
                self.upload_file(file)

                if self.state_filename:
                    f = open(self.state_filename, 'a')
                    print(file.filename, file=f)
                    f.close()

    def upload_file(self, file):
        wiki_filename = file.wiki_filename

        print("checking for duplicates of '{0}'... "
              .format(file.filename),
              end='',
              file=sys.stderr)
        duplicate_name = self.get_duplicate_name(file)
        if duplicate_name:
            duplicate_name = re.sub('^.+?:', '', duplicate_name)
                                
        if duplicate_name == wiki_filename:
            print()
            print("[[File:{0}]] already exists!".format(duplicate_name),
                  file=sys.stderr)
        elif duplicate_name:
            print()
            self.move_existing_file(duplicate_name, wiki_filename)
        else:
            print("none!", file=sys.stderr)
            
            if self.max_size and self.max_size > file.size:
                if self.overflow_dir:
                    self.upload_big_file(file)
                else:
                    print("file '{0}' exceeds maximum size; skipping",
                          file=sys.stderr)
            else:
                print("uploading '{0}' as [[File:{1}]]... "
                      .format(file.filename, wiki_filename),
                      end='',
                      file=sys.stderr)
                sys.stderr.flush()

                reply = self.api_request(action='query',
                                         prop='info',
                                         titles=duplicate_name,
                                         intoken='edit')
                edit_token = reply['pages'].values()[0]['edittoken']

                form = MultiPartForm()
                form.add_field('action', 'upload')
                form.add_field('filename', wiki_filename)
                #form.add_field('comment', '')
                form.add_field('text', file.wikitext)
                form.add_field('token', edit_token)
                form.add_field('ignorewarnings', 'true')
                form.add_file('file', file.os_filename, 
                              open(file.filename, 'rb'))

                request = urllib2.Request(self.api_url)
                body = str(form)
                request.add_header('Content-type', form.get_content_type())
                request.add_header('Content-length', len(body))
                request.add_data(body)
                response = self.opener.open(request)

                error = re.findall('(?m)^MediaWiki-API-Error: (.*)$',
                                   str(response.info()))
                if error:
                    raise Exception(error[0])
                    print("failed.", file=sys.stderr)
                else:
                    print("success!", file=sys.stderr)
        
        if not isinstance(file, JPEGFile):
            new_basename_root, old_ext = \
                os.path.splitext(os.path.basename(file.filename))
            new_basename = new_basename_root + '.jpg'
            new_filename = tempfile.gettempdir() + os.path.sep + new_basename
            print("converting '{0}' to '{1}'".format(file.filename,
                                                     new_filename),
                  file=sys.stderr)
            jpeg = file.to_jpeg()
            self.upload_file(jpeg)
            print("deleting '{0}'".format(new_filename),
                  file=sys.stderr)
            os.remove(jpeg.filename)
    
    def get_duplicate_name(self, file):
        sha1 = hashlib.sha1()
        f = open(file.filename, 'rb')
        while True:
            block = f.read(512)
            if not block:
                break
            sha1.update(block)
        reply = self.api_request(action='query',
                                 list='allimages',
                                 aisha1=sha1.hexdigest())
        if len(reply['allimages']):
            duplicate_name = reply['allimages'][0]['title']
            return duplicate_name
        else:
            return None

    def move_existing_file(self, old_wiki_filename, new_wiki_filename):
        print("moving [[File:{0}]] to [[File:{1}]]... "
              .format(old_wiki_filename, new_wiki_filename),
              end='',
              file=sys.stderr)
        sys.stderr.flush()
        
        reply = self.api_request(action='query',
                                 prop='info',
                                 titles=old_wiki_filename,
                                 intoken='move')
        move_token = reply['pages'].values()[0]['movetoken']

        reply = self.api_request(action='move',
                                 from_='File:' + old_wiki_filename,
                                 to='File:' + new_wiki_filename,
                                 reason="", #TODO
                                 movetalk=True,
                                 movesubpages=True,
                                 ignorewarnings=True,
                                 token=move_token)
        # TODO change text of new page
        # errors should throw an exception right now...
        if True:
            print("success!", file=sys.stderr)
        else:
            print("failed.", file=sys.stderr)

    def upload_big_file(self, file):
        new_filename = self.overflow_dir + os.path.sep + file.os_filename
        print("copying '{0}' to '{1}'".format(file.filename, new_filename),
              file=sys.stderr)
        shutil.copy(file.filename, new_filename)
        print("writing metadata to '{0}.txt'".format(new_filename),
              file=sys.stderr)
        open(new_filename + '.txt', 'w').write(file.wikitext)


# c/o http://www.doughellmann.com/PyMOTW/urllib2/
class MultiPartForm(object):
    """Accumulate the data to be used when posting a form."""

    def __init__(self):
        self.form_fields = []
        self.files = []
        self.boundary = mimetools.choose_boundary()
        return
    
    def get_content_type(self):
        return 'multipart/form-data; boundary=%s' % self.boundary

    def add_field(self, name, value):
        """Add a simple field to the form data."""
        self.form_fields.append((name, value))
        return

    def add_file(self, fieldname, filename, fileHandle, mimetype=None):
        """Add a file to be uploaded."""
        body = fileHandle.read()
        if mimetype is None:
            mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        self.files.append((fieldname, filename, mimetype, body))
        return
    
    def __str__(self):
        """Return a string representing the form data, including attached files."""
        # Build a list of lists, each containing "lines" of the
        # request.  Each part is separated by a boundary string.
        # Once the list is built, return a string where each
        # line is separated by '\r\n'.  
        parts = []
        part_boundary = '--' + self.boundary
        
        # Add the form fields
        parts.extend(
            [ part_boundary,
              'Content-Disposition: form-data; charset=utf-8; name="%s"' % name,
              '',
              value,
            ]
            for name, value in self.form_fields
            )
        
        # Add the files to upload
        parts.extend(
            [ part_boundary,
              'Content-Disposition: file; name="%s"; filename="%s"' % \
                 (field_name, filename),
              'Content-Type: %s' % content_type,
              '',
              body,
            ]
            for field_name, filename, content_type, body in self.files
            )
        
        # Flatten the list and add closing boundary marker,
        # then return CR+LF separated data
        flattened = list(itertools.chain(*parts))
        flattened.append('--' + self.boundary + '--')
        flattened.append('')
        def encode(s):
            if type(s) is unicode:
                return s.encode('utf-8')
            else:
                return s
        return '\r\n'.join([encode(s) for s in flattened])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description="MediaWiki file uploader for NARA")
    parser.add_argument('directories', metavar='DIR', type=str, nargs='+',
                        help="directory with images to upload")
    parser.add_argument('--username', dest='username', metavar='USERNAME',
                        action='store',
                        help="MediaWiki username (required)")
    parser.add_argument('--password', dest='password', metavar='PASSWORD',
                        action='store',
                        help="MediaWiki password (required)")
    parser.add_argument('--index', dest='index_file', metavar='INDEX_FILE',
                        action='store', default='./EAP files',
                        help="ARC ID index file (default: \"./EAP files\")")
    parser.add_argument('--max-size', dest='max_size', metavar='SIZE',
                        action='store', default=None,
                        help="maximum file size to upload (default: 100 MiB)")
    parser.add_argument('--overflow', dest='overflow_dir',
                        metavar='OVERFLOW_DIR', action='store', default=None,
                        help="directory to store overly-large files in"
                             " (required with --max-size)")
    parser.add_argument('--state-file', dest='state_file',
                        metavar='STATE_FILE', action='store', default=None,
                        help="file to record upload batch state (optional)")
    parser.add_argument('--api', dest='api_url',
                        metavar='API_URL', action='store',
                        default='https://commons.wikimedia.org/w/api.php',
                        help="MediaWiki API endpoint "
                             "(default: Wikimedia Commons' API)")
    args = parser.parse_args()

    if not args.username or not args.password:
        print("error: username and password required",
              file=sys.stderr)
        sys.exit(1)

    bot = UploadBot(api_url=args.api_url,
                    username=args.username,
                    password=args.password,
                    index_filename=args.index_file,
                    max_size=args.max_size,
                    overflow_dir=args.overflow_dir,
                    state_filename=args.state_file)
    bot.upload_directory(*args.directories)
    sys.exit(0)
