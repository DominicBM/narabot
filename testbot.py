
#Bot looks up target file from image directory in the TXT directory and finds its ID
#Checks all other rows in the TXT to see if that ID is repeated for other file names,
#meaning it is multi-page
#Verifies that all the files are in the image directory; if not, logs an error and
#skips so we don't upload partial documents.
#Checks *all* files for duplicates before uploading any.
#Uploads each in sequence with the following changes:
#Titles should indicate page numbers,
#   like "File:<title>_- pg. <x> of <y> -_NARA_-_<ID>.tif".
#The extra characters for this should come out of the title field,
#so the title is truncated shorter rather than the total file name becoming longer
#than single-page documents.
#In "other versions", list only the corresponding JPG/TIFF for that page.
#In "other pages" make two galleries: one with all the JPGs of each page and one
# with all the TIFFs of each page. Also include the DjVu (see below). 
#Uploads a .djvu file created from all of the pages. This will have the canonical (no pg. #) naming convention, since it is a single file. It will also have the same gallery of all the pages in different versions in "other pages," but "other versions" will be blank.
#I am pretty sure imagemagick can handle DjVu conversions compiled from multiple source files, but you might need to look up how that is done (make sure maximum quality/zero compression is always on, as with the TIFF-JPG converts).


#! /usr/bin/python 

###############################################################################
#                                                                             #
#               NARABOT.PY (a batch uploader for Wikipedia)                   # 
#                      Original Code by Fran Rogers                           #
#                 Revised and extended by Joshua Westgard                     #
#                        Version 2.0 - 2014-02-28                             #
#                                                                             #
###############################################################################
#
#  begin imports
#

from __future__ import print_function
from bs4 import BeautifulSoup, NavigableString, SoupStrainer
import cgi
import cookielib
from datetime import date
import hashlib
import image
import itertools
import json
import mimetools
import mimetypes
from collections import namedtuple
import os
import re
import shutil
import sys
import tempfile
import urllib
import urllib2

#
#  end imports
###############################################################################
#  begin variable declarations
#

Author = namedtuple('Author', ['id', 'name'])
ItemDate = namedtuple('ItemDate', ['year', 'month', 'day'])
FileUnit = namedtuple('FileUnit', ['id', 'name'])
Place = namedtuple('Place', ['id', 'name', 'latitude', 'longitude'])
RecordGroup = namedtuple('RecordGroup', ['id', 'name'])
Series = namedtuple('Series', ['id', 'name'])

#
#  end of variable declarations
###############################################################################
#  begin class-independent function definitions
#

def wikitext_escape(s):
    return re.sub(r'([#<>\[\]\|\{\}|]+)', r'<nowiki>\1</nowiki>', s)


def soup_to_plaintext(element):
    out = ""
    for child in element.children:
        if isinstance(child, NavigableString):
            out += str(child) + ' '
        elif child.name == 'br':
            out += '\n' + soup_to_plaintext(child)
        elif child.name == 'p':
            out += '\n\n' + soup_to_plaintext(child)
        else:
            out += soup_to_plaintext(child)
    return out

#
#  end of class-independent function definitions
###############################################################################
#  begin the UPLOAD BATCH class definition
#

class Batch(set):
    def __init__(self, index_filename, *directories):
        f = open(index_filename)
        
        # create dictionary to hold filename/arcid from filelist as key-value pairs
        print("\nUpload Manifest:")
        upload_manifest = {}
        lineno = 1  # track line number in filelist for error reporting
        
        # iterate through the filenames file pulling out filenames and arcids
        for line in f:
            m = re.match('^(.+)\s+([0-9]+)\r?$', line)
            if m:
                filename, arcid = m.groups()
                upload_manifest[filename.lower()] = int(arcid)
            else:
                raise IOError("bad mapping on line {0}: {1}"
                              .format(lineno, line))
            
            # Report the files and arcids captured from each line
            print("LINE {0}: FILE: {1}\tARC ID: {2}".format(lineno, filename, arcid))
            lineno += 1
        
        # create dictionary to hold filenames from upload directory
        item_filenames = {}
        
        # create list for tracking extra files not in the filelist
        self.unknown_filenames = []
        
        # iterate through the specified directories
        for d in directories:
            print("\nSearching directory \"{0}\" for files to upload ...".format(d))
            # for each file found therein
            for f in os.listdir(d):
                # construct the full-path filename and basename,
                # joining relative directory and filename to the abspath
                fullpath = os.path.abspath(os.path.join(d, f))
                print("Full path = {0}".format(fullpath))
                basename = os.path.basename(os.path.join(d, f.lower()))
                print("Basename = {0}".format(basename))
                
                # look in the filename_arcids dictionary for the basename
                # and lookup the arcid for that file
                if basename in upload_manifest:
                    arcid = upload_manifest[basename]
                    
                    # if arcid is already found in item_filenames dictionary,
                    # attach it to that item, otherwise add it as its own item
                    if arcid in item_filenames:
                        item_filenames[arcid].append(fullpath)
                        item_filenames[arcid].sort()
                    else:
                        item_filenames[arcid] = [fullpath]
                
                # add any files not found in filelist to the unknowns list
                else:
                    self.unknown_filenames.append(fullpath)

        print("\nCreated the following upload batch:")
        for a, f in item_filenames.items():
            print("\n{0}:".format(a))
            print("\n".join(f for f in item_filenames[a]))

        # for each set of items (arcid: files) in the item_filenames dictionary
        # iterate through the list of files, creating a file object for each and
        # appending it to a list of files, which in turn is attached to an item
        for arcid, filenames in item_filenames.items():
            files = [File.from_extension(self, f) for f in filenames]
            self.add(Item(arcid, *files))
            

