#!/usr/bin/env python3

import argparse
import errno
import json
import logging
import os
import sys
import copy
import tempfile

from contextlib import closing
from tarfile import TarFile
from tarfile import ExtractError

from constants import OWNER_READ_WRITE
from constants import DIRECTORY_MODE
from constants import OWNER_WRITE

LOG = logging.getLogger(__name__)

class TarFileOverrides(TarFile):
    def extractall(self, path=".", members=None, *, numeric_owner=False):
        """Extract all members from the archive to the current working
           directory and set owner, modification time and modified permissions 
           on directories afterwards. `path' specifies a different directory
           to extract to. `members' is optional and must be a subset of the
           list returned by getmembers(). If `numeric_owner` is True, only
           the numbers for user/group names are used and not the names.
           
           Directory permissions are modified so the owner is 'rwx', allowing 
           subsequent extractions of image layers to be added to the same file
           system. Without this permission modification, the extraction silently
           fails and the file system object is not added to the composite file 
           system.
        """
        directories = []

        if members is None:
            members = self

        for tarinfo in members:
            if tarinfo.isdir():
                # Extract directories with a safe mode.
                directories.append(tarinfo)
                tarinfo = copy.copy(tarinfo)
                tarinfo.mode = OWNER_READ_WRITE
            # Do not set_attrs directories, as we will do that further down
            self.extract(tarinfo, path, set_attrs=not tarinfo.isdir(),
                         numeric_owner=numeric_owner)

        # Reverse sort directories.
        directories.sort(key=lambda a: a.name)
        directories.reverse()

        # Set correct owner, mtime and filemode on directories.
        for tarinfo in directories:
            dirpath = os.path.join(path, tarinfo.name)
            try:
                self.chown(tarinfo, dirpath, numeric_owner=numeric_owner)
                self.utime(tarinfo, dirpath)
                if tarinfo.mode & DIRECTORY_MODE:
                    tarinfo.mode = tarinfo.mode | OWNER_WRITE
                self.chmod(tarinfo, dirpath)
            except ExtractError as e:
                if self.errorlevel > 1:
                    raise
                else:
                    self._dbg(1, "tarfile: %s" % e)

def parse_args():
    p = argparse.ArgumentParser()

    p.add_argument('--ignore-errors', '-i',
                   action='store_true',
                   help='Ignore OS errors when extracting files')
    p.add_argument('--archive', '-a',
                   default='.',
                   help='Archive file (defaults to stdin)')
    p.add_argument('--output', '-o',
                   default='.',
                   help='Output directory (defaults to ".")')
    p.add_argument('--verbose', '-v',
                   action='store_const',
                   const=logging.INFO,
                   dest='loglevel')
    p.add_argument('--debug', '-d',
                   action='store_const',
                   const=logging.DEBUG,
                   dest='loglevel')
    p.add_argument('--layers',
                   action='store_true',
                   help='List layers in an image')
    p.add_argument('--list', '--ls',
                   action='store_true',
                   help='List images/tags contained in archive')
    p.add_argument('--layer', '-l',
                   action='append',
                   help='Extract only the specified layer')
    p.add_argument('--no-whiteouts', '-W',
                   action='store_true',
                   help='Do not process whiteout (.wh.*) files')
    p.add_argument('image', nargs='?')

    p.set_defaults(level=logging.WARN)
    return p.parse_args()


def find_layers(img, id):
    with closing(img.extractfile('%s/json' % id)) as fd:
        info = json.load(fd)

    LOG.debug('layer = %s', id)
    for k in ['os', 'architecture', 'author', 'created']:
        if k in info:
            LOG.debug('%s = %s', k, info[k])

    yield id
    if 'parent' in info:
        pid = info['parent']
        for layer in find_layers(img, pid):
            yield layer


def main():
    args = parse_args()
    logging.basicConfig(level=args.loglevel)

    with tempfile.NamedTemporaryFile() as fd:
        if args.archive != '.':
            fd = open(args.archive, mode='rb')
        else:
            while True:
                data = sys.stdin.buffer.read(8192)
                if not data:
                    break
                fd.write(data)
            fd.seek(0)

        with TarFileOverrides(fileobj=fd) as img:
            repos = img.extractfile('repositories')
            repos = json.load(repos)

            if args.list:
                for name, tags in repos.items():
                    print('%s: %s' % (
                        name,
                        ' '.join(tags)))
                sys.exit(0)

            if not args.image:
                if len(repos) == 1:
                    args.image = next(iter(repos.keys()))
                else:
                    LOG.error('No image name specified and multiple '
                              'images contained in archive')
                    sys.exit(1)
            try:
                name, tag = args.image.split(':', 1)
            except ValueError:
                name, tag = args.image, next(iter(repos[args.image].keys()))

            try:
                top = repos[name][tag]
            except KeyError:
                LOG.error('failed to find image %s with tag %s',
                          name,
                          tag)
                sys.exit(1)

            LOG.info('extracting image %s (%s)', name, top)
            layers = list(find_layers(img, top))

            if args.layers:
                print('\n'.join(reversed(layers)))
                sys.exit(0)

            if not os.path.isdir(args.output):
                os.mkdir(args.output)

            for id in reversed(layers):
                if args.layer and id not in args.layer:
                    continue

                LOG.info('extracting layer %s', id)
                with TarFileOverrides(
                        fileobj=img.extractfile('%s/layer.tar' % id),
                        errorlevel=(0 if args.ignore_errors else 1)) as layer:
                    layer.extractall(path=args.output)
                    if not args.no_whiteouts:
                        LOG.info('processing whiteouts')
                        for member in layer.getmembers():
                            path = member.path
                            if path.startswith('.wh.') or '/.wh.' in path:
                                if path.startswith('.wh.'):
                                    newpath = path[4:]
                                else:
                                    newpath = path.replace('/.wh.', '/')

                                try:
                                    LOG.info('removing path %s', newpath)
                                    os.unlink(path)
                                    os.unlink(newpath)
                                except OSError as err:
                                    if err.errno != errno.ENOENT:
                                        raise


if __name__ == '__main__':
    main()