#
#  end of BATCH class definition
###############################################################################
#  beginning of the ITEM class definition
#

class Item(object):
    def __init__(self, arcid, *files):
        print("\nGenerating item for arcid #{0}".format(arcid))
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
        url = 'http://arcweb.archives.gov/arc/action/ExternalIdSearch?id=' + \
               str(self.arcid)
        return(url)
        

    @property
    def __item_page(self):
        if not hasattr(self, '__item_page_cached'):
            self.__item_page_cached = \
                BeautifulSoup(self.__opener.open(self.__item_url).read())
            print(self.__hierarchy_page_cached)
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
        if not hasattr(self, '__contacts'):
            try:
                contacts = \
                    soup_to_plaintext(self.__item_page
                                      .find('p', 'contacts')).split('\n')
                self.__contacts = []
                for contact in contacts:
                    contact = contact.strip()
                    contact = re.sub(' PHONE:.*$', '', contact)
                    if contact:
                        self.__contacts.append(contact)
            except:
                self.__contacts = None

        return self.__contacts        

    @property
    def creators(self):
        if not hasattr(self, '__creators'):
            try:
                creators = \
                    soup_to_plaintext(self.__item_page.find(text='Creator(s):')
                        .parent.next_sibling).split('\n')
                self.__creators = []
                for creator in creators:
                    creator = creator.strip()
                    if creator:
                        self.__creators.append(creator)
            except:
                self.__creators = None

        return self.__creators

    @property
    def dates(self):
        if not hasattr(self, '__dates'):
            date_field = self.__item_page.find(text='Production Date(s):') or \
                         self.__item_page.find(text='Coverage Dates:') or \
                         self.__item_page.find(text='Broadcast Date(s):') or \
                         None

            if date_field:
                date_str = date_field.parent.parent.next_sibling.text.strip()

                date_str = wikitext_escape(date_str)

                date_str = re.sub(r'(?<![{=|])\b(\d+)/(\d+)/(\d+)',
                                  r"{{date|\3|\1|\2}}",
                                  date_str)
                date_str = re.sub(r'(?<![{=|])\b(\d+)/(\d+)',
                                  r"{{date|\2|\1}}",
                                  date_str)
                date_str = re.sub(r'(?<![{=|])\b(\d+)',
                                  r"{{date|\1}}",
                                  date_str)
                
                self.__dates = date_str
            else:
                self.__dates = None

        return self.__dates

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
            try:
                arcid_field = self.__item_page.find('strong', 'arcID').text
                m = re.match('ARC Identifier (.+) / Local Identifier (.+)',
                             arcid_field)
                self.__local_identifier = m.group(2)
            except:
                self.__local_identifier = None
            
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
                vcns = \
                    soup_to_plaintext(self.__item_page.find(
                        text='Variant Control Number(s):')
                        .parent.next_sibling).split('\n')
                self.__variant_control_numbers = []
                for vcn in vcns:
                    vcn = vcn.strip()
                    if vcn:
                        self.__variant_control_numbers.append(vcn)
            except:
                self.__variant_control_numbers = None

        return self.__variant_control_numbers

#
#  end of the ITEM class
###############################################################################
#  beginning of the FILE class
#

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
                      '.tiff': TIFFFile,
                      '.ogg':  VorbisFile,
                      '.oga':  VorbisFile,
                      '.ogv':  TheoraFile}
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
        image.save(new_filename, 'JPEG', quality=100)
        
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
            suffix = ", p. {0} of {1} - NARA - {2}{3}" \
                     .format(self.index + 1,
                             len(self.item.files),
                             self.item.arcid,
                             self.canonical_extension)

        title = self.item.description
        while len(title + suffix) > 120:
            title = re.sub('\s+\S+$', '', title)
        if title == "":
            title = self.item.description[:120 - len(suffix)]

        title = re.sub(r'#|<|>|\[|\]|\||\{|\}|:|/', '-', title)
        title = re.sub('\s+', ' ', title)

        return title + suffix

    @property
    def os_filename(self):
        return re.sub(r'<|>|:|"|/|\\|\||\?|\*', '-', self.wiki_filename)

    @property
    def wikitext(self):
        text  = u"== {{{{int:filedesc}}}} ==\n"
        text += u"{{{{NARA-image-full\n"
        text += u"|Title={title}\n"
        text += u"|Scope and content={scope_and_content}\n"
        text += u"|General notes={general_notes}\n"
        text += u"|ARC={arc}\n"
        text += u"|Local identifier={local_identifier}\n"
        text += u"|Creator={creator}\n"
        text += u"|Author={author}\n"
        text += u"|Place={place}\n"
        text += u"|Location={location}\n"
        text += u"|Date={date}\n"
        text += u"|Record group={record_group}\n"
        text += u"|Record group ARC={record_group_arc}\n"
        text += u"|Series={series}\n"
        text += u"|Series ARC={series_arc}\n"
        text += u"|File unit={file_unit}\n"
        text += u"|File unit ARC={file_unit_arc}\n"
        text += u"|Variant control numbers={variant_control_numbers}\n"
        text += u"|TIFF={tiff}\n"
        text += u"|Other versions={other_versions}\n"
        text += u"}}}}\n\n"
        text += u"== {{{{int:license}}}} ==\n"
        text += u"{{{{NARA-cooperation}}}}\n"
        text += u"{{{{PD-USGov}}}}\n\n"
        text += u"{{{{Uncategorized-NARA|year={{{{subst:CURRENTYEAR}}}}|month={{{{subst:CURRENTMONTHNAME}}}}|day={{{{subst:CURRENTDAY}}}}}}}}"

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

        m['date'] = self.item.dates or ""
        
        m['record_group_arc'], m['record_group'] = \
            self.item.record_group or ("", "")
        m['series_arc'], m['series'] = \
            self.item.series or ("", "")
        m['file_unit_arc'], m['file_unit'] = \
            self.item.file_unit or ("", "")
        m['variant_control_numbers'] = \
            "\n*".join(map(escape, self.item.variant_control_numbers or []))
        m['tiff'] = "yes" if isinstance(self, TIFFFile) else ""

        m['other_versions'] = ""
        if isinstance(self.item[0], TIFFFile):
            m['other_versions'] = \
                "<gallery>\nFile:{0}|.tif\nFile:{1}|.jpg\n</gallery>".format(
                    self.item[0].wiki_filename,
                    self.item[0].wiki_filename[:-4] + ".jpg")
        
        return text.format(**m)

#
# End of the FILE class
###############################################################################
# Begin various file type class definitions
#

class ImageFile(File):
    pass


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
    @property
    def canonical_extension(self):
        return ".oga"


class VideoFile(File):
    pass


class TheoraFile(VideoFile):
    @property
    def canonical_extension(self):
        return ".ogv"

#
#  end the class definitions for various file types
###############################################################################
#  begin the UPLOAD BOT class definiton
#

class UploadBot(object):
    def __init__(self,
                 api_url,
                 username,
                 password,
                 index_filename="EAP files",
                 max_size=None,
                 overflow_dir=None,
                 state_filename=None,
                 unknowns_filename=None):
        self.api_url = api_url
        self.jar = cookielib.CookieJar()
        self.opener = \
            urllib2.build_opener(urllib2.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [('User-Agent', "narabot.py")]
        
        print("Creating a test bot ...\n")
        print("Logging in as [[User:{0}]] ... ".format(username),
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
        print("success!\n", file=sys.stderr)
        
        self.index_filename = index_filename
        self.max_size = max_size
        self.overflow_dir = overflow_dir
        self.skip_filenames = {}
        
        self.unknowns_filename = unknowns_filename
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
        print("Preparing the upload batch ... ")
        self.upload_batch(Batch(self.index_filename, *directories))


    def upload_batch(self, batch):
        if self.unknowns_filename:
            open(self.unknowns_filename, 'a').write(
                "\n".join(batch.unknown_filenames))
        print("\nSkipping Extra Files")
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
            
            if self.max_size and file.size > self.max_size:
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
                form.add_field('comment', file.wikitext)
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
        
        if isinstance(file, ImageFile) and not isinstance(file, JPEGFile):
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
                                 reason="Moving to proper filename "
                                        "per NARA metadata",
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

#
# End of the UPLOAD BOT class definition
###############################################################################
# Beginning of the MULTI-PART FORM class
# c/o http://www.doughellmann.com/PyMOTW/urllib2/
#

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

#    
# end of MULTI-PART FORM class
###############################################################################
# The main section, runs if this module is run as the main program
#

if __name__ == '__main__':
    
    print("\n\n\n")
    print("*********************************************************")
    print("*                      NARABOT                          *")
    print("*  A Batch Loader for NARA images in WikiMedia Commons  *")
    print("*                 -- Version 2.0 --                     *")    
    print("*********************************************************")
    print("\nWelcome!  Preparing the batch for uploading...\n")
    
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
                        action='store', default=None, type=int,
                        help="maximum file size to upload in bytes"
                             " (optional)")
    parser.add_argument('--overflow', dest='overflow_dir',
                        metavar='OVERFLOW_DIR', action='store', default=None,
                        help="directory to store overly-large files in"
                             " (required with --max-size)")
    parser.add_argument('--unknowns-file', dest='unknowns_file',
                        metavar='STATE_FILE', action='store', default=None,
                        help="file to record unknown files (optional)")
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
                    state_filename=args.state_file,
                    unknowns_filename=args.unknowns_file)
    bot.upload_directory(*args.directories)
    sys.exit(0)
